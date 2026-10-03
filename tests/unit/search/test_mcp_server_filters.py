"""The MCP search tools fail closed on malformed caller filters (spec D3, D11).

Caller filters are a hard search scope, so every malformed one — an unknown
key, a non-ISO date, an explicitly empty ``tag_ids``, or a mis-keyed
``filters`` container (L11) — is a tool error naming the offending key, never
the sanitised "search failed" text and never an unscoped search. Driven over
the in-memory MCP transport against a stub core, so every rejection is also
proven to happen before the core is called.

Split from ``test_mcp_server.py`` for the §3.1 500-line ceiling, as
``test_mcp_server_asker.py`` / ``_fetch.py`` / ``_keyword_search.py`` are.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent

from store.models import KeywordPage, SearchFilters
from tests.helpers.factories import make_search_result, make_search_settings
from tests.helpers.search import build_stub_mcp_app as _app

# (tool name, the name of its query argument, the core method it calls)
_SEARCH_TOOLS = [
    ("semantic_search", "query", "retrieve"),
    ("deep_search", "question", "answer"),
    ("keyword_search", "query", "keyword_search"),
]

_MALFORMED_FILTERS = [
    ({"tag_id": 5}, "tag_id"),
    ({"tags": [5]}, "tags"),
    ({"tag_ids": []}, "tag_ids"),
    ({"date_from": "junk"}, "date_from"),
    ({"date_to": "2025-04-25junk"}, "date_to"),
    ({"date_from": "20250425"}, "date_from"),
    ({"date_to": "2025-W17-5"}, "date_to"),
    ({"date_to": "9999-12-31"}, "date_to"),
    ({"correspondent_id": 2**63}, "correspondent_id"),
    ({"tag_ids": [2**64]}, "tag_ids"),
    ({"tag_ids": [True]}, "tag_ids"),
    ({"tag_ids": ["5"]}, "tag_ids"),
    ({"correspondent_id": 0}, "correspondent_id"),
    ({"document_type_id": -1}, "document_type_id"),
]


def _core() -> MagicMock:
    core = MagicMock()
    core.retrieve.return_value = make_search_result(answer="", sources=())
    core.answer.return_value = make_search_result(sources=())
    core.keyword_search.return_value = KeywordPage(hits=(), total=0, offset=0, limit=20)
    core.settings = make_search_settings()
    return core


def _text(result: CallToolResult) -> str:
    return " ".join(
        block.text for block in result.content if isinstance(block, TextContent)
    )


def _ui_filters(core: MagicMock, method: str) -> SearchFilters | None:
    """The ``ui_filters`` the tool handed to *method* (kwarg or 2nd positional)."""
    call = getattr(core, method).call_args
    return call.kwargs["ui_filters"] if "ui_filters" in call.kwargs else call.args[1]


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "query_arg", "method"), _SEARCH_TOOLS)
@pytest.mark.parametrize(("filters", "key"), _MALFORMED_FILTERS)
async def test_malformed_filters_are_rejected_naming_the_key(
    tool: str, query_arg: str, method: str, filters: dict[str, object], key: str
) -> None:
    core = _core()
    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool(tool, {query_arg: "boiler", "filters": filters})

    assert result.isError is True
    text = _text(result)
    assert key in text
    assert "search failed" not in text
    getattr(core, method).assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "query_arg", "method"), _SEARCH_TOOLS)
async def test_an_iso_timestamp_is_accepted_and_normalised(
    tool: str, query_arg: str, method: str
) -> None:
    core = _core()
    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool(
            tool,
            {
                query_arg: "boiler",
                "filters": {"date_from": "2025-04-25T00:00:00+00:00", "tag_ids": [7]},
            },
        )

    assert result.isError is False
    ui_filters = _ui_filters(core, method)
    assert ui_filters is not None
    assert ui_filters.date_from == "2025-04-25"
    assert ui_filters.tag_ids == (7,)


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "query_arg", "method"), _SEARCH_TOOLS)
@pytest.mark.parametrize("arguments", [{}, {"filters": {}}, {"filters": None}])
async def test_absent_or_empty_filters_mean_no_filters(
    tool: str, query_arg: str, method: str, arguments: dict[str, object]
) -> None:
    core = _core()
    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool(tool, {query_arg: "boiler", **arguments})

    assert result.isError is False
    assert _ui_filters(core, method) is None


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "query_arg", "method"), _SEARCH_TOOLS)
@pytest.mark.parametrize("container", ["filter", "Filters"])
async def test_a_mis_keyed_filters_container_is_rejected(
    tool: str, query_arg: str, method: str, container: str
) -> None:
    """L11: FastMCP would otherwise drop the key and run an unscoped search."""
    core = _core()
    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool(
            tool, {query_arg: "boiler", container: {"tag_ids": [7]}}
        )

    assert result.isError is True
    assert container in _text(result)
    getattr(core, method).assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "query_arg", "method"), _SEARCH_TOOLS)
async def test_a_correctly_keyed_filters_container_reaches_the_core(
    tool: str, query_arg: str, method: str
) -> None:
    core = _core()
    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        result = await client.call_tool(
            tool, {query_arg: "boiler", "filters": {"tag_ids": [7, 9]}}
        )

    assert result.isError is False
    ui_filters = _ui_filters(core, method)
    assert ui_filters is not None
    assert ui_filters.tag_ids == (7, 9)


@pytest.mark.anyio
async def test_every_tool_schema_forbids_undeclared_arguments() -> None:
    """``tools/list`` publishes ``additionalProperties: false`` on all five."""
    async with create_connected_server_and_client_session(
        _app(_core())._fastmcp
    ) as client:
        listed = await client.list_tools()

    schemas = {tool.name: tool.inputSchema for tool in listed.tools}
    assert set(schemas) == {
        "semantic_search",
        "deep_search",
        "keyword_search",
        "fetch_documents",
        "list_filters",
    }
    assert all(
        schema.get("additionalProperties") is False for schema in schemas.values()
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tool", [tool for tool, _, _ in _SEARCH_TOOLS] + ["keyword_search"]
)
async def test_the_filters_schema_publishes_the_strict_filter_rules(tool: str) -> None:
    """The inner object is closed too: it names the five fields and forbids the
    rest, rather than FastMCP's open ``additionalProperties: true`` object."""
    async with create_connected_server_and_client_session(
        _app(_core())._fastmcp
    ) as client:
        listed = await client.list_tools()

    filters = next(t for t in listed.tools if t.name == tool).inputSchema["properties"][
        "filters"
    ]
    (object_schema, null_schema) = filters["anyOf"]
    assert null_schema == {"type": "null"}
    assert object_schema["additionalProperties"] is False
    assert set(object_schema["properties"]) == {
        "date_from",
        "date_to",
        "correspondent_id",
        "document_type_id",
        "tag_ids",
    }


@pytest.mark.anyio
async def test_filters_sent_as_a_json_string_are_parsed_then_validated() -> None:
    """Some clients stringify object arguments; FastMCP parses the string, and
    the same fail-closed rules then apply — a typo is still rejected."""
    core = _core()
    async with create_connected_server_and_client_session(
        _app(core)._fastmcp
    ) as client:
        scoped = await client.call_tool(
            "semantic_search", {"query": "boiler", "filters": '{"tag_ids": [7]}'}
        )
        typo = await client.call_tool(
            "semantic_search", {"query": "boiler", "filters": '{"tag_id": 7}'}
        )
        string_id = await client.call_tool(
            "semantic_search", {"query": "boiler", "filters": '{"tag_ids": ["7"]}'}
        )

    assert scoped.isError is False
    ui_filters = _ui_filters(core, "retrieve")
    assert ui_filters is not None
    assert ui_filters.tag_ids == (7,)
    assert typo.isError is True
    assert "tag_id" in _text(typo)
    assert string_id.isError is True
    assert "tag_ids" in _text(string_id)
    assert core.retrieve.call_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("list_filters", {"filters": {"tag_ids": [7]}}),
        ("fetch_documents", {"document_ids": [1], "filter": {"tag_ids": [7]}}),
    ],
)
async def test_the_zero_llm_tools_reject_undeclared_arguments_too(
    tool: str, arguments: dict[str, object]
) -> None:
    """The strict server covers all five tools, not only the search tools."""
    async with create_connected_server_and_client_session(
        _app(_core())._fastmcp
    ) as client:
        result = await client.call_tool(tool, arguments)

    assert result.isError is True
    assert "unknown argument" in _text(result)
