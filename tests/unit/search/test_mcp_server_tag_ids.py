"""MCP search results carry each document's tag ids (spec D4).

A tag-scoped caller verifies the scope held from these ids. ``semantic_search``
and ``deep_search`` serialise ``SourceDocument`` with ``dataclasses.asdict``, so
``tag_ids`` rides along; a pruned row's ids are unknown and serialise as
``null``, never as ``[]`` (which would read as "no tags" — a leak). Every
``keyword_search`` document carries a list (``test_mcp_server_keyword_search.py``).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from tests.helpers.factories import (
    make_search_result,
    make_search_settings,
    make_source_document,
)
from tests.helpers.search import build_stub_mcp_app as _app


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
