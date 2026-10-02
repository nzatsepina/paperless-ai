"""MCP search results carry each document's tag ids (spec D4).

A tag-scoped caller verifies the scope held from these ids. ``semantic_search``
and ``deep_search`` serialise ``SourceDocument`` with ``dataclasses.asdict``, so
``tag_ids`` rides along; a pruned row's ids are unknown and serialise as
``null``, never as ``[]`` (which would read as "no tags" — a leak). Every
``keyword_search`` document carries a list.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from search.mcp_server import _McpApp, build_mcp_app
from search.offload import LazySemaphore
from store.models import DocumentSummary, KeywordHit, KeywordPage
from tests.helpers.factories import (
    make_search_result,
    make_search_settings,
    make_source_document,
)


def _app(core: MagicMock) -> _McpApp:
    return build_mcp_app(
        lambda _app_db_path: core,
        "unused-app-db-path",
        search_semaphore=LazySemaphore(0),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "query_arg", "method"),
    [("semantic_search", "query", "retrieve"), ("deep_search", "question", "answer")],
)
async def test_sources_carry_tag_ids_and_null_for_a_pruned_row(
    tool: str, query_arg: str, method: str
) -> None:
    core = MagicMock()
    getattr(core, method).return_value = make_search_result(
        sources=(
            make_source_document(document_id=1, tag_ids=(101, 102)),
            make_source_document(document_id=2, tag_ids=None),
        )
    )
    core.settings = make_search_settings()

    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool(tool, {query_arg: "boiler"})

    block = result.content[0]
    assert isinstance(block, TextContent)
    sources = json.loads(block.text)["sources"]
    assert [source["tag_ids"] for source in sources] == [[101, 102], None]


@pytest.mark.anyio
async def test_keyword_search_documents_carry_tag_ids() -> None:
    summary = DocumentSummary(
        id=42,
        title="Invoice 2024",
        correspondent=None,
        document_type=None,
        tags=("tax",),
        tag_ids=(101,),
        created=None,
        page_count=1,
    )
    core = MagicMock()
    core.keyword_search.return_value = KeywordPage(
        hits=(KeywordHit(document=summary, snippet="total", rank=-1.0),),
        total=1,
        offset=0,
        limit=20,
    )
    core.settings = make_search_settings()

    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool("keyword_search", {"query": "invoice"})

    block = result.content[0]
    assert isinstance(block, TextContent)
    assert json.loads(block.text)["documents"][0]["tag_ids"] == [101]
