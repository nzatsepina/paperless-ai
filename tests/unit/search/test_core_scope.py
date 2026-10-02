"""SearchCore keeps the caller scope on every relaxation site (spec D1, D9).

The retriever's choke point re-applies the scope at the store, so these tests
observe each *site* above it — the specs handed to ``Retriever.retrieve`` and
the ``refine`` phase detail — where reverting one site fix turns a test red
even though the choke point would still scope the store call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from search.cache import reset_search_result_cache
from search.models import PhaseRecord
from tests.helpers.factories import (
    make_chunk_hit,
    make_facet_set,
    make_indexed_document,
    make_search_filters,
    make_search_settings,
    make_taxonomy_entry,
)
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    needs_more_response_json,
    planner_response_json,
)
from tests.unit.search.conftest import build_search_core

# Placeholder tenant tag — no real taxonomy id.
_TAG_A = 101


def _npower_facets() -> object:
    return make_facet_set(
        correspondents=(
            make_taxonomy_entry(kind="correspondent", entry_id=10, name="npower"),
        )
    )


def _per_text_embedding_client() -> MagicMock:
    client = MagicMock()
    client.embed.side_effect = lambda texts: [[0.1] for _ in texts]
    return client


def _records(events: list) -> list[PhaseRecord]:
    return [event for event in events if isinstance(event, PhaseRecord)]


def test_refinement_specs_carry_the_caller_scope() -> None:
    """Leak site L3: every re-plan spec (twins included) carries the scope.

    Observed on the ``refine`` phase detail, not the store call — the choke
    point would re-scope the store call and hide a reverted site fix.
    """
    reset_search_result_cache()
    scope = make_search_filters(tag_ids=(_TAG_A,))
    store_reader = MagicMock()
    store_reader.list_facets.return_value = _npower_facets()
    store_reader.vector_search.return_value = [
        make_chunk_hit(chunk_id=1, document_id=1)
    ]
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = [make_indexed_document(document_id=1)]
    core = build_search_core(
        settings=make_search_settings(SEARCH_MAX_REFINEMENTS=1),
        llm_client=ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[_make_spec(semantic="boiler details")]
            ),
            synthesiser_responses=[
                needs_more_response_json("Look for the npower contract."),
                answered_response_json("Answer [1].", citations=[1]),
            ],
            replan_response=planner_response_json(
                specs=[_make_spec(semantic="npower contract", correspondent="npower")]
            ),
        ),
        store_reader=store_reader,
        embedding_client=_per_text_embedding_client(),
    )
    events: list = []

    core.answer("what boiler do I have?", ui_filters=scope, on_event=events.append)

    refine = next(r for r in _records(events) if r.phase == "refine")
    assert refine.detail["noop"] is False
    new_specs = refine.detail["new_specs"]
    assert len(new_specs) == 2  # the re-plan spec + its scope-keeping twin
    assert all(spec["filters"]["tag_ids"] == [_TAG_A] for spec in new_specs)
