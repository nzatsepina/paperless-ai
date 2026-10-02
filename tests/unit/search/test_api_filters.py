"""HTTP search endpoints fail closed on malformed caller filters (spec D3, D11).

``POST /api/search`` and ``/api/search/stream`` sit behind API-key auth and
serve programmatic callers, not only the SPA, so a malformed filter — unknown
key, mis-keyed ``filters`` container (L11), non-ISO date, or explicit empty
``tag_ids`` — is FastAPI's standard 422, never an unscoped 200.

Split from ``test_api.py`` for the §3.1 500-line ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.users import create as create_user
from tests.helpers.factories import make_search_result, make_search_settings
from tests.helpers.search import mint_api_key
from tests.unit.search.conftest import build_test_client

_ENDPOINTS = ["/api/search", "/api/search/stream"]


@dataclass(frozen=True)
class _ApiHarness:
    client: TestClient
    headers: dict[str, str]
    core: MagicMock


def _client_and_headers() -> _ApiHarness:
    """A test client, a valid API-key header, and the stub core behind it."""
    settings = make_search_settings(INDEX_DB_PATH="/nonexistent/index.db")
    core = MagicMock()
    core.answer.return_value = make_search_result()
    client = build_test_client(settings, core=core)
    conn = connect(settings.APP_DB_PATH)
    try:
        user = create_user(
            conn, username="api-user", password_hash=hash_password("pw"), role="member"
        )
        raw_key = mint_api_key(conn, owner_user_id=user.id, scopes="api")
    finally:
        conn.close()
    return _ApiHarness(client, {"Authorization": f"Bearer {raw_key}"}, core)


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
@pytest.mark.parametrize(
    "body",
    [
        {"query": "boiler", "filters": {"tag_id": 5}},
        {"query": "boiler", "filter": {"tag_ids": [5]}},
        {"query": "boiler", "Filters": {"tag_ids": [5]}},
        {"query": "boiler", "filters": {"date_from": "junk"}},
        {"query": "boiler", "filters": {"date_to": "2025-W17-5"}},
        {"query": "boiler", "filters": {"date_to": "9999-12-31"}},
        {"query": "boiler", "filters": {"tag_ids": []}},
    ],
)
def test_malformed_filters_are_a_422(endpoint: str, body: dict[str, object]) -> None:
    harness = _client_and_headers()

    response = harness.client.post(endpoint, json=body, headers=harness.headers)

    assert response.status_code == 422
    harness.core.answer.assert_not_called()


@pytest.mark.parametrize("endpoint", _ENDPOINTS)
def test_filters_without_a_tag_ids_key_are_accepted(endpoint: str) -> None:
    harness = _client_and_headers()

    response = harness.client.post(
        endpoint,
        json={"query": "boiler", "filters": {"date_from": "2025-01-01"}},
        headers=harness.headers,
    )

    assert response.status_code == 200
    ui_filters = harness.core.answer.call_args.kwargs["ui_filters"]
    assert ui_filters.tag_ids == ()
    assert ui_filters.date_from == "2025-01-01"
