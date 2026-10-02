"""Tests for the retriever's caller-scope choke point (spec D2).

``Retriever.retrieve(specs, scope=…)`` re-applies the caller's filters to every
spec before any store call, so no relaxation path — recall twins, broaden,
refinement — can widen a caller-scoped search. Each scope test runs with two
DIFFERENT scopes so the value is pinned, not a literal
(review-lessons: "A spy test asserts a value; it does not pin a behaviour").
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from search.models import RetrievalSpec
from search.retriever import _EMPTY_FILTERS, Retriever, _intersect
from store.reader import SearchFilters
from tests.helpers.factories import (
    make_chunk_hit,
    make_search_filters,
    make_search_settings,
)

# Placeholder tenant tags — no real taxonomy id.
_TAG_A = 101
_TAG_B = 202


def _unfiltered(mode: str, text: str) -> RetrievalSpec:
    """A spec carrying no filters at all — the shape a relaxed twin used to have."""
    return RetrievalSpec(
        mode=mode,  # type: ignore[arg-type]
        semantic=text if mode == "semantic" else None,
        keywords=(text,) if mode == "keyword" else (),
        filters=_EMPTY_FILTERS,
        rationale="unfiltered",
    )


def _retriever() -> tuple[Retriever, MagicMock]:
    """A Retriever over a mock store whose every pass returns one hit."""
    store_reader = MagicMock()
    store_reader.vector_search.return_value = [make_chunk_hit(chunk_id=1)]
    store_reader.keyword_search.return_value = [make_chunk_hit(chunk_id=2)]
    embedding_client = MagicMock()
    embedding_client.embed.side_effect = lambda texts: [[0.1] for _ in texts]
    retriever = Retriever(make_search_settings(), store_reader, embedding_client)
    return retriever, store_reader


@pytest.mark.parametrize("tag_id", [_TAG_A, _TAG_B])
def test_every_store_call_carries_the_caller_scope(tag_id: int) -> None:
    """An unfiltered spec still reaches the store scoped to the caller's tag."""
    scope = make_search_filters(tag_ids=(tag_id,))
    retriever, store_reader = _retriever()

    retriever.retrieve(
        (
            _unfiltered("semantic", "first"),
            _unfiltered("semantic", "second"),
            _unfiltered("keyword", "term"),
        ),
        scope=scope,
    )

    expected = _intersect(_EMPTY_FILTERS, scope)
    vector_calls = store_reader.vector_search.call_args_list
    keyword_calls = store_reader.keyword_search.call_args_list
    assert len(vector_calls) == 2
    assert len(keyword_calls) == 1
    assert all(call.args[2] == expected for call in vector_calls)
    assert all(call.args[2] == expected for call in keyword_calls)
    assert expected.tag_ids == (tag_id,)


def test_scope_narrows_a_spec_that_carries_its_own_filters() -> None:
    """A spec's planner filter survives; the caller scope is added on top."""
    scope = make_search_filters(tag_ids=(_TAG_A,), date_to="2024-12-31")
    spec = RetrievalSpec(
        mode="semantic",
        semantic="query",
        keywords=(),
        filters=make_search_filters(correspondent_id=7, date_to="2025-06-30"),
        rationale="planner spec",
    )
    retriever, store_reader = _retriever()

    retriever.retrieve((spec,), scope=scope)

    passed = store_reader.vector_search.call_args.args[2]
    assert passed == SearchFilters(
        date_from=None,
        date_to="2024-12-31",
        correspondent_id=7,
        document_type_id=None,
        tag_ids=(_TAG_A,),
    )


def test_no_scope_passes_each_spec_filters_unchanged() -> None:
    """``scope=None`` — an unscoped caller — leaves every spec's filters as is."""
    own = make_search_filters(correspondent_id=7)
    spec = RetrievalSpec(
        mode="semantic", semantic="q", keywords=(), filters=own, rationale="r"
    )
    retriever, store_reader = _retriever()

    retriever.retrieve((spec,), scope=None)

    assert store_reader.vector_search.call_args.args[2] is own


def test_intersect_is_idempotent_for_dates_ids_and_duplicate_tags() -> None:
    """Re-applying a scope to an already-scoped filter changes nothing."""
    spec_filters = make_search_filters(
        date_from="2024-01-01",
        date_to="2024-12-31",
        correspondent_id=7,
        tag_ids=(3, 3, 9),
    )
    scope = make_search_filters(
        date_from="2024-03-01",
        date_to="2025-01-31",
        document_type_id=4,
        tag_ids=(9, _TAG_A, _TAG_A),
    )

    once = _intersect(spec_filters, scope)

    assert _intersect(once, scope) == once
    assert once.tag_ids == (3, 9, _TAG_A)
