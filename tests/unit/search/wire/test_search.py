"""Tests for the search wire models in search.wire.search.

Covers: SearchRequest enforces the query length bounds at the HTTP boundary —
an empty or whitespace-only query is rejected with a ValidationError (HTTP-04,
§10.4/§10.6), so it never reaches the bounded LLM pipeline and burns budget;
a query over the maximum length is rejected; a valid query is trimmed of
surrounding whitespace so the pipeline sees one normalised form (HTTP-07).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from search.wire import MAX_QUERY_LENGTH, FilterRequest, SearchRequest


def test_search_request_accepts_a_normal_query() -> None:
    """A non-empty query within bounds validates and is preserved."""
    request = SearchRequest(query="what is my gas bill total")
    assert request.query == "what is my gas bill total"


def test_search_request_rejects_an_empty_query() -> None:
    """An empty query is rejected at the boundary, never dispatched to the LLM."""
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_rejects_a_whitespace_only_query() -> None:
    """A whitespace-only query is rejected — it is empty after trimming."""
    with pytest.raises(ValidationError):
        SearchRequest(query="   \t\n  ")


def test_search_request_trims_surrounding_whitespace() -> None:
    """A valid query is trimmed so the pipeline sees one normalised form."""
    request = SearchRequest(query="  invoices from acme  ")
    assert request.query == "invoices from acme"


def test_search_request_rejects_a_query_over_the_maximum_length() -> None:
    """A query longer than MAX_QUERY_LENGTH is rejected at the boundary."""
    with pytest.raises(ValidationError):
        SearchRequest(query="x" * (MAX_QUERY_LENGTH + 1))


def test_search_request_accepts_a_query_at_the_maximum_length() -> None:
    """A query of exactly MAX_QUERY_LENGTH characters validates."""
    request = SearchRequest(query="x" * MAX_QUERY_LENGTH)
    assert len(request.query) == MAX_QUERY_LENGTH


def test_filter_request_accepts_up_to_64_tag_ids() -> None:
    """A filter naming up to 64 tags validates (L16)."""
    filters = FilterRequest(tag_ids=list(range(1, 65)))
    assert len(filters.tag_ids) == 64


def test_filter_request_rejects_over_64_tag_ids() -> None:
    """A filter naming more than 64 tags is rejected, matching the GET bound (L16)."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=list(range(1, 66)))


# ---------------------------------------------------------------------------
# FilterRequest — malformed caller filters fail closed (spec D3, D11)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [{"tag_id": 5}, {"tags": [5]}])
def test_filter_request_rejects_an_unknown_key(raw: dict[str, object]) -> None:
    """A typo'd key would otherwise widen a scoped search with no error."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FilterRequest.model_validate(raw)


def test_filter_request_rejects_an_explicitly_empty_tag_list() -> None:
    with pytest.raises(ValidationError, match="tag_ids must not be empty"):
        FilterRequest.model_validate({"tag_ids": []})


@pytest.mark.parametrize("raw", [{}, {"correspondent_id": 3}])
def test_filter_request_without_tag_ids_means_no_tag_constraint(
    raw: dict[str, object],
) -> None:
    assert FilterRequest.model_validate(raw).tag_ids == []


@pytest.mark.parametrize("field", ["date_from", "date_to"])
@pytest.mark.parametrize(
    "value", ["junk", "2025-04-25junk", "20250425", "2025-W17-5", "2025-13-01"]
)
def test_filter_request_rejects_a_non_iso_date(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match="must be an ISO date"):
        FilterRequest.model_validate({field: value})


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ("2025-04-25", "2025-04-25"),
        ("2025-04-25T00:00:00+00:00", "2025-04-25"),
        ("2025-04-25T23:30:00-05:00", "2025-04-25"),
    ],
)
def test_filter_request_stores_the_date_of_an_iso_value(
    value: str, stored: str
) -> None:
    request = FilterRequest.model_validate({"date_from": value, "date_to": value})
    assert (request.date_from, request.date_to) == (stored, stored)


@pytest.mark.parametrize("field", ["date_from", "date_to"])
def test_filter_request_rejects_the_last_representable_date(field: str) -> None:
    """``9999-12-31`` has no next day, so the store's exclusive upper bound
    would overflow; it is rejected here with a clear error instead."""
    with pytest.raises(ValidationError, match="before 9999-12-31"):
        FilterRequest.model_validate({field: "9999-12-31"})


def test_filter_request_accepts_an_inverted_date_range() -> None:
    """``date_from`` after ``date_to`` narrows to nothing — it cannot leak, so
    it is not rejected."""
    request = FilterRequest.model_validate(
        {"date_from": "2025-12-31", "date_to": "2025-01-01"}
    )
    assert (request.date_from, request.date_to) == ("2025-12-31", "2025-01-01")


def test_search_request_rejects_a_mis_keyed_filters_container() -> None:
    """``filter`` for ``filters`` would otherwise read as "no filters"."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SearchRequest.model_validate({"query": "x", "filter": {"tag_ids": [1]}})


# FilterRequest — strict int validation (security: reject lax coercion of booleans, strings, floats)


def test_filter_request_rejects_tag_ids_with_boolean() -> None:
    """A filter with a boolean in tag_ids is rejected — strict int only."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=[True])


def test_filter_request_rejects_tag_ids_with_string() -> None:
    """A filter with a string in tag_ids is rejected — no lax coercion of "5"."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=["5"])


def test_filter_request_rejects_tag_ids_with_float() -> None:
    """A filter with a float in tag_ids is rejected — strict int only."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=[5.0])


def test_filter_request_rejects_tag_ids_with_zero() -> None:
    """A filter with zero in tag_ids is rejected — ids must be positive."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=[0])


def test_filter_request_rejects_tag_ids_with_negative() -> None:
    """A filter with negative ids in tag_ids is rejected — ids must be positive."""
    with pytest.raises(ValidationError):
        FilterRequest(tag_ids=[-1])


def test_filter_request_accepts_tag_ids_with_valid_integers() -> None:
    """A filter with valid positive integers in tag_ids validates."""
    filters = FilterRequest(tag_ids=[1, 2, 3])
    assert filters.tag_ids == [1, 2, 3]


def test_filter_request_rejects_correspondent_id_with_boolean() -> None:
    """A filter with correspondent_id=true is rejected — strict int only."""
    with pytest.raises(ValidationError):
        FilterRequest(correspondent_id=True)  # type: ignore[arg-type]


def test_filter_request_rejects_correspondent_id_with_zero() -> None:
    """A filter with correspondent_id=0 is rejected — ids must be positive."""
    with pytest.raises(ValidationError):
        FilterRequest(correspondent_id=0)


def test_filter_request_rejects_correspondent_id_with_negative() -> None:
    """A filter with correspondent_id=-1 is rejected — ids must be positive."""
    with pytest.raises(ValidationError):
        FilterRequest(correspondent_id=-1)


def test_filter_request_accepts_correspondent_id_with_valid_integer() -> None:
    """A filter with valid positive correspondent_id validates."""
    filters = FilterRequest(correspondent_id=42)
    assert filters.correspondent_id == 42


def test_filter_request_rejects_document_type_id_with_zero() -> None:
    """A filter with document_type_id=0 is rejected — ids must be positive."""
    with pytest.raises(ValidationError):
        FilterRequest(document_type_id=0)


def test_filter_request_rejects_document_type_id_with_negative() -> None:
    """A filter with document_type_id=-1 is rejected — ids must be positive."""
    with pytest.raises(ValidationError):
        FilterRequest(document_type_id=-1)


def test_filter_request_accepts_document_type_id_with_valid_integer() -> None:
    """A filter with valid positive document_type_id validates."""
    filters = FilterRequest(document_type_id=99)
    assert filters.document_type_id == 99


@pytest.mark.parametrize(
    "raw",
    [
        {"correspondent_id": 2**63},
        {"document_type_id": 2**63},
        {"tag_ids": [1, 2**63]},
    ],
)
def test_filter_request_rejects_an_id_above_the_sqlite_integer_range(
    raw: dict[str, object],
) -> None:
    """An id SQLite cannot bind is rejected here, not as a 500 at the store."""
    with pytest.raises(ValidationError, match="less than or equal to"):
        FilterRequest.model_validate(raw)


def test_filter_request_accepts_the_largest_sqlite_integer_id() -> None:
    assert FilterRequest(correspondent_id=2**63 - 1).correspondent_id == 2**63 - 1


def test_filter_request_names_the_offending_tag_id_by_index() -> None:
    """The error locates the bad element, like the sibling id fields."""
    with pytest.raises(ValidationError, match=r"tag_ids\.1\s+Input should be greater"):
        FilterRequest.model_validate({"tag_ids": [5, 0]})
