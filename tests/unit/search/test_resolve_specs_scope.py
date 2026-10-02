"""Recall twins keep the caller scope (spec D1, leak sites L1/L3).

A twin strips the planner's guesses only: its filters are
``_intersect(_EMPTY_FILTERS, ui_filters)``. The existing twin tests in
``test_resolve_specs.py`` (``ui_filters=None``) pin the unscoped behaviour
(R2/R6) and stay unchanged.
"""

from __future__ import annotations

from datetime import date

import pytest

from search.models import PlannedSpec, RetrievalPlan
from search.refinement import raw_rag_plan
from search.retriever import _EMPTY_FILTERS, _intersect, resolve_specs
from tests.helpers.factories import (
    make_facet_set,
    make_filter_candidates,
    make_search_filters,
)
from tests.helpers.factories import make_taxonomy_entry as _entry

_TODAY = date(2025, 6, 10)
# Placeholder tenant tags — no real taxonomy id.
_TAG_A = 101
_TAG_B = 202


def _facets() -> object:
    return make_facet_set(
        correspondents=(_entry(kind="correspondent", entry_id=132, name="eBay"),),
    )


def _guessing_spec(semantic: str = "find something") -> PlannedSpec:
    """A planner spec whose correspondent guess resolves to a real id."""
    return PlannedSpec(
        mode="semantic",
        semantic=semantic,
        keywords=(),
        filter_guess=make_filter_candidates(correspondent="eBay"),
        rationale="planner guess",
    )


@pytest.mark.parametrize("tag_id", [_TAG_A, _TAG_B])
def test_twin_strips_planner_guesses_but_keeps_the_caller_scope(tag_id: int) -> None:
    scope = make_search_filters(tag_ids=(tag_id,))
    plan = RetrievalPlan(specs=(_guessing_spec(),))

    specs = resolve_specs(plan, _facets(), ui_filters=scope, today=_TODAY, max_specs=8)

    assert len(specs) == 2
    assert specs[0].filters.correspondent_id == 132
    assert specs[0].filters.tag_ids == (tag_id,)
    assert specs[1].filters == _intersect(_EMPTY_FILTERS, scope)
    assert specs[1].semantic == specs[0].semantic


def test_scoped_dated_query_twins_keep_the_scope() -> None:
    """The date safety net's twin (leak path L1 via L4) keeps the scope too."""
    scope = make_search_filters(tag_ids=(_TAG_A,))

    specs = resolve_specs(
        raw_rag_plan("salary in April 2025"),
        _facets(),
        ui_filters=scope,
        today=_TODAY,
        query="salary in April 2025",
        max_specs=8,
    )

    assert specs
    assert all(_TAG_A in spec.filters.tag_ids for spec in specs)


def test_scoped_raw_rag_plan_appends_no_twin() -> None:
    """semantic_search's plan: each spec's only filter is the scope, so each
    twin equals its original and the dedup drops it."""
    scope = make_search_filters(tag_ids=(_TAG_A,))

    specs = resolve_specs(
        raw_rag_plan("boiler warranty"),
        _facets(),
        ui_filters=scope,
        today=_TODAY,
        query="boiler warranty",
        max_specs=8,
    )

    assert [spec.mode for spec in specs] == ["semantic", "keyword"]
    assert all(spec.filters == _intersect(_EMPTY_FILTERS, scope) for spec in specs)
