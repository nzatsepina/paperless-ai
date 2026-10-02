"""Caller filters are a hard search scope — end to end against a real store.

Two tenants share one archive and are kept apart by tag. Tenant B's chunks sit
on the query axis and tenant A's off it, so any unscoped pass ranks B *first*
and a leak cannot hide below the top-K cut. Every assertion reads each returned
document's tags back from the store (``get_documents``), never from the new
``tag_ids`` result field, so the check does not depend on the code under test.

One forcing input per leak site (spec "Tests & verification"): L1 recall twins,
L1 via the date safety net, L2 broaden on an empty scope and on an embedding
outage, L3 refinement, L8 keyword search, and R6 for an unscoped caller.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from unittest.mock import MagicMock

from common.embeddings import EmbeddingError
from search.core import SearchCore
from store.models import SearchFilters, TaxonomyEntry
from store.reader import StoreReader
from store.writer import StoreWriter
from tests.helpers.llm import (
    ScriptedLLMClient,
    _make_spec,
    answered_response_json,
    needs_more_response_json,
    planner_response_json,
)
from tests.helpers.search import build_search_core
from tests.integration.conftest import (
    AXIS_BOILER,
    AXIS_OTHER,
    make_axis_embedding_client,
    make_pipeline_settings,
    seed_pipeline_document,
)

# Placeholder tenant tags — no real taxonomy id.
_TAG_A = 101
_TAG_B = 202
_TAG_NOBODY = 303
_NAME_A = "tenant-a"
_NAME_B = "tenant-b"
_A_IDS = (1, 2)
_B_IDS = (3, 4)


def _scope(tag_id: int) -> SearchFilters:
    return SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(tag_id,),
    )


def _seed_two_tenants(tmp_path: Path) -> MagicMock:
    """Seed tenant A off the query axis and tenant B on it; return settings."""
    settings = make_pipeline_settings(tmp_path)
    writer = StoreWriter(settings)
    try:
        writer.refresh_taxonomy(
            [
                TaxonomyEntry(kind="tag", id=_TAG_A, name=_NAME_A),
                TaxonomyEntry(kind="tag", id=_TAG_B, name=_NAME_B),
                TaxonomyEntry(kind="tag", id=_TAG_NOBODY, name="tenant-nobody"),
            ]
        )
        for document_id in _A_IDS:
            seed_pipeline_document(
                writer,
                document_id=document_id,
                title=f"Tenant A boiler warranty {document_id}",
                text="The boiler warranty for this flat runs until 2027.",
                embedding=AXIS_OTHER,
                tag_ids=(_TAG_A,),
            )
        for document_id in _B_IDS:
            seed_pipeline_document(
                writer,
                document_id=document_id,
                title=f"Tenant B boiler warranty {document_id}",
                text="The boiler warranty and gasket service plan run until 2028.",
                embedding=AXIS_BOILER,
                tag_ids=(_TAG_B,),
            )
    finally:
        writer.close()
    return settings


def _core(
    settings: MagicMock,
    reader: StoreReader,
    *,
    llm_client: ScriptedLLMClient | None = None,
    embedding_client: MagicMock | None = None,
) -> SearchCore:
    return build_search_core(
        settings=settings,
        llm_client=llm_client
        or ScriptedLLMClient(
            planner_response=planner_response_json(), synthesiser_responses=[]
        ),
        store_reader=reader,
        embedding_client=embedding_client or make_axis_embedding_client(AXIS_BOILER),
    )


def _assert_all_carry(
    reader: StoreReader, document_ids: Iterable[int], name: str
) -> None:
    """Every returned document carries the scope tag, read back from the store."""
    ids = set(document_ids)
    tags_by_id = {doc.id: doc.tags for doc in reader.get_documents(ids)}
    assert set(tags_by_id) == ids
    leaked = {doc_id: tags for doc_id, tags in tags_by_id.items() if name not in tags}
    assert not leaked, f"documents outside the scope were returned: {leaked}"


def test_scoped_semantic_search_returns_only_the_scope(tmp_path: Path) -> None:
    """L1: recall twins no longer drop the caller's tag."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    try:
        result = _core(settings, reader).retrieve(
            "boiler warranty", ui_filters=_scope(_TAG_A)
        )
        ids = [source.document_id for source in result.sources]
        assert ids
        _assert_all_carry(reader, ids, _NAME_A)
    finally:
        reader.close()


def test_scoped_dated_semantic_search_returns_only_the_scope(tmp_path: Path) -> None:
    """L1 via L4: the date safety net's twin keeps the caller's tag."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    try:
        result = _core(settings, reader).retrieve(
            "boiler warranty in 2024", ui_filters=_scope(_TAG_A)
        )
        ids = [source.document_id for source in result.sources]
        assert ids
        _assert_all_carry(reader, ids, _NAME_A)
    finally:
        reader.close()


def test_scope_matching_no_document_returns_nothing(tmp_path: Path) -> None:
    """L2: an empty first pass is not broadened past the caller's tag."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    try:
        result = _core(settings, reader).retrieve(
            "boiler warranty", ui_filters=_scope(_TAG_NOBODY)
        )
        assert result.sources == ()
    finally:
        reader.close()


def test_embedding_outage_with_no_scoped_keyword_hit_returns_nothing(
    tmp_path: Path,
) -> None:
    """L2 (outage): no vector pass and an empty scoped FTS pass stay empty."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    embedding_client = MagicMock()
    embedding_client.embed.side_effect = EmbeddingError("embedding endpoint down")
    try:
        result = _core(settings, reader, embedding_client=embedding_client).retrieve(
            "gasket", ui_filters=_scope(_TAG_A)
        )
        assert result.sources == ()
    finally:
        reader.close()


def test_scoped_deep_search_refinement_returns_only_the_scope(tmp_path: Path) -> None:
    """L3: the refinement re-plan keeps the caller's tag."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(
            specs=[
                _make_spec(semantic="boiler warranty"),
                _make_spec(mode="keyword", semantic=None, keywords=["warranty"]),
            ]
        ),
        synthesiser_responses=[
            needs_more_response_json("Look for the boiler service plan."),
            # citations=[] keeps every retrieved source in the result, so a
            # leaked document cannot hide behind the citation filter.
            answered_response_json("The warranty runs until 2027.", citations=[]),
        ],
        replan_response=planner_response_json(
            specs=[_make_spec(semantic="boiler service plan")]
        ),
    )
    try:
        result = _core(settings, reader, llm_client=llm_client).answer(
            "when does my boiler warranty end?", ui_filters=_scope(_TAG_A)
        )
        assert llm_client.replan_calls == 1
        ids = [source.document_id for source in result.sources]
        assert ids
        _assert_all_carry(reader, ids, _NAME_A)
    finally:
        reader.close()


def test_scoped_keyword_search_returns_only_the_scope(tmp_path: Path) -> None:
    """L8: keyword search and filter-only browse honour the caller's tag."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    try:
        core = _core(settings, reader)
        for query in ("warranty", None):
            page = core.keyword_search(query, _scope(_TAG_A), 20, 0)
            ids = [hit.document.id for hit in page.hits]
            assert ids
            _assert_all_carry(reader, ids, _NAME_A)
    finally:
        reader.close()


def test_multiple_scope_tags_are_anded(tmp_path: Path) -> None:
    """D6: two scope tags require both; no seeded document carries both."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    both = SearchFilters(
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(_TAG_A, _TAG_B),
    )
    try:
        result = _core(settings, reader).retrieve("boiler warranty", ui_filters=both)
        assert result.sources == ()
    finally:
        reader.close()


def test_unscoped_search_still_reaches_both_tenants(tmp_path: Path) -> None:
    """R6: with no filters, both tenants' documents are reachable, as today."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    try:
        result = _core(settings, reader).retrieve("boiler warranty", ui_filters=None)
        ids = {source.document_id for source in result.sources}
        assert ids & set(_A_IDS)
        assert ids & set(_B_IDS)
    finally:
        reader.close()


def test_unscoped_deep_search_still_reaches_both_tenants(tmp_path: Path) -> None:
    """R6 on ``answer()``: with no filters, both tenants stay reachable."""
    settings = _seed_two_tenants(tmp_path)
    reader = StoreReader(settings)
    llm_client = ScriptedLLMClient(
        planner_response=planner_response_json(),
        # citations=[] keeps every retrieved source in the result, so the
        # reachability check does not depend on what the answer cites.
        synthesiser_responses=[
            answered_response_json("Both warranties are on file.", citations=[])
        ],
    )
    try:
        result = _core(settings, reader, llm_client=llm_client).answer(
            "boiler warranty", ui_filters=None
        )
        ids = {source.document_id for source in result.sources}
        assert ids & set(_A_IDS)
        assert ids & set(_B_IDS)
    finally:
        reader.close()
