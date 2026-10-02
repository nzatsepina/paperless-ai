# Caller Filters Are a Hard Search Scope — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every document a search returns satisfies every filter the caller sent — on MCP `semantic_search` / `deep_search` / `keyword_search` and HTTP `POST /api/search` / `/api/search/stream` — while recall insurance keeps relaxing only what the planner guessed, malformed caller filters fail closed, and results expose each document's tag ids.

**Architecture:** One choke point — `Retriever.retrieve(specs, *, scope)` re-intersects every spec with the caller scope before any store call — plus fixes at the three relaxation sites (recall twins, broaden-and-retry, refinement twins) so they stop producing specs the choke point would collapse. `FilterRequest` / `SearchRequest` forbid unknown keys, validate dates and reject an explicit empty `tag_ids`; a `_StrictFastMCP` subclass rejects undeclared MCP tool arguments and publishes `additionalProperties: false`. `IndexedDocument` / `DocumentSummary` / `SourceDocument` carry raw `tag_ids`; the SPA stops sending an empty `tag_ids`.

**Tech Stack:** Python 3.11+ (pydantic 2.13, `mcp` 1.29 FastMCP, FastAPI, sqlite-vec store), pytest + pytest-xdist; React/TypeScript SPA with vitest.

**Spec:** `.claude/specs/20261002-caller-scope-hard.md` (approved; `ecaeb28`). Decisions D1–D11 are law; read the spec before any task.

## Global Constraints

- **Caller filters are a hard scope (D1).** "Caller filters" = `ui_filters` as built by `to_search_filters()` (`src/search/wire/search.py`). Twins, broaden, refinement twins and any future relaxation strip **planner guesses only**.
- **`scope` is a required keyword argument with no default** on `Retriever.retrieve()` (D2); a deliberate `scope=None` means "no caller scope". `keyword_search` never enters `Retriever` and is held by test only (L8).
- **Fail closed at the boundary (D3, D11)** on MCP **and** HTTP: unknown key inside `filters`; mis-keyed container (`filter`, `Filters`); non-ISO `date_from` / `date_to`; explicit `tag_ids: []`. `filters` omitted, `None` or `{}` still means "no filters". `date_from > date_to` is **not** rejected.
- **Date rule:** accept only when `normalise_iso_date()` returns a date **and** `datetime.fromisoformat()` parses the whole string **and** the parsed date equals the ten-character prefix; store that `YYYY-MM-DD`. (The third check is a plan-time tightening — see *Spec ambiguity resolved*.)
- **Error contract:** a rejected filter reaches the MCP client as a message naming the key — never the sanitised `"search failed — see server logs"`; `raise ValueError(...) from exc` (CODE_GUIDELINES §6.3). HTTP returns FastAPI's standard 422.
- **Multiple `tag_ids` stay AND (D6).** Documented, not changed.
- **`tag_ids` on results (D4):** `IndexedDocument.tag_ids` / `DocumentSummary.tag_ids` are **required** `tuple[int, ...]` (raw ids, not names); `SourceDocument.tag_ids: tuple[int, ...] | None = None` **after** `relevance_tier`, `None` for a pruned row. HTTP response models stay unchanged.
- **D9:** skip a broaden whose searches (`_spec_search_key()` set) are all in pass 1's; skip branch returns `_BroadenOutcome(chunks=[], signal=<pass-1 signal>, broadened=False)`.
- **§5.8:** `_retrieve_with_broaden()` returns the frozen `_BroadenOutcome` dataclass, not a 3-tuple.
- **§3.1 — all three limits (file lines, function executable body lines, imported names) on every touched file, tests included** (spec Risks: the file headers *and* "touched functions stay within §3.1"). No splits — a split would move unrelated code and widen the diff past the leak fix; every exception is §3.1's own `# rationale:` carve-out:
  - **File headers** (over 500 lines, no header today): `src/search/mcp_server.py` (B2 — its header also covers the 30-name import cap: the module already imports 40 names, and B2 adds five — `Sequence`, `ToolError`, `ValidationError` and the type-only `ContentBlock` / `MCPTool` — for the strict server and the filter error, taking it to 45), `src/store/reader/_lookups.py` (C1), `src/search/models.py` (C2); and the four over-ceiling test files this change grows — `tests/unit/search/test_core.py`, `tests/unit/search/test_core_trace.py` (A3), `tests/helpers/factories/_search.py`, `tests/unit/search/test_document_routes.py` (C1). `src/search/core.py`'s existing header covers its length only; A1 extends it to its import count (66 names, unchanged by this change).
  - **Touched functions over the 60-line ceiling** get a `# rationale:` immediately above the `def`, stating why the function stays whole in this change: `SearchCore._refine()` (A1), `list_documents()` (C1), `_register_search_tools()` (B2, then S1). §3.1's count is executable body lines excluding only the signature, decorators, docstring and blank lines, so the registrar counts its nested tool closures: 211 on `ecaeb28`, 190 on the merged replay — over before this change, shortened by it. B2 moves the three tool descriptions it lengthens into module-level constants (`_SEMANTIC_SEARCH_DESCRIPTION`, `_DEEP_SEARCH_DESCRIPTION`, `_KEYWORD_SEARCH_DESCRIPTION`) to shrink the registrar, not to bring it under the ceiling; the `# rationale:` states the pre-existing cause. Every other function this plan edits stays at or under 60 executable body lines (measured on the merged replay). Over-limit functions in touched files that this plan does **not** edit (`SearchCore._answer_uncached()`, `to_search_response()`, `list_filters_with_counts()`) are outside the spec's "touched functions" clause and are left as they are.
- **Tests encoding the old drop are re-targeted or inverted, never deleted** (GATES: a red gate is never greened by deletion).
- **Public repository:** no host, container, domain, client, downstream project, real taxonomy id or person anywhere — every id in code, tests and prose is a placeholder (`101`, `202`, `"tenant-a"`).
- **Every command block runs in the venv, in the worktree that owns the task.** Shell state does not persist between an agent's tool calls, so each block starts with `source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"` (run from that worktree's root). A tool resolved from anywhere else — above all `pip-audit` in G1, which would audit the wrong environment and pass silently — invalidates the result. `web/node_modules` is per checkout: every worktree that runs `npm`/`npx` installs it first (`cd web && npm ci`).
- **British English** in prose, comments, docstrings and commit messages; identifiers follow the existing code.
- **Commits:** Conventional Commits, ambient git identity (no `-c user.*`, no `GIT_AUTHOR_*`), no AI attribution. One commit per task unless a task says otherwise.
- **Plan code was executed, not just written:** every Python/TS block below was applied to a copy of `ecaeb28`, track by track, and `ruff check`, `ruff format --check`, `mypy src`, the full pytest suite, `npm run typecheck`, `npm run lint` and `npm run test:coverage` were green; each test block was red before its code block. The one formatting fix-up is named where it occurs (Task A1).

## Spec ambiguity resolved at plan time

- **The week form passes the spec's two date checks.** `"2025-W17-5"` passes both `normalise_iso_date()` (its first ten characters parse with `date.fromisoformat`, which accepts ISO week dates on Python 3.11+) and `datetime.fromisoformat()` — probed on the repo venv, Python 3.12 — yet it is exactly the non-`YYYY-MM-DD` form the spec says the store's lexical comparison cannot use, and `normalise_iso_date()` would store it verbatim. The plan adds a third check (the parsed date's `isoformat()` must equal the ten-character prefix) and a `"2025-W17-5"` rejection test. This tightens, never loosens, the approved rule; the DECISIONS entry (Task E1) records it.
- **MCP boundary tests live in new sibling files**, not in `tests/unit/search/test_mcp_server.py` / `test_mcp_server_keyword_search.py` as the spec lists: `test_mcp_server.py` is already 785 lines (§3.1), and the repo already splits that suite (`test_mcp_server_asker.py`, `_fetch.py`, `_keyword_search.py`). Same for `test_api_filters.py` (`test_api.py` is 482 lines), `test_core_scope.py` and `test_resolve_specs_scope.py`.

## Review Focus

Inputs and conditions the spec implies but does not enumerate, most likely to bite first — each now has a test in the owning task:

1. **An MCP client that stringifies the `filters` object** (`"filters": "{\"tag_id\": 7}"`). FastMCP parses the JSON string first; the same fail-closed rules must then apply — a typo still rejected, a valid string still scoped. → Task B2, `test_filters_sent_as_a_json_string_are_parsed_then_validated`.
2. **An undeclared argument on a zero-LLM tool** (`list_filters({"filters": …})`, `fetch_documents(..., filter=…)`). The strict server must cover all five tools, not just the three search tools. → Task B2, `test_the_zero_llm_tools_reject_undeclared_arguments_too`.
3. **Several scope tags at once** — a caller expecting any-of gets AND (D6); no document carrying only one tag may leak through. → Task A1, `test_multiple_scope_tags_are_anded`.
4. **An inverted date range** (`date_from` after `date_to`) — must be accepted and match nothing, not 422 (spec: "it narrows to nothing, which cannot leak"). → Task B1, `test_filter_request_accepts_an_inverted_date_range`.
5. **A timezone-offset timestamp near midnight** (`"2025-04-25T23:30:00-05:00"`) — stored as the date of the value as written (`2025-04-25`), not shifted to UTC. → Task B1, `test_filter_request_stores_the_date_of_an_iso_value`.

---

## Tracks and file sets

Tracks A–E run in parallel, one worktree each, branched from `fix/caller-scope-hard`. Tasks inside a track are sequential. The serial phase starts once every track has merged back. Before its first task, each track's branch and worktree are created from the feature worktree (`.claude/worktrees/caller-scope-hard`); the path is anchored on the main checkout, so it never nests inside the feature worktree:

```bash
WT="$(git rev-parse --path-format=absolute --git-common-dir)/../.claude/worktrees"
for track in a b c d e; do
  git worktree add -b "fix/caller-scope-hard-$track" "$WT/caller-scope-hard-$track" fix/caller-scope-hard
done
```

Track A → branch `fix/caller-scope-hard-a`, worktree `$WT/caller-scope-hard-a`; B → `fix/caller-scope-hard-b`, `$WT/caller-scope-hard-b`; likewise C, D and E. Each track's implementer runs every command from its own worktree's root.

| Track | Tasks | Files (exact) |
|---|---|---|
| **A — retriever / core** | A1 → A2 → A3 | `src/search/retriever.py`, `src/search/core.py`, `tests/integration/conftest.py`, `tests/integration/test_caller_scope.py` (new), `tests/integration/test_salary_april_regression.py`, `tests/unit/search/test_retriever.py`, `tests/unit/search/test_retriever_multispec.py`, `tests/unit/search/test_retriever_scope.py` (new), `tests/unit/search/test_resolve_specs_scope.py` (new), `tests/unit/search/test_core_scope.py` (new), `tests/unit/search/test_core_sources.py`, `tests/unit/search/test_core.py`, `tests/unit/search/test_core_trace.py` |
| **B — wire / MCP boundary** | B1 → B2 | `src/search/wire/search.py`, `src/search/mcp_server.py`, `tests/unit/search/wire/test_search.py`, `tests/unit/search/test_api_filters.py` (new), `tests/unit/search/test_mcp_server_filters.py` (new) |
| **C — result shape `tag_ids`** | C1 → C2 | `src/store/models.py`, `src/store/reader/_lookups.py`, `src/store/reader/_browse.py`, `src/search/models.py`, `src/search/sources.py`, `tests/helpers/factories/_search.py`, `tests/unit/store/test_reader_tag_ids.py` (new), `tests/unit/store/test_schema.py`, `tests/unit/store/test_models.py`, `tests/unit/search/test_fetch.py`, `tests/unit/search/test_mcp_server_fetch.py`, `tests/unit/search/test_mcp_server_keyword_search.py`, `tests/unit/search/test_document_routes.py`, `tests/unit/search/wire/test_library.py`, `tests/unit/search/test_sources.py` |
| **D — SPA request body** | D1 | `web/src/api/client/search.ts`, `web/src/api/client/searchStream.ts`, `web/src/api/client/search.test.ts` (new), `web/src/api/client/searchStream.test.ts` |
| **E — docs + decision** | E1 | `docs/search-pipeline.md`, `.claude/DECISIONS.md` |
| **Serial** | I1 → S1 → G1 → M1 | S1: `src/search/mcp_server.py`, `tests/unit/search/test_mcp_server_tag_ids.py` (new). G1/M1 change no file. |

**Disjointness, checked:** no file appears in two rows. **Interface independence, checked:** A's tests build `IndexedDocument` only through `make_indexed_document()` (C adds a *defaulted* `tag_ids` parameter, so A needs nothing from C); B's tests stub the core; C never touches `Retriever`, `FilterRequest` or `mcp_server.py`. The one consumer of two tracks' output — MCP `keyword_search` emitting `DocumentSummary.tag_ids` from inside B's `mcp_server.py` — is Task S1, serial after the merge. Each track was also applied alone to `ecaeb28` and its suite run green (B and C without A, A without B and C).

| Task | Model | Why |
|---|---|---|
| 0 | Haiku | run-and-report |
| A1 | Opus | the choke point every other guarantee rests on; touches both core modules and 27 test call sites |
| A2 | Sonnet | one site fix with its tests given verbatim |
| A3 | Opus | D9 skip semantics, the §5.8 carrier, two re-targeted tests — the subtlest change in the plan |
| B1 | Sonnet | well-scoped validators and tests |
| B2 | Opus | security boundary; subclasses a third-party server and moves the error path |
| C1 | Sonnet | mechanical field threading through 16 construction sites (+ the factory), script given |
| C2 | Sonnet | one optional field, one builder |
| D1 | Sonnet | small TS change with tests |
| E1 | Sonnet | prose against fixed anchors |
| I1 | Haiku | merges and a suite run |
| S1 | Sonnet | one line and its tests |
| G1 | Haiku | run every gate, report |
| M1 | Sonnet | fourteen break/run/restore cycles; judgement only on reading which test went red |

---

## Task 0: Environment and baseline (Haiku)

**Files:** none modified.

The worktree has no `.venv` of its own; the venv lives in the main checkout and **also holds a non-editable install of this package in `site-packages`**. Under pytest that is harmless — `pyproject.toml` sets `pythonpath = ["src"]`, which puts the worktree's `src` first (verified: `search.__file__` resolves to `<worktree>/src/search/__init__.py` inside a test). A bare `python -c "import search"` would import the *installed* copy and silently test the wrong code, so every ad-hoc probe outside pytest uses `PYTHONPATH=src`. The worktree also has no `web/node_modules`.

- [ ] **Step 1: Activate the venv** (from the worktree root):

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python --version   # expect 3.11+
```

- [ ] **Step 2: Prove pytest imports the worktree's code**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
# Inside this worktree's git dir: writable, never committed, never /tmp root.
PROBE="$(git rev-parse --path-format=absolute --git-dir)/scope-check"
mkdir -p "$PROBE" && printf 'def test_where():\n    import search\n    print("SEARCH_AT", search.__file__)\n' > "$PROBE/test_where.py"
python -m pytest -s -p no:cacheprovider --rootdir=. -c pyproject.toml "$PROBE/test_where.py" | grep SEARCH_AT
rm -r "$PROBE"
```

Expected: `SEARCH_AT <worktree>/src/search/__init__.py`. **Anything under `site-packages` → stop and report**: every later red/green (and every mutation) would be meaningless.

- [ ] **Step 3: Install the SPA dependencies**

```bash
(cd web && npm ci)
```

- [ ] **Step 4: Baseline the Python suite**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest -n auto
```

Expected: exit 0 (pytest's `addopts` already carries `-q`; do not add another, it suppresses the summary). A red baseline → stop and report; do not start the tracks on a red tree.

No commit.

---

## Track A — retriever / core

### Task A1: End-to-end forcing inputs and the retriever choke point (Opus)

**Files:**
- Modify: `tests/integration/conftest.py` (`seed_pipeline_document()` gains `tag_ids`)
- Create: `tests/integration/test_caller_scope.py`
- Create: `tests/unit/search/test_retriever_scope.py`
- Modify: `tests/unit/search/test_retriever.py`, `tests/unit/search/test_retriever_multispec.py`, `tests/integration/test_salary_april_regression.py` (27 `retriever.retrieve(` calls gain `scope=None`)
- Modify: `src/search/retriever.py` (`Retriever.retrieve()`, `Retriever._run_passes()`)
- Modify: `src/search/core.py` (`_retrieve_phase()`, `_retrieve_with_broaden()`, `_refine()` pass the scope; `# rationale:` above `_refine()` and the header's import-cap line — §3.1)

**Interfaces:**
- Produces: `Retriever.retrieve(specs: tuple[RetrievalSpec, ...], *, scope: SearchFilters | None) -> tuple[list[RetrievedChunk], RetrievalSignal]`; `Retriever._run_passes(specs, scope)`; `SearchCore._retrieve_with_broaden(plan, specs, facets, today, ui_filters)` (still a 3-tuple here — A3 changes the return); `seed_pipeline_document(..., tag_ids: tuple[int, ...] = ())`.
- Consumes: `_intersect()` and `_EMPTY_FILTERS` (`src/search/retriever.py`, unchanged).

The integration module is the spec's forcing-input table against a **real** SQLite store (review-lessons: a mocked seam does not guard the logic beneath it). Tenant B sits on the query axis, tenant A off it, so any unscoped pass ranks B first and a leak cannot hide below top-K; every assertion reads tags back from the store with `get_documents()`, never from the new `tag_ids` field.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/conftest.py`, replace:

```python
    created: str = "2024-01-15T00:00:00+00:00",
) -> None:
```

with:

```python
    created: str = "2024-01-15T00:00:00+00:00",
    tag_ids: tuple[int, ...] = (),
) -> None:
```

In `tests/integration/conftest.py`, replace:

```python
            documents that only fall within a date-scoped retrieval filter.
```

with:

```python
            documents that only fall within a date-scoped retrieval filter.
        tag_ids: The document's tag ids; lets a test seed tag-scoped tenants.
```

In `tests/integration/conftest.py`, replace:

```python
        tag_ids=(),
        created=created,
```

with:

```python
        tag_ids=tag_ids,
        created=created,
```

Create `tests/integration/test_caller_scope.py`:

```python
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
```

Save this script as `add_scope_none.py` in the session scratchpad directory your system prompt names (never the repository, never /tmp root) and run it from the worktree root (`python <scratchpad>/add_scope_none.py`); it asserts every count before it writes and stops on any drift — it never commits:

```python
"""Append ``scope=None`` to every ``retriever.retrieve(...)`` call in the given files.

Asserts the per-file call count before editing so a drifted file fails loudly.
"""

import pathlib
import sys

EXPECTED = {
    "tests/unit/search/test_retriever_multispec.py": 7,
    "tests/unit/search/test_retriever.py": 19,
    "tests/integration/test_salary_april_regression.py": 1,
}
NEEDLE = "retriever.retrieve("

for name, expected in EXPECTED.items():
    path = pathlib.Path(name)
    text = path.read_text()
    assert text.count(NEEDLE) == expected, (name, text.count(NEEDLE))
    out, pos = [], 0
    while (start := text.find(NEEDLE, pos)) != -1:
        depth, i = 1, start + len(NEEDLE)
        while depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        close = i - 1
        inner = text[start + len(NEEDLE) : close]
        assert "scope=" not in inner, (name, inner)
        sep = "" if inner.strip() == "" else ", "
        trailing = inner.rstrip()
        if trailing.endswith(","):
            sep = " "
        out.append(text[pos:start] + NEEDLE + trailing + sep + "scope=None" + inner[len(trailing):])
        pos = close
    out.append(text[pos:])
    new = "".join(out)
    assert new.count("scope=None") == expected, name
    path.write_text(new)
    print(name, "edited", expected)
sys.exit(0)
```

Create `tests/unit/search/test_retriever_scope.py`:

```python
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
```


Then normalise the long lines the script produced (the only formatter fix-up in the plan):

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
ruff format tests/unit/search/test_retriever.py tests/unit/search/test_retriever_multispec.py tests/integration/test_salary_april_regression.py
```

- [ ] **Step 2: Run them and watch them fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/integration/test_caller_scope.py tests/unit/search/test_retriever_scope.py tests/unit/search/test_retriever.py tests/unit/search/test_retriever_multispec.py tests/integration/test_salary_april_regression.py
```

Expected: FAIL. In `test_caller_scope.py` the six scoped tests fail on a leaked tenant-B document or a non-empty result (`documents outside the scope were returned` / `assert (...) == ()`); `test_scoped_keyword_search_returns_only_the_scope` (L8 — already clean), `test_unscoped_search_still_reaches_both_tenants` and `test_unscoped_deep_search_still_reaches_both_tenants` (R6, on `retrieve()` and `answer()`) pass. Every `retrieve(..., scope=…)` call fails with `TypeError: ... unexpected keyword argument 'scope'`. `test_intersect_is_idempotent_for_dates_ids_and_duplicate_tags` passes — it pins an existing property of `_intersect()`.

- [ ] **Step 3: Implement the choke point**

In `src/search/retriever.py`, replace:

```python
    def retrieve(
        self,
        specs: tuple[RetrievalSpec, ...],
    ) -> tuple[list[RetrievedChunk], RetrievalSignal]:
```

with:

```python
    def retrieve(
        self,
        specs: tuple[RetrievalSpec, ...],
        *,
        scope: SearchFilters | None,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal]:
```

In `src/search/retriever.py`, replace:

```python
        Args:
            specs: The resolved retrieval specs (from ``resolve_specs``).
```

with:

```python
        *scope* is the caller's hard filter scope, re-applied here to every
        spec with :func:`_intersect` before any store call — the one choke point
        no relaxation path (recall twins, broaden-and-retry, refinement) can
        bypass.  ``_intersect`` is idempotent, so an already-scoped spec is
        unchanged.  Keyword-only, with no default, so no call site can omit it
        by accident.

        Args:
            specs: The resolved retrieval specs (from ``resolve_specs``).
            scope: The caller's filters (``ui_filters``), or ``None`` for an
                unscoped caller.
```

In `src/search/retriever.py`, replace:

```python
        passes = self._run_passes(specs)
```

with:

```python
        passes = self._run_passes(specs, scope)
```

In `src/search/retriever.py`, replace:

```python
    def _run_passes(self, specs: tuple[RetrievalSpec, ...]) -> _RetrievalPasses:
        """Run each spec's store search and collect the ranked lists and signals.

        Semantic specs are embedded together in one batch and each embedding is
        searched with its own spec's filters; keyword specs are searched
        directly.  Returns the accumulated ranked lists plus the absolute
        vector signals RRF discards.
        """
```

with:

```python
    def _run_passes(
        self, specs: tuple[RetrievalSpec, ...], scope: SearchFilters | None
    ) -> _RetrievalPasses:
        """Run each spec's store search and collect the ranked lists and signals.

        Semantic specs are embedded together in one batch and each embedding is
        searched with its own spec's filters intersected with *scope*; keyword
        specs are searched likewise.  Returns the accumulated ranked lists plus
        the absolute vector signals RRF discards.
        """
```

In `src/search/retriever.py`, replace:

```python
            hits = self._store_reader.vector_search(embedding, per_spec_k, spec.filters)
```

with:

```python
            hits = self._store_reader.vector_search(
                embedding, per_spec_k, _intersect(spec.filters, scope)
            )
```

In `src/search/retriever.py`, replace:

```python
            hits = self._store_reader.keyword_search(
                list(spec.keywords), per_spec_k, spec.filters
            )
```

with:

```python
            hits = self._store_reader.keyword_search(
                list(spec.keywords), per_spec_k, _intersect(spec.filters, scope)
            )
```

In `src/search/core.py`, replace:

```python
        chunks, signal, broadened = self._retrieve_with_broaden(
            plan, specs, facets, today
        )
```

with:

```python
        chunks, signal, broadened = self._retrieve_with_broaden(
            plan, specs, facets, today, ui_filters
        )
```

In `src/search/core.py`, replace:

```python
        facets: FacetSet,
        today: date,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal, bool]:
```

with:

```python
        facets: FacetSet,
        today: date,
        ui_filters: SearchFilters | None,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal, bool]:
```

In `src/search/core.py`, replace:

```python
        chunks, signal = self._retriever.retrieve(specs)
        if chunks:
```

with:

```python
        chunks, signal = self._retriever.retrieve(specs, scope=ui_filters)
        if chunks:
```

In `src/search/core.py`, replace:

```python
        chunks, signal = self._retriever.retrieve(broadened_specs)
```

with:

```python
        chunks, signal = self._retriever.retrieve(broadened_specs, scope=ui_filters)
```

In `src/search/core.py`, replace:

```python
        new_chunks, _signal = self._retriever.retrieve(new_specs)
```

with:

```python
        new_chunks, _signal = self._retriever.retrieve(new_specs, scope=ui_filters)
```

`_refine()` is over the §3.1 60-line ceiling and this task edits it, so it gets the function-level carve-out (spec Risks: "touched functions stay within §3.1"; no split in this change). In `src/search/core.py`, replace:

```python
    def _refine(
        self,
```

with:

```python
    # rationale: over the §3.1 60-line ceiling. One refinement pass is one
    # ordered sequence — re-plan, the clarify and no-op exits, retrieve, merge,
    # re-judge, re-synthesise — sharing the LLM budget, the telemetry and one
    # returned triple. This change only passes the caller scope to its
    # retrieve; a split would widen a leak-fix diff (spec
    # 20261002-caller-scope-hard, Risks).
    def _refine(
        self,
```

The file header already carries the length carve-out; it does not cover the 30-name import cap (66 names; this change adds none). In `src/search/core.py`, replace:

```python
# Splitting _LlmBudget into its own module would add an import edge with no
# cohesion benefit. The Wave 4 simplification audit accepted this length.
"""
```

with:

```python
# Splitting _LlmBudget into its own module would add an import edge with no
# cohesion benefit. The Wave 4 simplification audit accepted this length.
# The imported names exceed the §3.1 30-name cap for the same reason: the one
# orchestrator drives every pipeline stage and names each stage's I/O shapes,
# so only a split would lower the count, and the caller-scope change adds no
# import (spec 20261002-caller-scope-hard, Risks).
"""
```


- [ ] **Step 4: Run the tests and the core suites that call `_retrieve_with_broaden`**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/integration/test_caller_scope.py tests/unit/search/test_retriever_scope.py tests/unit/search/test_retriever.py tests/unit/search/test_retriever_multispec.py tests/integration/test_salary_april_regression.py tests/unit/search/test_core.py tests/unit/search/test_core_trace.py tests/unit/search/test_core_sources.py
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS — the choke point alone turns the whole end-to-end table green. That is D2's point, and why A2/A3 add per-site pins: from here on, reverting one site fix leaves these tests green.

- [ ] **Step 5: Commit**

```bash
git add src/search/retriever.py src/search/core.py tests/integration/conftest.py tests/integration/test_caller_scope.py tests/integration/test_salary_april_regression.py tests/unit/search/test_retriever_scope.py tests/unit/search/test_retriever.py tests/unit/search/test_retriever_multispec.py
git commit -m "fix(search): re-apply the caller scope to every retriever store call"
```

### Task A2: Recall twins keep the caller scope — leak sites L1 and L3 (Sonnet)

**Files:**
- Create: `tests/unit/search/test_resolve_specs_scope.py`
- Create: `tests/unit/search/test_core_scope.py` (module, helpers and the L3 test; A3 appends two more)
- Modify: `tests/unit/search/test_core_sources.py` (`TestUiFilters.test_ui_filters_are_passed_to_vector_search`)
- Modify: `src/search/retriever.py` (`resolve_specs()`, `_append_unfiltered_twins()`)
- Modify: `src/search/core.py` (docstrings of `_retrieve_phase()` and `_refine()`)

**Interfaces:**
- Produces: `_append_unfiltered_twins(resolved: list[RetrievalSpec], max_specs: int, ui_filters: SearchFilters | None) -> list[RetrievalSpec]` — a twin's filters are `_intersect(_EMPTY_FILTERS, ui_filters)`.
- Consumes: `Retriever.retrieve(..., scope=...)` from A1.

`TestUiFilters` passes today **for the wrong reason**: its embedding stub returns one vector for two semantic specs (original + twin), `zip()` in `_run_passes()` drops the twin, and the test reads only `call_args`. The fix sizes the stub per text and asserts over every call; it was run red on `ecaeb28`'s code (the unfiltered twin's `vector_search` call appears) before it counts.

The L3 pin observes the `refine` phase detail (`new_specs[*].filters.tag_ids`, emitted by `_emit_refine_marker()` from `_spec_detail_for_resolved(new_specs)`), not the store call — the A1 choke point re-scopes the store call and would hide a reverted site fix.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/search/test_resolve_specs_scope.py`:

```python
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
```

Save this script as `fix_ui_filters_test.py` in the session scratchpad directory your system prompt names (never the repository, never /tmp root) and run it from the worktree root (`python <scratchpad>/fix_ui_filters_test.py`); it asserts every count before it writes and stops on any drift — it never commits:

```python
"""Make TestUiFilters assert every vector_search call (it passed for the wrong reason)."""

import pathlib

path = pathlib.Path("tests/unit/search/test_core_sources.py")
text = path.read_text()
PAIRS = [
    (
        '''        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        core.answer("a query", ui_filters=ui_filters)

        # The UI filters are the authoritative global constraint: a spec guess
        # that does not resolve (the empty test taxonomy drops "npower") leaves
        # the UI's correspondent_id=55 as the only filter reaching vector_search.
        # resolve_specs intersects per spec, so the object is rebuilt but its
        # values equal the UI filters exactly.
        passed_filters = store_reader.vector_search.call_args[0][2]
        assert passed_filters == ui_filters
''',
        '''        # One vector per text: a single canned vector would let zip() in
        # Retriever._run_passes drop every semantic spec after the first, hiding
        # an unscoped recall twin from the assertion below.
        embedding_client = MagicMock()
        embedding_client.embed.side_effect = lambda texts: [[0.1] for _ in texts]
        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=embedding_client,
        )
        core.answer("a query", ui_filters=ui_filters)

        # The caller's filters are a hard scope: a spec guess that does not
        # resolve (the empty test taxonomy drops "npower") leaves
        # correspondent_id=55 as the only filter, and EVERY vector pass —
        # recall twins included — carries it.
        calls = store_reader.vector_search.call_args_list
        assert calls
        assert all(call.args[2] == ui_filters for call in calls)
''',
    ),
]
for old, new in PAIRS:
    assert text.count(old) == 1, (old[:60], text.count(old))
    text = text.replace(old, new)
path.write_text(text)
print("edited", path)
```

Create `tests/unit/search/test_core_scope.py`:

```python
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
```


- [ ] **Step 2: Run them and watch them fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_resolve_specs_scope.py tests/unit/search/test_core_scope.py tests/unit/search/test_core_sources.py tests/unit/search/test_resolve_specs.py
```

Expected: 5 FAIL — the four `test_resolve_specs_scope.py` tests (twins carry no tag) and `test_refinement_specs_carry_the_caller_scope` (`new_specs` has 2 entries but the twin's `tag_ids` is `[]`). `TestUiFilters` already passes here, because A1's choke point scopes the twin at the store; its red run belongs to the pre-change code (Step 6 below shows how to see it). The existing twin tests in `test_resolve_specs.py` (`ui_filters=None`) pass — R2/R6.

- [ ] **Step 3: Implement the site fix**

In `src/search/retriever.py`, replace:

```python
        resolved = _append_unfiltered_twins(resolved, max_specs)
```

with:

```python
        resolved = _append_unfiltered_twins(resolved, max_specs, ui_filters)
```

In `src/search/retriever.py`, replace:

```python
def _append_unfiltered_twins(
    resolved: list[RetrievalSpec], max_specs: int
) -> list[RetrievalSpec]:
    """Append a filter-stripped twin of each filtered spec (deduped, capped).

    Recall insurance: a wrong filter silently *excludes* the answer, and the
    tightest spec is the most filtered.  Each filtered spec gains a twin with the
    same query but no filters, so whatever a filter excluded is still retrieved;
    if the filter was right, RRF fusion rewards the document found by both the
    filtered spec and its twin.  The twin is the *same query* with filters off,
    so it cannot drift off-topic — it only re-admits what a filter removed.
```

with:

```python
def _append_unfiltered_twins(
    resolved: list[RetrievalSpec],
    max_specs: int,
    ui_filters: SearchFilters | None,
) -> list[RetrievalSpec]:
    """Append a planner-filter-stripped twin of each filtered spec (deduped, capped).

    Recall insurance against the *planner*: a wrong planner guess silently
    *excludes* the answer, and the tightest spec is the most filtered.  Each
    filtered spec gains a twin with the same query and the planner's guesses
    stripped, so whatever a guess excluded is still retrieved; if the guess was
    right, RRF fusion rewards the document found by both.  The caller's
    *ui_filters* are a hard scope, not a guess, so the twin keeps them: its
    filters are ``_intersect(_EMPTY_FILTERS, ui_filters)``.  A spec whose only
    filters are the caller scope therefore yields a twin equal to itself, which
    the dedup below drops.
```

In `src/search/retriever.py`, replace:

```python
        twin = replace(spec, filters=_EMPTY_FILTERS)
```

with:

```python
        twin = replace(spec, filters=_intersect(_EMPTY_FILTERS, ui_filters))
```

In `src/search/retriever.py`, replace:

```python
            which deliberately drops all date filters — can omit it.
        max_specs: When set, enables the unfiltered recall-twin pass after the
            safety net: every resolved spec that carries a filter gains a
            filter-stripped twin (deduped on retrieval identity). Only twins are
            bounded by ``max_specs`` — originals (including a safety-net spec)
            always survive, so the total can be ``max_specs + 1`` when the
            safety net also fired. ``None`` (the default) disables twinning, so
            the broadened pass — which already drops all filters — is unaffected.
```

with:

```python
            which deliberately drops the planner's date guesses — can omit it.
        max_specs: When set, enables the recall-twin pass after the safety net:
            every resolved spec that carries a filter gains a twin with the
            planner's guesses stripped and *ui_filters* kept (deduped on
            retrieval identity). Only twins are bounded by ``max_specs`` —
            originals (including a safety-net spec) always survive, so the total
            can be ``max_specs + 1`` when the safety net also fired. ``None``
            (the default) disables twinning, so the broadened pass — which
            already strips every planner guess — is unaffected.
```

In `src/search/retriever.py`, replace:

```python
        deduped unfiltered twins.
```

with:

```python
        deduped recall twins.
```

In `src/search/core.py`, replace:

```python
        date-scoped spec is appended automatically.  ``max_specs`` enables the
        unfiltered recall-twin pass — a bad filter can never silently exclude the
        answer because its filter-stripped twin still retrieves it.
```

with:

```python
        date-scoped spec is appended automatically.  ``max_specs`` enables the
        recall-twin pass — a bad *planner* guess can never silently exclude the
        answer because its guess-stripped twin still retrieves it; the twin
        keeps *ui_filters*, which are a hard scope, not a guess.
```

In `src/search/core.py`, replace:

```python
            ui_filters: The authoritative UI filters, if any.
```

with:

```python
            ui_filters: The caller's filters (a hard scope), if any.
```


- [ ] **Step 4: Run the tests**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_resolve_specs_scope.py tests/unit/search/test_core_scope.py tests/unit/search/test_core_sources.py tests/unit/search/test_resolve_specs.py
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/search/retriever.py src/search/core.py tests/unit/search/test_resolve_specs_scope.py tests/unit/search/test_core_scope.py tests/unit/search/test_core_sources.py
git commit -m "fix(search): keep the caller scope on recall twins"
```

- [ ] **Step 6: Prove the repaired `TestUiFilters` bites** (on the clean, committed tree)

In `src/search/retriever.py` change `twin = replace(spec, filters=_intersect(_EMPTY_FILTERS, ui_filters))` to `twin = replace(spec, filters=_EMPTY_FILTERS)` **and** both `_intersect(spec.filters, scope)` in `_run_passes()` to `spec.filters`, then:

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_core_sources.py -k UiFilters   # expect FAIL: a vector_search call without correspondent_id=55
git checkout -- src/search/retriever.py && git status --short          # expect clean
python -m pytest tests/unit/search/test_core_sources.py -k UiFilters   # expect PASS
```

Record the FAILED line in the task report. (With either fix alone in place it passes — the choke point and the site fix each scope the twin — which is why M1 also pins the two layers separately.)

### Task A3: Broaden keeps the scope, skips a repeat of pass 1, returns a dataclass (Opus)

**Files:**
- Modify: `tests/unit/search/test_core.py` (`TestEmptyRetrieval.test_broaden_retry_runs_before_giving_up` — re-targeted; `# rationale:` header — §3.1)
- Modify: `tests/unit/search/test_core_trace.py` (`TestRetrieveDetail.test_retrieve_detail_marks_broadened_on_second_pass` — re-targeted; `# rationale:` header — §3.1)
- Modify: `tests/unit/search/test_core_scope.py` (append the L2 and D9 tests)
- Modify: `src/search/core.py` (`_BroadenOutcome`, `_retrieve_phase()`, `_retrieve_with_broaden()`, docstrings of `answer()` and `retrieve()`)

**Interfaces:**
- Produces: `@dataclass(frozen=True, slots=True) class _BroadenOutcome: chunks: list[RetrievedChunk]; signal: RetrievalSignal; broadened: bool` (module-private, declared beside `_RetrievalPhaseResult`); `SearchCore._retrieve_with_broaden(plan, specs, facets, today, ui_filters) -> _BroadenOutcome`.
- Consumes: `_spec_search_key()` (`src/search/core.py`, unchanged); `resolve_specs()`, `broaden_plan()`.

**Skip branch (review-lessons: a new early return states its return value):** `_BroadenOutcome(chunks=[], signal=<pass-1 signal>, broadened=False)`. Consumers: `_retrieve_phase()` writes `outcome.broadened` into the `retrieve` trace detail and `outcome.signal` into `_RetrievalPhaseResult`; the empty chunks reach the existing `reason="empty_retrieval"` no-match in `_answer_uncached()` through the same path an empty broaden takes today — it reuses that path, it adds no new one. The comparison is the **set** of `_spec_search_key()` over each pass: `_specs_equal()` is positional and length-sensitive, and pass 1 carries twins and the date safety net that the broaden resolve (no `query`, no `max_specs`) does not.

**Why the two existing tests need re-targeting:** both use `make_facet_set()`, whose empty taxonomy drops their `correspondent="npower"` guess, so their only spec resolves to no filter, the broaden resolves to the same search, and D9 now (correctly) skips it. The re-target gives the facet set a real `npower` correspondent and sets `SEARCH_PLANNER_MAX_SPECS=1`, so the spec resolves to a real filter whose twin is cut by the cap — the only case in which broaden still differs from pass 1. They are re-targeted, not deleted. `test_retrieve_detail_reports_counts_and_not_broadened` needs no change (checked: it passes before and after).

- [ ] **Step 1: Re-target the two tests (green before and after) and write the failing tests**

Save this script as `retarget_broaden.py` in the session scratchpad directory your system prompt names (never the repository, never /tmp root) and run it from the worktree root (`python <scratchpad>/retarget_broaden.py`); it asserts every count before it writes and stops on any drift — it never commits:

```python
"""Re-target the two broaden tests to a twin-capped plan (spec D9)."""

import pathlib

IMPORT_OLD = "    make_search_settings,\n)\n"
IMPORT_NEW = "    make_search_settings,\n    make_taxonomy_entry,\n)\n"

EDITS = {
    "tests/unit/search/test_core.py": [
        (IMPORT_OLD, IMPORT_NEW),
        (
            '''    def test_broaden_retry_runs_before_giving_up(self) -> None:
        """A filtered retrieval that finds nothing is retried broadened; if
        the broadened retrieval finds chunks, synthesis proceeds normally."""
''',
            '''    def test_broaden_retry_runs_before_giving_up(self) -> None:
        """A filtered retrieval that finds nothing is retried broadened; if
        the broadened retrieval finds chunks, synthesis proceeds normally.

        Twin-capped setup (spec D9): the planner guess resolves to a real
        correspondent and ``SEARCH_PLANNER_MAX_SPECS=1`` leaves no room for its
        recall twin, so the broadened search is not among pass 1's searches —
        the only case in which broaden still runs.
        """
''',
        ),
        (
            '''        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        # First call (filtered) → nothing; second call (broadened) → a hit.
''',
            '''        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set(
            correspondents=(
                make_taxonomy_entry(kind="correspondent", entry_id=10, name="npower"),
            )
        )
        # First call (filtered) → nothing; second call (broadened) → a hit.
''',
        ),
        (
            '''        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        result = core.answer("npower bill query")
''',
            '''        core = build_search_core(
            settings=make_search_settings(SEARCH_PLANNER_MAX_SPECS=1),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        result = core.answer("npower bill query")
''',
        ),
    ],
    "tests/unit/search/test_core_trace.py": [
        (IMPORT_OLD, IMPORT_NEW),
        (
            '''        store_reader = MagicMock()
        store_reader.list_facets.return_value = make_facet_set()
        store_reader.vector_search.side_effect = [
            [],
            [make_chunk_hit(chunk_id=1, document_id=1)],
        ]
''',
            '''        store_reader = MagicMock()
        # Twin-capped (spec D9): "npower" resolves and SEARCH_PLANNER_MAX_SPECS=1
        # leaves no room for its recall twin, so broaden still differs from pass 1.
        store_reader.list_facets.return_value = make_facet_set(
            correspondents=(
                make_taxonomy_entry(kind="correspondent", entry_id=10, name="npower"),
            )
        )
        store_reader.vector_search.side_effect = [
            [],
            [make_chunk_hit(chunk_id=1, document_id=1)],
        ]
''',
        ),
        (
            '''        core = build_search_core(
            settings=make_search_settings(),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("npower bill", on_event=events.append)
''',
            '''        core = build_search_core(
            settings=make_search_settings(SEARCH_PLANNER_MAX_SPECS=1),
            llm_client=llm_client,
            store_reader=store_reader,
            embedding_client=_embedding_client(),
        )
        events: list = []
        core.answer("npower bill", on_event=events.append)
''',
        ),
    ],
}

for name, pairs in EDITS.items():
    path = pathlib.Path(name)
    text = path.read_text()
    for old, new in pairs:
        assert text.count(old) == 1, (name, old[:60], text.count(old))
        text = text.replace(old, new)
    path.write_text(text)
    print(name, "edited", len(pairs))
```

Append to the end of `tests/unit/search/test_core_scope.py`:

```python


def test_broaden_resolves_the_broadened_plan_with_the_caller_scope() -> None:
    """Leak site L2: the second retrieve's specs carry the scope.

    Twin-capped plan (SEARCH_PLANNER_MAX_SPECS=1, a real correspondent guess):
    the only setup in which broaden still runs under D9.
    """
    reset_search_result_cache()
    scope = make_search_filters(tag_ids=(_TAG_A,))
    store_reader = MagicMock()
    store_reader.list_facets.return_value = _npower_facets()
    store_reader.vector_search.side_effect = [
        [],
        [make_chunk_hit(chunk_id=1, document_id=1)],
    ]
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = [make_indexed_document(document_id=1)]
    core = build_search_core(
        settings=make_search_settings(SEARCH_PLANNER_MAX_SPECS=1),
        llm_client=ScriptedLLMClient(
            planner_response=planner_response_json(
                specs=[_make_spec(correspondent="npower")]
            ),
            synthesiser_responses=[
                answered_response_json("Answer [1].", citations=[1])
            ],
        ),
        store_reader=store_reader,
        embedding_client=_per_text_embedding_client(),
    )
    spy = MagicMock(wraps=core._retriever.retrieve)
    core._retriever.retrieve = spy  # type: ignore[method-assign]

    core.answer("npower bill", ui_filters=scope)

    assert spy.call_count == 2
    broadened_specs = spy.call_args_list[1].args[0]
    assert broadened_specs
    assert all(spec.filters.tag_ids == (_TAG_A,) for spec in broadened_specs)
    assert all(spec.filters.correspondent_id is None for spec in broadened_specs)


def test_scoped_search_with_an_empty_first_pass_does_not_repeat_it() -> None:
    """D9: a broaden that would repeat pass 1 is skipped — one embedding call,
    one retrieve, and the trace reports ``broadened: false``."""
    reset_search_result_cache()
    store_reader = MagicMock()
    store_reader.list_facets.return_value = make_facet_set()
    store_reader.vector_search.return_value = []
    store_reader.keyword_search.return_value = []
    store_reader.get_documents.return_value = []
    embedding_client = _per_text_embedding_client()
    core = build_search_core(
        settings=make_search_settings(),
        llm_client=ScriptedLLMClient(
            planner_response=planner_response_json(), synthesiser_responses=[]
        ),
        store_reader=store_reader,
        embedding_client=embedding_client,
    )
    spy = MagicMock(wraps=core._retriever.retrieve)
    core._retriever.retrieve = spy  # type: ignore[method-assign]
    events: list = []

    result = core.retrieve(
        "boiler warranty",
        ui_filters=make_search_filters(tag_ids=(_TAG_A,)),
        on_event=events.append,
    )

    assert result.sources == ()
    assert embedding_client.embed.call_count == 1
    assert spy.call_count == 1
    retrieve = next(r for r in _records(events) if r.phase == "retrieve")
    assert retrieve.detail["broadened"] is False
```


Both re-targeted test files are already over the §3.1 500-line ceiling and this task grows them, so each gets the header carve-out (Global Constraints §3.1). In `tests/unit/search/test_core.py`, replace:

```python
retriever, and synthesiser stages over mock store / embedding clients.
"""
```

with:

```python
retriever, and synthesiser stages over mock store / embedding clients.

# rationale: this file exceeds the §3.1 500-line guideline. It is the one
# suite for the answer() call-count contract, sharing its scripted-driver
# fixtures; source assembly already moved to test_core_sources. The
# caller-scope change only re-targets one broaden test, and a further split
# there would move unrelated tests and widen a leak-fix diff (spec
# 20261002-caller-scope-hard, Risks).
"""
```

In `tests/unit/search/test_core_trace.py`, replace:

```python
from ``result.stats.trace`` so the two are pinned to agree.
"""
```

with:

```python
from ``result.stats.trace`` so the two are pinned to agree.

# rationale: this file exceeds the §3.1 500-line guideline. Every test drives
# one pipeline and asserts the per-phase events and the assembled trace
# against each other, through one set of builders. The caller-scope change
# only re-targets one broaden test, and a split there would move unrelated
# tests and widen a leak-fix diff (spec 20261002-caller-scope-hard, Risks).
"""
```

- [ ] **Step 2: Run them and watch the new ones fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_core_scope.py tests/unit/search/test_core.py tests/unit/search/test_core_trace.py
```

Expected: 2 FAIL — `test_broaden_resolves_the_broadened_plan_with_the_caller_scope` (the broadened specs carry no tag: `ui_filters=None` today) and `test_scoped_search_with_an_empty_first_pass_does_not_repeat_it` (`embed.call_count == 2`, two retrieves, `broadened: True`). The two re-targeted tests PASS.

- [ ] **Step 3: Implement**

In `src/search/core.py`, replace:

```python
    documents_by_id: dict[int, IndexedDocument]


class SearchCore:
```

with:

```python
    documents_by_id: dict[int, IndexedDocument]


@dataclass(frozen=True, slots=True)
class _BroadenOutcome:
    """The output of :meth:`SearchCore._retrieve_with_broaden`.

    *signal* is from whichever pass produced *chunks* (pass 1 when the broaden
    was skipped); *broadened* is True iff a second, different retrieval ran.
    A frozen carrier instead of a positional 3-tuple (CODE_GUIDELINES §5.8).
    """

    chunks: list[RetrievedChunk]
    signal: RetrievalSignal
    broadened: bool


class SearchCore:
```

In `src/search/core.py`, replace:

```python
        chunks, signal, broadened = self._retrieve_with_broaden(
            plan, specs, facets, today, ui_filters
        )
        doc_ids = {c.document_id for c in chunks}
```

with:

```python
        outcome = self._retrieve_with_broaden(plan, specs, facets, today, ui_filters)
        chunks = outcome.chunks
        doc_ids = {c.document_id for c in chunks}
```

In `src/search/core.py`, replace:

```python
                "broadened": broadened,
```

with:

```python
                "broadened": outcome.broadened,
```

In `src/search/core.py`, replace:

```python
        return _RetrievalPhaseResult(
            chunks=chunks,
            signal=signal,
            specs=specs,
```

with:

```python
        return _RetrievalPhaseResult(
            chunks=chunks,
            signal=outcome.signal,
            specs=specs,
```

In `src/search/core.py`, replace:

```python
        broadened (filter-dropped) second pass ran.
```

with:

```python
        broadened (planner-guess-dropped) second pass ran.
```

In `src/search/core.py`, replace:

```python
        ui_filters: SearchFilters | None,
    ) -> tuple[list[RetrievedChunk], RetrievalSignal, bool]:
        """Retrieve for the resolved *specs*; broaden and retry once if empty.

        Runs hybrid retrieval over the already-resolved *specs* (the caller
        resolved them with any UI filters already applied).  An empty result is
        retried once with every spec's filters dropped (spec §6.3) — a
        mis-resolved or hallucinated filter is the most common cause of an
        otherwise-answerable query returning nothing.  The broadened pass
        re-resolves :func:`~search.refinement.broaden_plan`'s output against the
        same *facets* (no second ``list_facets`` round-trip) with no UI filters,
        so a UI-set filter the user explicitly chose does not survive the
        broaden.  Neither call is an LLM call.

        Returns:
            A 3-tuple ``(chunks, signal, broadened)`` where *signal* is from
            whichever retrieval pass found chunks (or the broadened pass when
            the first was empty) and *broadened* is True iff the second
            (filter-dropped) pass ran. The signal is forwarded to Layer 2 and
            *broadened* feeds the retrieve-phase detail.
        """
        chunks, signal = self._retriever.retrieve(specs, scope=ui_filters)
        if chunks:
            return chunks, signal, False

        # Empty retrieval — drop every spec's filters and try once more.
        broadened_specs = resolve_specs(
            broaden_plan(plan), facets, ui_filters=None, today=today
        )
        log.info("search.retrieval_broadened")
        chunks, signal = self._retriever.retrieve(broadened_specs, scope=ui_filters)
        return chunks, signal, True
```

with:

```python
        ui_filters: SearchFilters | None,
    ) -> _BroadenOutcome:
        """Retrieve for the resolved *specs*; broaden and retry once if empty.

        Runs hybrid retrieval over the already-resolved *specs* (the caller
        resolved them with *ui_filters* already applied).  An empty result is
        retried once with every *planner* guess dropped (spec §6.3) — a
        mis-resolved or hallucinated planner filter is the most common cause of
        an otherwise-answerable query returning nothing.  The broadened pass
        re-resolves :func:`~search.refinement.broaden_plan`'s output against the
        same *facets* (no second ``list_facets`` round-trip) and the same
        *ui_filters*: the caller's filters are a hard scope and survive the
        broaden.  Both passes hand *ui_filters* to the retriever as ``scope``.

        When every broadened search is already among pass 1's searches (always
        the case for an unplanned, scoped search, whose recall twins already ran
        the scope-only searches) the retry would repeat pass 1, so it is
        skipped: no second retrieve, no second embedding call, and
        ``broadened=False`` with pass 1's empty chunks and signal.  Neither call
        is an LLM call.

        Returns:
            A :class:`_BroadenOutcome`; *broadened* feeds the retrieve-phase
            detail and *signal* is forwarded to Layer 2.
        """
        chunks, signal = self._retriever.retrieve(specs, scope=ui_filters)
        if chunks:
            return _BroadenOutcome(chunks=chunks, signal=signal, broadened=False)

        broadened_specs = resolve_specs(
            broaden_plan(plan), facets, ui_filters=ui_filters, today=today
        )
        pass_one_keys = {_spec_search_key(spec) for spec in specs}
        if all(_spec_search_key(spec) in pass_one_keys for spec in broadened_specs):
            return _BroadenOutcome(chunks=[], signal=signal, broadened=False)

        log.info("search.retrieval_broadened")
        chunks, signal = self._retriever.retrieve(broadened_specs, scope=ui_filters)
        return _BroadenOutcome(chunks=chunks, signal=signal, broadened=True)
```

In `src/search/core.py`, replace:

```python
            ui_filters: Explicit user-set filters; when provided they are
                authoritative and bypass free-text filter resolution.
```

with:

```python
            ui_filters: The caller's filters — a hard scope: every returned
                document satisfies every one of them, on every pass (planner
                guesses are intersected with them, never replace them).
```

In `src/search/core.py`, replace:

```python
            ui_filters: Explicit user-set filters; authoritative when set.
```

with:

```python
            ui_filters: The caller's filters — a hard scope every returned
                document satisfies; never relaxed.
```


- [ ] **Step 4: Run the track's whole surface**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search tests/integration
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/search/core.py tests/unit/search/test_core_scope.py tests/unit/search/test_core.py tests/unit/search/test_core_trace.py
git commit -m "fix(search): keep the caller scope through broaden and skip a repeat of pass 1"
```

---

## Track B — wire / MCP boundary

### Task B1: `FilterRequest` and `SearchRequest` fail closed (Sonnet)

**Files:**
- Modify: `tests/unit/search/wire/test_search.py` (append)
- Create: `tests/unit/search/test_api_filters.py`
- Modify: `src/search/wire/search.py` (`FilterRequest`, new `_caller_iso_date()`, `SearchRequest`, module header)

**Interfaces:**
- Produces: `FilterRequest` with `model_config = ConfigDict(extra="forbid")`, `_require_iso_date` (field validator on `date_from`/`date_to`), `_reject_empty_tag_ids` (`model_validator(mode="after")`); `SearchRequest` with `extra="forbid"`. Error texts: `"Extra inputs are not permitted"` (Pydantic's), `"must be an ISO date (YYYY-MM-DD) or ISO timestamp"`, `"tag_ids must not be empty; omit it for no tag constraint"` — B2's tests match on the key names these errors carry.
- Consumes: `normalise_iso_date()` (`src/search/dates.py`). New import edge `search.wire.search → search.dates` (stdlib-only module; header updated).

The explicit-empty check reads `model_fields_set` inside the validator — the same test `_update_api_key` in `src/search/api_key_routes.py` uses (`sent = body.model_fields_set`) to tell an explicit value from an absent key.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/unit/search/wire/test_search.py`:

```python


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
```

Create `tests/unit/search/test_api_filters.py`:

```python
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
```


- [ ] **Step 2: Run them and watch them fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/wire/test_search.py tests/unit/search/test_api_filters.py
```

Expected: 28 FAIL — every rejection test (no error raised / HTTP 200 instead of 422) and the two timestamp-normalisation cases (`'2025-04-25T00:00:00+00:00'` stored verbatim). The "accepted" cases, the inverted-range test and the existing query-length tests pass.

- [ ] **Step 3: Implement**

In `src/search/wire/search.py`, replace:

```python
Allowed deps: pydantic, search.models, store (SearchFilters).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator

from search.models import NoMatchReason
from store import SearchFilters
```

with:

```python
Allowed deps: pydantic, search.models, search.dates (normalise_iso_date),
    store (SearchFilters).
Forbidden: FastAPI, sqlite3, any I/O.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from search.dates import normalise_iso_date
from search.models import NoMatchReason
from store import SearchFilters
```

In `src/search/wire/search.py`, replace:

```python
    """Optional filters supplied in a search request (spec §7.1).

    Every field defaults to absent; only the fields present in the request body
    are forwarded to the pipeline.  Extra keys are ignored — both the HTTP and
    the MCP boundary are lenient on unrecognised fields.
    """

    date_from: str | None = None
```

with:

```python
    """Optional filters supplied in a search request (spec §7.1).

    The caller's filters are a hard search scope, so a malformed one fails
    closed (CODE_GUIDELINES §1.11) instead of silently widening the search:
    an unknown key (``tag_id`` for ``tag_ids``), a ``date_from`` / ``date_to``
    that is not an ISO date, and an explicitly empty ``tag_ids`` are all
    rejected.  This one model is the parse for both the HTTP and the MCP
    boundary, so the rules hold identically on both.  An omitted field means
    "no constraint"; multiple ``tag_ids`` are ANDed (every id required).
    """

    model_config = ConfigDict(extra="forbid")

    date_from: str | None = None
```

In `src/search/wire/search.py`, replace:

```python
    tag_ids: list[int] = Field(default_factory=list, max_length=64)


def normalise_query
```

with:

```python
    tag_ids: list[int] = Field(default_factory=list, max_length=64)

    @field_validator("date_from", "date_to")
    @classmethod
    def _require_iso_date(cls, value: str | None) -> str | None:
        """Accept an ISO date or timestamp; store its ``YYYY-MM-DD`` date."""
        return None if value is None else _caller_iso_date(value)

    @model_validator(mode="after")
    def _reject_empty_tag_ids(self) -> FilterRequest:
        """Reject an explicit ``tag_ids: []`` — it names no scope at all.

        ``model_fields_set`` tells an explicit empty list from an omitted key,
        which keeps its ``[]`` default and means "no tag constraint".
        """
        if "tag_ids" in self.model_fields_set and not self.tag_ids:
            raise ValueError("tag_ids must not be empty; omit it for no tag constraint")
        return self


def _caller_iso_date(value: str) -> str:
    """Return the ``YYYY-MM-DD`` date of an ISO date or timestamp, or raise.

    Three checks, each closing a gap the others leave: :func:`normalise_iso_date`
    validates only the first ten characters (``"2025-04-25junk"`` passes it);
    ``datetime.fromisoformat`` accepts compact and week forms (``"20250425"``,
    ``"2025-W17-5"``) the store's lexical date comparison cannot use; requiring
    the parsed date to equal the ten-character prefix rejects the week form,
    which passes the first two.
    """
    date_part = normalise_iso_date(value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    if date_part is None or parsed is None or parsed.date().isoformat() != date_part:
        raise ValueError("must be an ISO date (YYYY-MM-DD) or ISO timestamp")
    return date_part


def normalise_query
```

In `src/search/wire/search.py`, replace:

```python
class SearchRequest(BaseModel):
    """Body for POST /api/search."""
```

with:

```python
class SearchRequest(BaseModel):
    """Body for POST /api/search and /api/search/stream.

    ``extra="forbid"``: a mis-keyed container (``filter`` for ``filters``)
    would otherwise read as "no filters" and run an unscoped search.
    """

    model_config = ConfigDict(extra="forbid")
```


- [ ] **Step 4: Run**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/wire tests/unit/search/test_api_filters.py tests/unit/search/test_api.py tests/unit/search/test_routes_stream.py tests/integration/test_search_api.py
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/search/wire/search.py tests/unit/search/wire/test_search.py tests/unit/search/test_api_filters.py
git commit -m "fix(search): reject malformed caller filters at the HTTP boundary"
```

### Task B2: MCP — strict arguments, clear filter errors, the stated contract (Opus)

**Files:**
- Create: `tests/unit/search/test_mcp_server_filters.py`
- Modify: `src/search/mcp_server.py` (module header + `# rationale:` covering length and the import cap, imports, `_to_search_filters()`, `_run_search_tool()`, new `_StrictFastMCP`, three tool-description constants, `_dispatch()`, the three tools' `description=` arguments, server `instructions`, `build_mcp_app()`)

**Interfaces:**
- Consumes: B1's `FilterRequest` validators.
- Produces: `_StrictFastMCP(FastMCP)` overriding the public `list_tools()` and `call_tool(name, arguments)`; `_to_search_filters(raw) -> SearchFilters | None` raising `ValueError("invalid filters — <key>: <reason>; …") from exc`; `_run_search_tool(*, query, filters: SearchFilters | None, core_call, error_event, asker=None)` — the parameter keeps its name, so `tests/unit/search/test_mcp_server_asker.py` (which passes `filters=None`) needs no change.

**Why the conversion moves:** today `_run_search_tool()` converts filters *inside* its outer-boundary `try`, whose `except Exception` replaces every message with `"search failed — see server logs"`. Converting in `_dispatch()` **before** `_run_tool()` — as `keyword_search` already does, and as `fetch_documents` validates "BEFORE dispatch" — means a rejected filter never resolves the core, checks the spend quota or takes the semaphore, and its message reaches the client. `_run_tool()` has no catch-all of its own; FastMCP turns the `ValueError` into `isError: true` with text `Error executing tool <name>: invalid filters — …` (probed).

**Why a subclass:** FastMCP drops an undeclared argument name in its generated argument model before the tool body runs, and registers its handler with `call_tool(validate_input=False)` (`FastMCP._setup_handlers()`), so neither the tool body nor a published schema can catch `filter` for `filters`. `_StrictFastMCP` uses only public methods; the low-level handler calls the bound `self.call_tool` / `self.list_tools`, so the overrides are what `tools/call` and `tools/list` run (probed on `mcp` 1.29.1). `inputSchema.get("properties", {})` covers a tool with no parameters (`list_filters`). An unknown tool name falls through to FastMCP's own error. Rejected alternative (spec): forcing `extra="forbid"` onto each generated argument model reaches through the private `FastMCP._tool_manager`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/search/test_mcp_server_filters.py`:

```python
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

from search.mcp_server import _McpApp, build_mcp_app
from search.offload import LazySemaphore
from store.models import KeywordPage, SearchFilters
from tests.helpers.factories import make_search_result, make_search_settings

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
]


def _core() -> MagicMock:
    core = MagicMock()
    core.retrieve.return_value = make_search_result(answer="", sources=())
    core.answer.return_value = make_search_result(sources=())
    core.keyword_search.return_value = KeywordPage(hits=(), total=0, offset=0, limit=20)
    core.settings = make_search_settings()
    return core


def _app(core: MagicMock) -> _McpApp:
    return build_mcp_app(
        lambda _app_db_path: core,
        "unused-app-db-path",
        search_semaphore=LazySemaphore(0),
    )


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

    assert scoped.isError is False
    ui_filters = _ui_filters(core, "retrieve")
    assert ui_filters is not None
    assert ui_filters.tag_ids == (7,)
    assert typo.isError is True
    assert "tag_id" in _text(typo)
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
```


- [ ] **Step 2: Run them and watch them fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_mcp_server_filters.py
```

Expected: 24 FAIL — the 14 `semantic_search` / `deep_search` rows of `test_malformed_filters_are_rejected_naming_the_key` (the client gets the sanitised `search failed — see server logs`, because the conversion still runs inside `_run_search_tool()`'s outer `try`); all 6 `test_a_mis_keyed_filters_container_is_rejected` cases (`isError is False` — FastMCP dropped the key and ran an unscoped search); `test_every_tool_schema_forbids_undeclared_arguments`; `test_filters_sent_as_a_json_string_are_parsed_then_validated` (the typo comes back as `search failed`); both `test_the_zero_llm_tools_reject_undeclared_arguments_too` cases. The 7 `keyword_search` malformed rows already PASS after B1 — that tool converts before `_run_tool()` today, so Pydantic's message (which names the key) reaches the client — and stay as pins of the shared message. The timestamp, absent-filters and correctly-keyed cases pass.

- [ ] **Step 3: Implement**

In `src/search/mcp_server.py`, replace:

```python
    ``PaperlessClient`` run off the loop — mirroring ``search.document_routes``.
"""
```

with:

```python
    ``PaperlessClient`` run off the loop — mirroring ``search.document_routes``.

# rationale: this file exceeds the §3.1 500-line guideline. It is the one MCP
# boundary: the auth middleware, the strict FastMCP subclass, and the five tool
# closures share the per-request core resolution, the spend-quota scaffold
# (``_run_tool``) and the filter parse, and the closures must be registered on
# one FastMCP instance. The caller-scope change that last touched it is a leak
# fix; splitting the module there would move unrelated code and widen that
# diff past the fix (spec 20261002-caller-scope-hard, Risks). The imported
# names exceed the §3.1 30-name cap too: the module already imported 40, since
# this one boundary wires session and API-key auth, the spend quota, the core,
# the store's filter shape, the MCP SDK and the ASGI transport; the caller-scope
# change adds five (Sequence, ToolError, ValidationError, ContentBlock, MCPTool)
# for the strict server and the filter error. Only that split would lower it.
"""
```

In `src/search/mcp_server.py`, replace:

```python
    identity, offload, spend_quota), store (SearchFilters), common (paperless,
    config), appdb (connection), mcp SDK, starlette.
```

with:

```python
    identity, offload, spend_quota), store (SearchFilters), common (paperless,
    config), appdb (connection), mcp SDK, pydantic (ValidationError), starlette.
```

In `src/search/mcp_server.py`, replace:

```python
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
```

with:

```python
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
```

In `src/search/mcp_server.py`, replace:

```python
if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
```

with:

```python
if TYPE_CHECKING:
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.types import ContentBlock
    from mcp.types import Tool as MCPTool
```

In `src/search/mcp_server.py`, replace:

```python
    one shared :func:`~search.wire.to_search_filters` converter.  Unknown keys
    are ignored; ``None`` or an empty dict means no filters.

    Args:
        raw: The raw filters dict from the tool call, or ``None``.

    Returns:
        A :class:`SearchFilters` instance, or ``None`` when no filters apply.
    """
    if not raw:
        return None
    return to_search_filters(FilterRequest.model_validate(raw))
```

with:

```python
    one shared :func:`~search.wire.to_search_filters` converter.  The filters
    are a hard scope, so a malformed one (unknown key, non-ISO date, empty
    ``tag_ids``) is rejected, never ignored; ``None`` or an empty dict means
    no filters.  The one converter all three search tools call, so every tool
    raises the same message.

    Args:
        raw: The raw filters dict from the tool call, or ``None``.

    Returns:
        A :class:`SearchFilters` instance, or ``None`` when no filters apply.

    Raises:
        ValueError: Naming each offending key and Pydantic's reason.  The
            message echoes only the caller's own input, so the chain is kept
            (CODE_GUIDELINES §6.3).
    """
    if not raw:
        return None
    try:
        request = FilterRequest.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'filters'}: "
            f"{error['msg']}"
            for error in exc.errors()
        )
        raise ValueError(f"invalid filters — {problems}") from exc
    return to_search_filters(request)
```

In `src/search/mcp_server.py`, replace:

```python
    query: str,
    filters: dict[str, Any] | None,
    core_call: Callable[[str, SearchFilters | None, str | None], SearchResult],
```

with:

```python
    query: str,
    filters: SearchFilters | None,
    core_call: Callable[[str, SearchFilters | None, str | None], SearchResult],
```

In `src/search/mcp_server.py`, replace:

```python
    enforce the maximum length — §10.4/§10.6), converts the optional *filters*,
    invokes *core_call*, and serialises the result.
```

with:

```python
    enforce the maximum length — §10.4/§10.6), invokes *core_call* with the
    already-validated *filters*, and serialises the result.
```

In `src/search/mcp_server.py`, replace:

```python
        filters: The optional raw filters dict from the tool call.
```

with:

```python
        filters: The caller's validated filters (converted by
            :func:`_to_search_filters` in ``_dispatch``, before any core is
            resolved), or ``None``.
```

In `src/search/mcp_server.py`, replace:

```python
    try:
        ui_filters = _to_search_filters(filters)
        result = core_call(query, ui_filters, asker)
```

with:

```python
    try:
        result = core_call(query, filters, asker)
```

In `src/search/mcp_server.py`, replace:

```python
class _McpApp:
    """Thin wrapper
```

with:

```python
class _StrictFastMCP(FastMCP):
    """A FastMCP server that rejects tool arguments the tool does not declare.

    FastMCP drops an undeclared argument name in its generated argument model
    before the tool runs, and registers its handler with
    ``call_tool(validate_input=False)`` — so a caller passing ``filter`` for
    ``filters`` would silently get an unscoped search.  This overrides only the
    public ``call_tool`` / ``list_tools`` methods: ``call_tool`` is the one
    enforcement point; ``list_tools`` publishes ``additionalProperties: false``
    so a schema-driven client learns the rule up front.
    """

    async def list_tools(self) -> list[MCPTool]:
        """Return every tool with ``additionalProperties: false`` on its schema.

        Each tool is a copy; the library's own schema object is not mutated.
        """
        return [
            tool.model_copy(
                update={
                    "inputSchema": {**tool.inputSchema, "additionalProperties": False}
                }
            )
            for tool in await super().list_tools()
        ]

    # rationale: Any mirrors the overridden FastMCP.call_tool signature — tool
    # arguments and structured results are arbitrary JSON, and an override
    # must keep its base method's parameter and return types.
    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        """Reject any argument not in the tool's ``inputSchema`` properties.

        An unknown tool name is left to FastMCP's own error.
        """
        tool = next((t for t in await self.list_tools() if t.name == name), None)
        if tool is not None:
            declared = set(tool.inputSchema.get("properties", {}))
            unknown = sorted(set(arguments) - declared)
            if unknown:
                raise ToolError(f"unknown argument(s) for {name}: {', '.join(unknown)}")
        return await super().call_tool(name, arguments)


class _McpApp:
    """Thin wrapper
```

`_register_search_tools()` is over the §3.1 60-line ceiling and this task edits it (`_dispatch`, the three `description=` arguments), so it gets the function-level carve-out (spec Risks: "touched functions stay within §3.1"; no split in this change). By §3.1's literal count it is 211 executable body lines on `ecaeb28` (nested closures included) and 190 on the merged replay: over before this change, and the three description constants below take it down from what inline text would make it. The `list_filters` and `fetch_documents` descriptions are unchanged and stay inline. Per §3.5 the constants sit after the imports, not above the registrar. In `src/search/mcp_server.py`, replace:

```python
    from search.core import SearchCore


def _default_paperless_factory(settings: Settings) -> PaperlessClient:
```

with:

```python
    from search.core import SearchCore

# The descriptions of the three tools that take caller filters live here, not
# inline in _register_search_tools, to shrink that registrar.
_SEMANTIC_SEARCH_DESCRIPTION = (
    "PREFERRED, no-cost search — use for almost every query. Returns "
    "ranked source documents (snippets + Paperless deep-links) matching "
    "the query; no synthesised answer. Makes zero LLM calls and does "
    "not bill the archive owner. Read the sources and synthesise the "
    "answer yourself. Optional 'filters' narrows by correspondent, "
    "document type, tag, or date. Filters are a hard scope: every "
    "returned document matches every filter, and they are never "
    "relaxed; multiple tag_ids are ANDed (a document must carry every "
    "tag)."
)
_DEEP_SEARCH_DESCRIPTION = (
    "COSTLY, last-resort search. Runs the archive's server-side agentic "
    "pipeline (planner + judge + synthesiser) and returns a written "
    "answer plus sources. Spends the archive owner's paid LLM API "
    "budget on every call. Prefer semantic_search and synthesise "
    "yourself; only call this when you truly cannot. Optional 'filters' "
    "narrows results. Filters are a hard scope: every returned document "
    "matches every filter, and they are never relaxed; multiple tag_ids "
    "are ANDed (a document must carry every tag)."
)
_KEYWORD_SEARCH_DESCRIPTION = (
    "Free. Exact full-text keyword search over document content plus "
    "title/correspondent/type, optionally narrowed by correspondent_id, "
    "document_type_id, tag_ids, date_from/date_to; returns a ranked "
    "DOCUMENT list (not passages). Use for exact terms, names, or "
    "reference numbers, or to enumerate/filter (e.g. every document "
    "tagged X from 2024). Omit 'query' to list documents by filter "
    "alone. Discover valid filter ids with list_filters. Filters are a "
    "hard scope (never relaxed); multiple tag_ids are ANDed (a document "
    "must carry every tag). Makes no LLM call. 'limit' defaults to 20 "
    "(max 50); 'offset' paginates."
)


def _default_paperless_factory(settings: Settings) -> PaperlessClient:
```

In `src/search/mcp_server.py`, replace:

```python
def _register_search_tools(
    mcp: FastMCP,
```

with:

```python
# rationale: over the §3.1 60-line ceiling before this change — the five MCP
# tools are closures that must register on one FastMCP instance and share the
# captured `resolve_core`, `app_db_path`, `search_semaphore` and
# `paperless_factory`. The caller-scope change shortens it (its three
# filter-taking descriptions move to module constants); a split would widen a
# leak-fix diff (spec 20261002-caller-scope-hard, Risks).
def _register_search_tools(
    mcp: FastMCP,
```

In `src/search/mcp_server.py`, replace:

```python
        raw_asker = mcp_asker.get()

        def _build(core: SearchCore) -> str:
```

with:

```python
        raw_asker = mcp_asker.get()
        # Validate the filters BEFORE _run_tool: a rejected filter never
        # resolves the core, checks the spend quota or takes the semaphore, and
        # its clear message is not swallowed by _run_search_tool's sanitising
        # outer-boundary catch.
        ui_filters = _to_search_filters(filters)

        def _build(core: SearchCore) -> str:
```

In `src/search/mcp_server.py`, replace:

```python
                query=query,
                filters=filters,
                core_call=lambda text
```

with:

```python
                query=query,
                filters=ui_filters,
                core_call=lambda text
```

In `src/search/mcp_server.py`, replace:

```python
        description=(
            "PREFERRED, no-cost search — use for almost every query. Returns "
            "ranked source documents (snippets + Paperless deep-links) matching "
            "the query; no synthesised answer. Makes zero LLM calls and does "
            "not bill the archive owner. Read the sources and synthesise the "
            "answer yourself. Optional 'filters' narrows by correspondent, "
            "document type, tag, or date."
        ),
```

with:

```python
        description=_SEMANTIC_SEARCH_DESCRIPTION,
```

In `src/search/mcp_server.py`, replace:

```python
        description=(
            "COSTLY, last-resort search. Runs the archive's server-side agentic "
            "pipeline (planner + judge + synthesiser) and returns a written "
            "answer plus sources. Spends the archive owner's paid LLM API "
            "budget on every call. Prefer semantic_search and synthesise "
            "yourself; only call this when you truly cannot. Optional 'filters' "
            "narrows results."
        ),
```

with:

```python
        description=_DEEP_SEARCH_DESCRIPTION,
```

In `src/search/mcp_server.py`, replace:

```python
        description=(
            "Free. Exact full-text keyword search over document content plus "
            "title/correspondent/type, optionally narrowed by correspondent_id, "
            "document_type_id, tag_ids, date_from/date_to; returns a ranked "
            "DOCUMENT list (not passages). Use for exact terms, names, or "
            "reference numbers, or to enumerate/filter (e.g. every document "
            "tagged X from 2024). Omit 'query' to list documents by filter "
            "alone. Discover valid filter ids with list_filters. Makes no LLM "
            "call. 'limit' defaults to 20 (max 50); 'offset' paginates."
        ),
```

with:

```python
        description=_KEYWORD_SEARCH_DESCRIPTION,
```

In `src/search/mcp_server.py`, replace:

```python
            "Default to semantic_search. Discover filters with list_filters. "
```

with:

```python
            "Search filters are a hard scope: every returned document matches "
            "every filter, they are never relaxed, and multiple tag_ids are "
            "ANDed. An unknown filter key, a non-ISO date or an empty tag_ids "
            "is rejected with an error.\n\n"
            "Default to semantic_search. Discover filters with list_filters. "
```

In `src/search/mcp_server.py`, replace:

```python
    mcp = FastMCP(
        name="paperless-search",
```

with:

```python
    mcp = _StrictFastMCP(
        name="paperless-search",
```


- [ ] **Step 4: Run the whole MCP surface**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_mcp_server_filters.py tests/unit/search/test_mcp_server.py tests/unit/search/test_mcp_server_asker.py tests/unit/search/test_mcp_server_fetch.py tests/unit/search/test_mcp_server_keyword_search.py tests/unit/search/test_mcp_server_list_filters.py tests/integration/test_mcp_mount.py
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS — every existing MCP test passes only declared argument names, so the strict server rejects none of them.

- [ ] **Step 5: Commit**

```bash
git add src/search/mcp_server.py tests/unit/search/test_mcp_server_filters.py
git commit -m "fix(search): reject undeclared MCP arguments and malformed filters with a clear error"
```

---

## Track C — result shape `tag_ids`

### Task C1: Store read models carry raw `tag_ids` (Sonnet)

**Files:**
- Create: `tests/unit/store/test_reader_tag_ids.py`
- Modify: `src/store/models.py` (`IndexedDocument`, `DocumentSummary`)
- Modify: `src/store/reader/_lookups.py` (`get_documents()`, `get_document_summary()`, `# rationale:` header), `src/store/reader/_browse.py` (`list_documents()` and the `# rationale:` above it — §3.1)
- Modify: `tests/helpers/factories/_search.py` (`make_indexed_document()`, `# rationale:` header — §3.1); `tests/unit/search/test_document_routes.py` also gains the `# rationale:` header
- Modify (construction sites, by the script): `tests/unit/store/test_schema.py`, `tests/unit/store/test_models.py`, `tests/unit/search/test_fetch.py`, `tests/unit/search/test_mcp_server_fetch.py`, `tests/unit/search/test_mcp_server_keyword_search.py`, `tests/unit/search/test_document_routes.py`, `tests/unit/search/wire/test_library.py`

**Interfaces:**
- Produces: `IndexedDocument.tag_ids: tuple[int, ...]` and `DocumentSummary.tag_ids: tuple[int, ...]` — **required**, declared right after `tags`; `make_indexed_document(..., tag_ids: tuple[int, ...] = ())`. `keyword_document_search()` gets the field for free (it builds hits from `get_document_summary()`).

Required, not defaulted: a new construction site cannot silently report "no tags". Every existing site passes keyword arguments (checked), so inserting the field after `tags` cannot shift a positional argument. The ids come from the `tag_ids` already parsed by `_parse_tag_ids()` in each reader, so a tag missing from the taxonomy cannot hide an id.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/store/test_reader_tag_ids.py`:

```python
"""Read results carry each document's raw tag ids (spec D4).

A caller scoping searches by tag verifies the scope held from these ids, so
they are the raw ``documents.tag_ids`` values — not the name-resolved list —
and an id missing from the taxonomy is still reported. ``populated_db`` (from
``tests/unit/store/conftest.py``): document 1 carries tags 101 and 102,
document 2 carries tag 102.
"""

from __future__ import annotations

from store.models import ChunkInput, DocumentBrowseQuery, DocumentMeta
from tests.helpers.factories import make_search_filters
from tests.helpers.store import open_reader, open_writer
from tests.unit.store.conftest import unit_vec

# A tag id the taxonomy does not name — placeholder, no real taxonomy id.
_UNNAMED_TAG = 999


def _browse_all() -> DocumentBrowseQuery:
    return DocumentBrowseQuery(
        text=None,
        date_from=None,
        date_to=None,
        correspondent_id=None,
        document_type_id=None,
        tag_ids=(),
        sort="created",
        descending=True,
        offset=0,
        limit=20,
    )


def test_get_documents_carries_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        by_id = {doc.id: doc.tag_ids for doc in reader.get_documents([1, 2])}
    finally:
        reader.close()

    assert by_id == {1: (101, 102), 2: (102,)}


def test_get_document_summary_carries_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        summary = reader.get_document_summary(1)
    finally:
        reader.close()

    assert summary is not None
    assert summary.tag_ids == (101, 102)


def test_list_documents_carries_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        page = reader.list_documents(_browse_all())
    finally:
        reader.close()

    assert {doc.id: doc.tag_ids for doc in page.documents} == {
        1: (101, 102),
        2: (102,),
    }


def test_keyword_document_search_hits_carry_raw_tag_ids(populated_db: str) -> None:
    reader = open_reader(populated_db)
    try:
        page = reader.keyword_document_search(("boiler",), make_search_filters(), 20, 0)
    finally:
        reader.close()

    assert [hit.document.tag_ids for hit in page.hits] == [(101, 102)]


def test_a_tag_id_missing_from_the_taxonomy_is_still_reported(
    populated_db: str,
) -> None:
    """The name list drops an unnamed tag; the id list must not."""
    writer = open_writer(populated_db)
    try:
        writer.upsert_document(
            DocumentMeta(
                id=3,
                title="Unnamed tag",
                correspondent_id=None,
                document_type_id=None,
                tag_ids=(_UNNAMED_TAG,),
                created="2024-07-01T00:00:00+00:00",
                modified="2024-07-01T00:00:00+00:00",
                content_hash="hash3",
                page_count=1,
            ),
            [
                ChunkInput(
                    chunk_index=0,
                    text="untagged",
                    page_hint=1,
                    embedding=unit_vec(4, 0),
                )
            ],
        )
    finally:
        writer.close()
    reader = open_reader(populated_db)
    try:
        (document,) = reader.get_documents([3])
    finally:
        reader.close()

    assert document.tags == ()
    assert document.tag_ids == (_UNNAMED_TAG,)
```

In `tests/helpers/factories/_search.py`, replace:

```python
    tags: tuple[str, ...] = (),
    created: str | None = "2024-01-15T00:00:00+00:00",
) -> IndexedDocument:
    """Create an IndexedDocument as StoreReader.get_documents returns it."""
    return IndexedDocument(
        id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        created=created,
```

with:

```python
    tags: tuple[str, ...] = (),
    tag_ids: tuple[int, ...] = (),
    created: str | None = "2024-01-15T00:00:00+00:00",
) -> IndexedDocument:
    """Create an IndexedDocument as StoreReader.get_documents returns it."""
    return IndexedDocument(
        id=document_id,
        title=title,
        correspondent=correspondent,
        document_type=document_type,
        tags=tags,
        tag_ids=tag_ids,
        created=created,
```


- [ ] **Step 2: Run them and watch them fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/store/test_reader_tag_ids.py
```

Expected: 5 FAIL with `AttributeError: 'IndexedDocument' object has no attribute 'tag_ids'` (and the `DocumentSummary` equivalent).

- [ ] **Step 3: Implement — models, the 16 construction sites, the factory, the headers, the `list_documents()` rationale**

In `src/store/models.py`, replace:

```python
        tags: Tuple of tag names (resolved from taxonomy).
        created: Document date in normalised UTC ISO-8601, or None.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    created: str | None
```

with:

```python
        tags: Tuple of tag names (resolved from taxonomy).
        tag_ids: The raw tag ids from the row's ``tag_ids`` JSON — not the
            name-resolved list, so a tag missing from the taxonomy cannot hide
            an id. Required, so no construction site can silently report "no
            tags".
        created: Document date in normalised UTC ISO-8601, or None.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    tag_ids: tuple[int, ...]
    created: str | None
```

In `src/store/models.py`, replace:

```python
        tags: Tuple of tag names resolved from taxonomy.
        created: Document date in normalised UTC ISO-8601, or None.
        page_count: Number of pages, or None when unknown.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    created: str | None
```

with:

```python
        tags: Tuple of tag names resolved from taxonomy.
        tag_ids: The raw tag ids from the row's ``tag_ids`` JSON (see
            :class:`IndexedDocument`). Required.
        created: Document date in normalised UTC ISO-8601, or None.
        page_count: Number of pages, or None when unknown.
    """

    id: int
    title: str | None
    correspondent: str | None
    document_type: str | None
    tags: tuple[str, ...]
    tag_ids: tuple[int, ...]
    created: str | None
```

Save this script as `add_tag_ids_sites.py` in the session scratchpad directory your system prompt names (never the repository, never /tmp root) and run it from the worktree root (`python <scratchpad>/add_tag_ids_sites.py`); it asserts every count before it writes and stops on any drift — it never commits:

```python
"""Add ``tag_ids=`` after ``tags=`` in every IndexedDocument/DocumentSummary build.

Asserts the per-file construction count first, so a drifted file fails loudly
instead of being half-edited. Source sites carry the parsed ids; test sites an
empty tuple (each test that cares about the value sets it explicitly).
"""

import pathlib
import re

SITES = {
    "src/store/reader/_lookups.py": (2, "tag_ids=tuple(tag_ids),"),
    "src/store/reader/_browse.py": (1, "tag_ids=tuple(tag_ids),"),
    "tests/unit/store/test_schema.py": (1, "tag_ids=(),"),
    "tests/unit/store/test_models.py": (3, "tag_ids=(),"),
    "tests/unit/search/test_fetch.py": (1, "tag_ids=(),"),
    "tests/unit/search/test_mcp_server_fetch.py": (1, "tag_ids=(),"),
    "tests/unit/search/test_mcp_server_keyword_search.py": (1, "tag_ids=(),"),
    "tests/unit/search/test_document_routes.py": (3, "tag_ids=(),"),
    "tests/unit/search/wire/test_library.py": (3, "tag_ids=(),"),
}
CALL = re.compile(r"\b(?:IndexedDocument|DocumentSummary)\(")
TAGS_LINE = re.compile(r"^(?P<indent>[ \t]*)tags=.*,\n", re.MULTILINE)

for name, (expected, value) in SITES.items():
    path = pathlib.Path(name)
    text = path.read_text()
    starts = [m.end() for m in CALL.finditer(text)]
    assert len(starts) == expected, (name, len(starts))
    for start in reversed(starts):
        tags = TAGS_LINE.search(text, start)
        assert tags is not None, (name, start)
        assert "tag_ids=" not in text[start : tags.end() + 80], (name, start)
        insert = f"{tags.group('indent')}{value}\n"
        text = text[: tags.end()] + insert + text[tags.end() :]
    assert text.count(value) >= expected, name
    path.write_text(text)
    print(name, "edited", expected)
```

In `src/store/reader/_lookups.py`, replace:

```python
Allowed deps: sqlite3, json, store.models, store._sql, store.migrations.
"""
```

with:

```python
Allowed deps: sqlite3, json, store.models, store._sql, store.migrations.

# rationale: this file exceeds the §3.1 500-line guideline. Every function here
# is one non-ranked read sharing the connection/query-lock contract and the
# tag-id parsing and name-resolution helpers (``_parse_tag_ids``,
# ``_resolve_tag_names``) that ``_browse`` also imports; the caller-scope change
# only threads ``tag_ids`` through two builds, and a split there would move
# unrelated reads and widen that diff (spec 20261002-caller-scope-hard, Risks).
"""
```


`list_documents()` is over the §3.1 60-line ceiling and this task grows it, so it gets the function-level carve-out (spec Risks; no split in this change). In `src/store/reader/_browse.py`, replace:

```python
def list_documents(
    conn: sqlite3.Connection,
```

with:

```python
# rationale: over the §3.1 60-line ceiling. Most of the body is the count and
# page SQL, which must run under one held lock so the total matches the page,
# with the page's tag names resolved inside that same read. This change only
# threads the raw tag ids into each row; a split would widen a leak-fix diff
# (spec 20261002-caller-scope-hard, Risks).
def list_documents(
    conn: sqlite3.Connection,
```

Two test files this task grows are already over the 500-line ceiling, so each gets the header carve-out (Global Constraints §3.1). In `tests/helpers/factories/_search.py`, replace:

```python
replace the ~28 hand-rolled ``_make_*`` builders the search test files used to
each redeclare.
"""
```

with:

```python
replace the ~28 hand-rolled ``_make_*`` builders the search test files used to
each redeclare.

# rationale: this file exceeds the §3.1 500-line guideline. It is the package's
# one search-shapes factory module, and the shapes' builders call each other;
# the caller-scope change only adds a tag-id parameter, and a split there
# would move unrelated builders and widen a leak-fix diff (spec
# 20261002-caller-scope-hard, Risks).
"""
```

In `tests/unit/search/test_document_routes.py`, replace:

```python
exercised the legacy bearer path have been removed.
"""
```

with:

```python
exercised the legacy bearer path have been removed.

# rationale: this file exceeds the §3.1 500-line guideline. Both document
# routes share one app, auth and stubbed-Paperless fixture set; the
# caller-scope change only adds a field to three constructions, and a split
# there would move unrelated tests and widen a leak-fix diff (spec
# 20261002-caller-scope-hard, Risks).
"""
```

- [ ] **Step 4: Run every suite that builds these shapes**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/store tests/unit/search/test_fetch.py tests/unit/search/test_document_routes.py tests/unit/search/wire/test_library.py tests/unit/search/test_mcp_server_fetch.py tests/unit/search/test_mcp_server_keyword_search.py tests/integration/test_library_api.py
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/store/models.py src/store/reader/_lookups.py src/store/reader/_browse.py tests/helpers/factories/_search.py tests/unit/store/test_reader_tag_ids.py tests/unit/store/test_schema.py tests/unit/store/test_models.py tests/unit/search/test_fetch.py tests/unit/search/test_mcp_server_fetch.py tests/unit/search/test_mcp_server_keyword_search.py tests/unit/search/test_document_routes.py tests/unit/search/wire/test_library.py
git commit -m "feat(store): carry raw tag ids on indexed documents and summaries"
```

### Task C2: `SourceDocument.tag_ids` — `None` for a pruned row (Sonnet)

**Files:**
- Modify: `tests/unit/search/test_sources.py` (append)
- Modify: `src/search/models.py` (`SourceDocument`, `# rationale:` header), `src/search/sources.py` (`_build_source()`)
- Modify: `tests/helpers/factories/_search.py` (`make_source_document()`)

**Interfaces:**
- Consumes: `IndexedDocument.tag_ids` (C1).
- Produces: `SourceDocument.tag_ids: tuple[int, ...] | None = None`, declared **after** `relevance_tier` (the last defaulted field; a non-default field after it is a `TypeError`); `make_source_document(..., tag_ids: tuple[int, ...] | None = None)`. `semantic_search` / `deep_search` serialise `SearchResult` with `dataclasses.asdict` in `_serialise_result()`, so both carry the field with no further change (pinned in S1).

`None`, not `()`: `()` means "this document has no tags", which for a scoped search would read as a leak; a pruned row's tags are *unknown* — the genuine absence CODE_GUIDELINES §5.4 reserves `None` for — and `_build_source()` already sets `title`, `correspondent`, `document_type` and `created` to `None` in that case.

- [ ] **Step 1: Write the failing tests**

Append to the end of `tests/unit/search/test_sources.py`:

```python


# ---------------------------------------------------------------------------
# tag_ids — a caller can verify its tag scope held (spec D4)
# ---------------------------------------------------------------------------


def test_source_carries_the_indexed_documents_tag_ids() -> None:
    reader = _reader(make_indexed_document(document_id=7, tag_ids=(101, 102)))

    sources = _assemble([make_retrieved_chunk(chunk_id=1, document_id=7)], reader)

    assert sources[0].tag_ids == (101, 102)


def test_source_of_a_pruned_row_reports_unknown_tag_ids() -> None:
    """A row pruned mid-request: ``None`` (unknown), never ``()`` (no tags)."""
    sources = _assemble([make_retrieved_chunk(chunk_id=1, document_id=7)], _reader())

    assert sources[0].tag_ids is None
```

In `tests/helpers/factories/_search.py`, replace:

```python
    relevance_tier: RelevanceTier = "good",
) -> SourceDocument:
```

with:

```python
    relevance_tier: RelevanceTier = "good",
    tag_ids: tuple[int, ...] | None = None,
) -> SourceDocument:
```

In `tests/helpers/factories/_search.py`, replace:

```python
        score=score,
        relevance_tier=relevance_tier,
    )
```

with:

```python
        score=score,
        relevance_tier=relevance_tier,
        tag_ids=tag_ids,
    )
```


- [ ] **Step 2: Run them and watch them fail**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_sources.py
```

Expected: 2 FAIL with `AttributeError: 'SourceDocument' object has no attribute 'tag_ids'`.

- [ ] **Step 3: Implement**

In `src/search/models.py`, replace:

```python
No stage imports Pydantic; validation happens only at the HTTP boundary in
api.py (CODE_GUIDELINES.md §5.6).
"""
```

with:

```python
No stage imports Pydantic; validation happens only at the HTTP boundary in
api.py (CODE_GUIDELINES.md §5.6).

# rationale: this file exceeds the §3.1 500-line guideline. It holds only the
# pipeline's frozen I/O dataclasses (one derived property, no other behaviour);
# every stage imports its shapes from this one module and the shapes reference
# each other, so splitting it would add re-export edges (forbidden by the
# no-barrel rule). The caller-scope change only adds a field (spec
# 20261002-caller-scope-hard, Risks).
"""
```

In `src/search/models.py`, replace:

```python
            similarity. What the UI renders as the relevance badge.
    """

    document_id: int
```

with:

```python
            similarity. What the UI renders as the relevance badge.
        tag_ids: The document's raw tag ids, so a caller can verify its tag
            scope held. ``None`` — unknown, not "no tags" — when the index row
            was pruned between retrieval and assembly; ``()`` means the
            document has no tags.
    """

    document_id: int
```

In `src/search/models.py`, replace:

```python
    relevance_tier: RelevanceTier = "good"


@dataclass(frozen=True, slots=True)
class TokenUsage:
```

with:

```python
    relevance_tier: RelevanceTier = "good"
    tag_ids: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
```

In `src/search/sources.py`, replace:

```python
    chunk text is real); only the taxonomy-resolved fields fall back to None.
```

with:

```python
    chunk text is real); only the taxonomy-resolved fields — and ``tag_ids``,
    which is then unknown rather than empty — fall back to None.
```

In `src/search/sources.py`, replace:

```python
        relevance_tier=tier,
    )
```

with:

```python
        relevance_tier=tier,
        tag_ids=indexed.tag_ids if indexed is not None else None,
    )
```


- [ ] **Step 4: Run**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search tests/integration
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/search/models.py src/search/sources.py tests/helpers/factories/_search.py tests/unit/search/test_sources.py
git commit -m "feat(search): expose each source's tag ids so a caller can verify its scope"
```

---

## Track D — SPA request body

### Task D1: The SPA omits an empty `tag_ids` (Sonnet)

**Files:**
- Create: `web/src/api/client/search.test.ts`
- Modify: `web/src/api/client/searchStream.test.ts`
- Modify: `web/src/api/client/search.ts` (new `toSearchRequestBody()`, `search()`), `web/src/api/client/searchStream.ts` (`streamSearch()`, "Allowed deps" header)

**Interfaces:**
- Produces: `export function toSearchRequestBody(body: SearchRequest): string` in `web/src/api/client/search.ts`.
- Consumes: nothing from other tracks. `paramsToFilters()` (`web/src/lib/parseSearchParams.ts`) and `FilterRequest.tag_ids` in `web/src/api/types/search.ts` stay **unchanged**: that `FilterRequest` is UI state read as a required array by `FilterControls`, `ActiveFiltersStrip` and `features/search/filters.ts`.

Built on a shallow copy — `body` and `body.filters` are live UI state and are never mutated (the `delete` runs on a fresh object). `filters: null` / absent passes through, so the existing `filters: null` assertion in `searchStream.test.ts` stays green unmodified. `searchStream.ts` → `search.ts` is an `api` → `api` import, which `web/eslint.config.js` allows (`{ from: 'api', allow: ['api', 'lib'] }`).

- [ ] **Step 0: Install this worktree's SPA dependencies** (each worktree has its own `web/node_modules`; Task 0's install does not reach the track worktree)

```bash
(cd web && npm ci)
```

- [ ] **Step 1: Write the failing tests**

Create `web/src/api/client/search.test.ts`:

```ts
/**
 * Tests for the search request serialiser and `search()` request body.
 *
 * The backend rejects an explicit empty `tag_ids` (spec D11), so the SPA must
 * omit it for an untagged search — without mutating the live UI filter state.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { search, toSearchRequestBody } from './search';
import type { SearchRequest } from '../types';
import { EMPTY_TELEMETRY } from '../types/__fixtures__/searchResponse';

describe('toSearchRequestBody', () => {
  it('drops an empty tag_ids and keeps the other filters', () => {
    const body: SearchRequest = {
      query: 'invoice',
      filters: { tag_ids: [], date_from: '2025-01-01', correspondent_id: 4 },
    };
    expect(JSON.parse(toSearchRequestBody(body))).toEqual({
      query: 'invoice',
      filters: { date_from: '2025-01-01', correspondent_id: 4 },
    });
  });

  it('keeps a non-empty tag_ids', () => {
    const body: SearchRequest = { query: 'invoice', filters: { tag_ids: [7, 9] } };
    expect(JSON.parse(toSearchRequestBody(body))).toEqual(body);
  });

  it('passes null and absent filters through unchanged', () => {
    expect(JSON.parse(toSearchRequestBody({ query: 'q', filters: null }))).toEqual({
      query: 'q',
      filters: null,
    });
    expect(JSON.parse(toSearchRequestBody({ query: 'q' }))).toEqual({ query: 'q' });
  });

  it('does not mutate the request or its filters', () => {
    const filters = { tag_ids: [] as number[], date_to: '2025-12-31' };
    const body: SearchRequest = { query: 'q', filters };
    toSearchRequestBody(body);
    expect(body.filters).toBe(filters);
    expect(filters).toEqual({ tag_ids: [], date_to: '2025-12-31' });
  });
});

describe('search', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends no tag_ids key for an untagged search', async () => {
    const response = JSON.stringify({
      answer: '',
      sources: [],
      plan: { specs: [] },
      stats: { llm_calls: 0, latency_ms: 1, refined: false },
      ...EMPTY_TELEMETRY,
      outcome_kind: 'answered',
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      text: () => Promise.resolve(response),
    });
    vi.stubGlobal('fetch', fetchMock);

    await search({ query: 'invoice', filters: { tag_ids: [] } });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ query: 'invoice', filters: {} });
  });
});
```

In `web/src/api/client/searchStream.test.ts`, replace:

```ts
  it('forwards an AbortSignal to fetch', async () => {
```

with:

```ts
  it('sends no tag_ids key for an untagged search', async () => {
    const fetchMock = mockFetch(200, streamFrom([]));
    await streamSearch({ query: 'invoice', filters: { tag_ids: [] } });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      query: 'invoice',
      filters: {},
    });
  });

  it('forwards an AbortSignal to fetch', async () => {
```


- [ ] **Step 2: Run them and watch them fail**

```bash
(cd web && npx vitest run src/api/client/search.test.ts src/api/client/searchStream.test.ts)
```

Expected: FAIL — `search.test.ts` cannot import `toSearchRequestBody`; the new `streamSearch` test sees `filters: { tag_ids: [] }` in the posted body.

- [ ] **Step 3: Implement**

In `web/src/api/client/search.ts`, replace:

```ts
import type {
  SearchRequest,
```

with:

```ts
import type {
  FilterRequest,
  SearchRequest,
```

In `web/src/api/client/search.ts`, replace:

```ts
/** POST /api/search — run the agentic search pipeline. */
export async function search(body: SearchRequest): Promise<SearchResponse> {
  return request<SearchResponse>(`${BASE_URL}/api/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
```

with:

```ts
/**
 * Serialise a search request body for the wire, omitting an empty `tag_ids`.
 *
 * The backend rejects an explicit `tag_ids: []` (a hard-scope filter that
 * names no tag fails closed), while an omitted key means "no tag constraint".
 * The UI's `FilterRequest` keeps `tag_ids` as a required array, so the
 * omission happens here, at the wire boundary. Builds a shallow copy — `body`
 * and `body.filters` are live UI state and are never mutated. A `null` or
 * absent `filters` passes through unchanged.
 */
export function toSearchRequestBody(body: SearchRequest): string {
  const { filters } = body;
  if (!filters || filters.tag_ids.length > 0) {
    return JSON.stringify(body);
  }
  // `delete` on a fresh copy only — the caller's `filters` is never touched.
  const wireFilters: Partial<FilterRequest> = { ...filters };
  delete wireFilters.tag_ids;
  return JSON.stringify({ ...body, filters: wireFilters });
}

/** POST /api/search — run the agentic search pipeline. */
export async function search(body: SearchRequest): Promise<SearchResponse> {
  return request<SearchResponse>(`${BASE_URL}/api/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: toSearchRequestBody(body),
  });
}
```

In `web/src/api/client/searchStream.ts`, replace:

```ts
 * Allowed deps: core (error types + BASE_URL), types (leaf module —
 * CODE_GUIDELINES §12.3).
 */

import type { SearchRequest, StreamEvent } from '../types';
import { ApiError, BASE_URL, Unauthenticated } from './core';
```

with:

```ts
 * Allowed deps: core (error types + BASE_URL), search (toSearchRequestBody),
 * types (leaf module — CODE_GUIDELINES §12.3).
 */

import type { SearchRequest, StreamEvent } from '../types';
import { ApiError, BASE_URL, Unauthenticated } from './core';
import { toSearchRequestBody } from './search';
```

In `web/src/api/client/searchStream.ts`, replace:

```ts
    body: JSON.stringify(body),
    ...(signal ? { signal } : {}),
```

with:

```ts
    body: toSearchRequestBody(body),
    ...(signal ? { signal } : {}),
```


- [ ] **Step 4: Run the web gates this track can turn red**

```bash
(cd web && npm run typecheck && npm run lint && npm run test:coverage && npm run build)
```

Expected: all exit 0; coverage stays above the 91/83/91/91 floor (measured on the plan's dry run: 93.04 / 85.32 / 93.75 / 93.85).

- [ ] **Step 5: Commit**

```bash
git add web/src/api/client/search.ts web/src/api/client/searchStream.ts web/src/api/client/search.test.ts web/src/api/client/searchStream.test.ts
git commit -m "fix(web): omit an empty tag_ids from search request bodies"
```

---

## Track E — docs and decision

### Task E1: `docs/search-pipeline.md` and the DECISIONS entry (Sonnet)

**Files:**
- Modify: `docs/search-pipeline.md` — human doc; the edits below are the ones D8 authorises, nothing else
- Modify: `.claude/DECISIONS.md` (append)
- Out of scope, not edited: `docs/search.md` — human doc, outside D8, so not authorised. It states the old contract (**Filters.**: "Unknown keys are ignored") and its `keyword_search` output field list lacks `tag_ids` (D4). Step 4 records both for the PR body instead.

**Interfaces:** none (prose). Anchors are the doc's own headings and the flowchart node id `T6`.

- [ ] **Step 1: Edit `docs/search-pipeline.md`**

In `docs/search-pipeline.md`, replace:

```markdown
        T5 -- yes, first try --> T6[broaden: drop all filters\nretry once]
```

with:

```markdown
        T5 -- yes, first try --> T6[broaden: drop planner guesses\nkeep caller filters\nretry once unless it repeats pass 1]
```

In `docs/search-pipeline.md`, replace:

```markdown
- `tag_ids` → order-stable de-duplicated union (all required).
```

with:

```markdown
- `tag_ids` → order-stable de-duplicated union (all required).

**Caller filters are a hard scope.** The filters a caller sends — the MCP
`filters` argument or the HTTP request body's `filters` — narrow every search
and are never relaxed. Recall insurance (the twins below, broaden-and-retry,
the refinement re-plan) strips only what the *planner* guessed. As a second
line of defence, `Retriever.retrieve(specs, scope=ui_filters)` re-applies
`_intersect()` to every spec immediately before each store call, so a future
relaxation path cannot widen a scoped search either. (`keyword_search` never
enters the retriever; its filters go straight to the store.)

Multiple `tag_ids` are **ANDed**: a document must carry every listed tag. There
is no any-of form.

A malformed caller filter is rejected at the boundary, never ignored: an unknown
key (`tag_id` for `tag_ids`), a mis-keyed container (`filter` for `filters`), a
`date_from` / `date_to` that is not an ISO date, or an explicitly empty
`tag_ids` is a 422 over HTTP and a tool error over MCP. An omitted `tag_ids`
still means "no tag constraint".
```

In `docs/search-pipeline.md`, replace:

```markdown
path — the normal planner already binds at least one spec to a date.

#### SQL date filter correctness
```

with:

```markdown
path — the normal planner already binds at least one spec to a date.

#### Recall twins (planner guesses only)

When `resolve_specs()` is given `max_specs` (pass 1 and the refinement re-plan),
every resolved spec that carries a filter gains a *twin*: the same query with
the planner's guesses stripped but the caller's filters kept
(`_intersect(_EMPTY_FILTERS, ui_filters)`). A wrong planner guess would
otherwise silently exclude the answer; the twin still retrieves it, and RRF
rewards a document both find. A spec whose only filters are the caller's yields
a twin identical to itself, which the retrieval-identity dedup drops — so a
caller-scoped `semantic_search` runs no extra search. Only twins count against
`SEARCH_PLANNER_MAX_SPECS`; originals always survive.

#### SQL date filter correctness
```

In `docs/search-pipeline.md`, replace:

```markdown
When the first retrieval pass returns an empty list, the core retries once with
all filter guesses dropped (`broaden_plan()` clears every spec's `filter_guess`,
and the broadened pass is resolved with `ui_filters=None`).  A user-set filter is
not the cause of a mis-resolved planner filter, so it is dropped too.  This retry
fires once per query, never recursively.
```

with:

```markdown
When the first retrieval pass returns an empty list, the core retries once with
every planner guess dropped (`broaden_plan()` clears every spec's
`filter_guess`) and the caller's filters kept: the broadened pass is resolved
with the same `ui_filters`.  This reverses the upstream design, which dropped a
user-set filter too on the grounds that it is not the cause of a mis-resolved
planner filter: a caller that keeps tenants apart by tag relies on that filter,
and silently broadening past it returned other tenants' documents.

If every broadened search already ran in pass 1 — always true for a scoped
`semantic_search`, whose twins already ran the scope-only searches — the retry
would repeat pass 1, so it is skipped and the trace reports
`broadened: false`.  In practice broaden now fires only when
`SEARCH_PLANNER_MAX_SPECS` cut off a twin.  The retry fires once per query,
never recursively.
```

In `docs/search-pipeline.md`, replace:

```markdown
| `retriever.py` | `resolve_specs` + `Retriever` — name/date resolution, the date safety net, per-spec fan-out, RRF fusion, broaden-and-retry |
```

with:

```markdown
| `retriever.py` | `resolve_specs` + `Retriever` — name/date resolution, the date safety net, recall twins (planner guesses only), per-spec fan-out under the caller-scope choke point, RRF fusion |
```


- [ ] **Step 2: Append the decision to `.claude/DECISIONS.md`**

```markdown

## 2026-10-02 — Caller filters are a hard search scope; recall insurance relaxes only planner filters

Reverses the upstream design that dropped a user-set filter during broaden-and-retry
(`docs/search-pipeline.md` said a user filter "is dropped too"). Three recall-insurance paths —
filter-stripped twins, broaden-and-retry, and refinement twins — also stripped the *caller's*
filters, so a caller keeping tenants apart by tag got other tenants' documents fused into a
tag-scoped `semantic_search`, with no way to detect it. Caller filters are now a hard scope; the
insurance strips planner guesses only. Defence in depth: `Retriever.retrieve(specs, *, scope)`
re-intersects every spec with the scope before any store call, so a future relaxation path (or an
upstream merge re-adding one) cannot reopen the leak; `keyword_search` never enters the retriever
and is held by test only. Malformed caller filters fail closed on MCP and HTTP — unknown keys, a
mis-keyed `filters` container (enforced over MCP by `_StrictFastMCP`, since FastMCP itself drops
undeclared arguments and does not enforce its schema), non-ISO dates and an explicit empty
`tag_ids`; the SPA stops sending `tag_ids: []`. Results carry raw `tag_ids` (`None` for a row
pruned mid-request). Multiple `tag_ids` stay ANDed. A broaden whose searches all ran in pass 1 is
skipped, which nearly retires broaden (it fires only when `SEARCH_PLANNER_MAX_SPECS` cut a twin)
and removes its incidental second embedding call; retrying a transient embedding failure belongs
to the client's own retry. At plan time the date rule was tightened beyond the spec's two checks:
the ISO week form (`2025-W17-5`) passes both, so the parsed date must also equal the
ten-character prefix. Rejected: a per-site fix without a choke point; keeping the old semantics
for the web UI; an MCP-only empty-`tag_ids` rule; making `tag_ids` optional in the SPA's UI state.
**Spec:** `.claude/specs/20261002-caller-scope-hard.md`
**Affects:** `src/search/retriever.py`, `src/search/core.py`, `src/search/wire/search.py`, `src/search/mcp_server.py`, `src/store/models.py`, `src/store/reader/_lookups.py`, `src/store/reader/_browse.py`, `src/search/models.py`, `src/search/sources.py`, `web/src/api/client/search.ts`, `web/src/api/client/searchStream.ts`, `docs/search-pipeline.md`
```

- [ ] **Step 3: Check the anchors**

```bash
rg -n "drop all filters|dropped too" docs/search-pipeline.md        # expect no output
rg -n "Recall twins \(planner guesses only\)|Caller filters are a hard scope" docs/search-pipeline.md   # expect 2 lines
```

The names the entry cites (`_StrictFastMCP`, `Retriever.retrieve(specs, *, scope)`) exist only once the tracks merge; Task I1 greps them.

- [ ] **Step 4: Record the stale human doc for the PR body (no edit)**

Do not edit `docs/search.md`. Report to the orchestrator, by file and anchor, for the PR body's "human docs to update" section: (1) `docs/search.md`, Tool reference, **Filters.** — the sentence "Unknown keys are ignored" is now false (an unknown key is a tool error over MCP and a 422 over HTTP); (2) the same section's `keyword_search` output field list `{ documents: [{ document_id, title, correspondent, document_type, created, snippet, paperless_url }] … }` lacks the new `tag_ids` (D4). Both are left stale pending a human-authorised edit; the review-team gate has this recorded disposition.

- [ ] **Step 5: Commit**

```bash
git add docs/search-pipeline.md .claude/DECISIONS.md
git commit -m "docs(search): record caller filters as a hard search scope"
```

---

## Serial phase

### Task I1: Merge the tracks and integrate (Haiku)

**Files:** none edited (merge commits only).

- [ ] **Step 1: Merge each track branch into `fix/caller-scope-hard`**, from the feature worktree root (`.claude/worktrees/caller-scope-hard`), in the order A, B, C, D, E:

```bash
for track in a b c d e; do
  git merge --no-ff --no-edit "fix/caller-scope-hard-$track" || break
done
git status --short
```

A conflict (a non-zero `git merge`) means the disjointness claim above is wrong: run `git merge --abort`, stop, and report to the orchestrator which track conflicted on which files. Do not resolve it here and do not continue to Step 2.
- [ ] **Step 2: Run the merged suite and the names check**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest -n auto
ruff check src tests && ruff format --check src tests && mypy src
rg -n "_StrictFastMCP|_BroadenOutcome" src | head -4 && rg -n "toSearchRequestBody" web/src | head -3
```

Expected: exit 0 everywhere; each name found.

- [ ] **Step 3: Remove the track worktrees and their merged branches**

```bash
WT="$(git rev-parse --path-format=absolute --git-common-dir)/../.claude/worktrees"
for track in a b c d e; do
  git worktree remove "$WT/caller-scope-hard-$track" && git branch -d "fix/caller-scope-hard-$track"
done
```

`git worktree remove` refuses a worktree with uncommitted changes and `git branch -d` refuses an unmerged branch: never add `--force` / `-D` — report it instead.

### Task S1: MCP results carry `tag_ids` — `keyword_search` and the serialised sources (Sonnet)

**Files:**
- Create: `tests/unit/search/test_mcp_server_tag_ids.py`
- Modify: `src/search/mcp_server.py` (`keyword_search` document object)

**Interfaces:**
- Consumes: `DocumentSummary.tag_ids` (C1), `SourceDocument.tag_ids` (C2), B2's `mcp_server.py`.

- [ ] **Step 1: Write the tests**

Create `tests/unit/search/test_mcp_server_tag_ids.py`:

```python
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
```


- [ ] **Step 2: Run them**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_mcp_server_tag_ids.py
```

Expected: 1 FAIL (`KeyError: 'tag_ids'` on the keyword document). The two `semantic_search` / `deep_search` cases already PASS — `dataclasses.asdict` carries C2's field — and stay as pins that a pruned row serialises as `null`, never `[]`.

- [ ] **Step 3: Implement**

In `src/search/mcp_server.py`, replace:

```python
                            "created": hit.document.created,
                            "snippet": hit.snippet,
```

with:

```python
                            "created": hit.document.created,
                            "tag_ids": list(hit.document.tag_ids),
                            "snippet": hit.snippet,
```


- [ ] **Step 4: Run**

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest tests/unit/search/test_mcp_server_tag_ids.py tests/unit/search/test_mcp_server_keyword_search.py
ruff check src tests && ruff format --check src tests && mypy src
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/search/mcp_server.py tests/unit/search/test_mcp_server_tag_ids.py
git commit -m "feat(search): include tag ids in MCP keyword_search documents"
```

### Task G1: Every gate in `.claude/GATES.md` (Haiku)

**Files:** none. Run each of the ten gates **exactly as written** in `.claude/GATES.md`, from the worktree root, and record each exit code. A red gate means the work is not done: report it, never edit the gate or what it points at.

```bash
source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"
python -m pytest -n auto                                   # gate: python-tests
mypy src                                                   # gate: python-types
ruff check src tests && ruff format --check src tests      # gate: python-lint
bandit -r src/ -ll                                         # gate: python-security
(cd web && npm run typecheck)                              # gate: web-types
(cd web && npm run lint)                                   # gate: web-lint
(cd web && npm run test:coverage)                          # gate: web-tests-coverage
(cd web && npm run build)                                  # gate: web-build
pip-audit                                                  # gate: python-dep-audit
(cd web && npm audit --omit=dev --audit-level=high)        # gate: web-dep-audit
```

Expected: all ten exit 0. `bandit` prints 23 pre-existing `nosec encountered` warnings (22 `B608`, 1 `B104`, across eight files — identical on `ecaeb28`); they are not findings. Its pass condition is exit 0 **and** `No issues identified.` in the output. The two audit gates depend on the advisory databases on the day: a new advisory against an untouched dependency is reported to the orchestrator, not "fixed" here. Then delete `web/coverage/` if the run left it untracked (`git status --short` must be clean).

### Task M1: The fourteen mutations — break, run, observe red, restore (Sonnet)

**Files:** none committed. The tree is clean before each mutation and restored with `git checkout -- <file>` after it — never `git stash`, never a commit. Each row is run **only now**; the "expected red" column is the prediction from the plan's dry run, and the report records the test ids that actually went red. A mutation that leaves every test green is a **finding** — stop and report it; never weaken the mutation to make it bite.

Run every command from the feature worktree root after `source "$(git rev-parse --path-format=absolute --git-common-dir)/../.venv/bin/activate"` (Global Constraints: shell state does not persist between tool calls, so prefix each run with it). For each row: apply the change, run the command, read the FAILED lines, `git checkout -- <file(s)>`, confirm `git status --short` is clean.

| # | Mutation (exact edit) | Run | Expected red (at least) |
|---|---|---|---|
| 1 | `src/search/retriever.py` `_run_passes()`: both `_intersect(spec.filters, scope)` → `spec.filters` | `python -m pytest tests/unit/search/test_retriever_scope.py` | `test_every_store_call_carries_the_caller_scope[101]`, `[202]`, `test_scope_narrows_a_spec_that_carries_its_own_filters` |
| 2 | `src/search/retriever.py` `_append_unfiltered_twins()`: `filters=_intersect(_EMPTY_FILTERS, ui_filters)` → `filters=_EMPTY_FILTERS` | `python -m pytest tests/unit/search/test_resolve_specs_scope.py tests/unit/search/test_core_scope.py` | all four in `test_resolve_specs_scope.py`; `test_refinement_specs_carry_the_caller_scope` |
| 3 | `src/search/core.py` `_retrieve_with_broaden()`: `broaden_plan(plan), facets, ui_filters=ui_filters, today=today` → `ui_filters=None` | `python -m pytest tests/unit/search/test_core_scope.py` | `test_broaden_resolves_the_broadened_plan_with_the_caller_scope` (spy sees unscoped specs) |
| 4 | `src/search/core.py` `_refine()`: the `resolve_specs(replan_outcome, facets, ui_filters=ui_filters, …)` argument → `ui_filters=None` | `python -m pytest tests/unit/search/test_core_scope.py` | `test_refinement_specs_carry_the_caller_scope` |
| 5 | `src/search/core.py` `_retrieve_with_broaden()`: delete the two-line `if all(_spec_search_key(spec) in pass_one_keys …): return _BroadenOutcome(chunks=[], …)` | `python -m pytest tests/unit/search/test_core_scope.py` | `test_scoped_search_with_an_empty_first_pass_does_not_repeat_it` |
| 6 | `src/search/wire/search.py` `FilterRequest`: delete `model_config = ConfigDict(extra="forbid")` | `python -m pytest tests/unit/search/wire/test_search.py tests/unit/search/test_mcp_server_filters.py tests/unit/search/test_api_filters.py` | `test_filter_request_rejects_an_unknown_key[*]`; the `tag_id` / `tags` rows of `test_malformed_filters_are_rejected_naming_the_key`; the `{"tag_id": 5}` row of `test_malformed_filters_are_a_422` |
| 7 | `src/search/wire/search.py`: delete the `@field_validator("date_from", "date_to")` decorator line | same as 6 | every `test_filter_request_rejects_a_non_iso_date[*]`; the date rows on MCP and HTTP |
| 8 | `src/search/wire/search.py`: delete the `@model_validator(mode="after")` decorator line | same as 6 | `test_filter_request_rejects_an_explicitly_empty_tag_list`; the `tag_ids: []` rows on MCP (all three tools) and HTTP (both endpoints) |
| 9 | `src/search/mcp_server.py`: move conversion back inside the `try` — in `_dispatch()` delete the `ui_filters = _to_search_filters(filters)` line directly after the `# outer-boundary catch.` comment (which follows `raw_asker = mcp_asker.get()`) — **not** the identical line in `keyword_search` — and pass `filters=filters`; in `_run_search_tool()` call `core_call(query, _to_search_filters(filters), asker)` | `python -m pytest tests/unit/search/test_mcp_server_filters.py` | the `semantic_search` / `deep_search` rows of `test_malformed_filters_are_rejected_naming_the_key` (`search failed` text) |
| 10 | Mutations 1 + 2 + 3 + 4 together (choke point and every site) | `python -m pytest tests/integration/test_caller_scope.py` | the six scoped tests (L1, L1 via L4, L2 ×2, L3, multi-tag AND) |
| 11 | `web/src/api/client/search.ts` `toSearchRequestBody()`: make the first statement `return JSON.stringify(body);` | `cd web && npx vitest run src/api/client/search.test.ts src/api/client/searchStream.test.ts` | `drops an empty tag_ids and keeps the other filters`; both `sends no tag_ids key for an untagged search` |
| 12 | `src/search/wire/search.py` `SearchRequest`: delete its `model_config = ConfigDict(extra="forbid")` | `python -m pytest tests/unit/search/wire/test_search.py tests/unit/search/test_api_filters.py` | `test_search_request_rejects_a_mis_keyed_filters_container`; the `filter` / `Filters` rows of `test_malformed_filters_are_a_422` on both endpoints |
| 13 | `src/search/mcp_server.py` `build_mcp_app()`: `mcp = _StrictFastMCP(` → `mcp = FastMCP(` | `python -m pytest tests/unit/search/test_mcp_server_filters.py` | every `test_a_mis_keyed_filters_container_is_rejected[*]`; `test_the_zero_llm_tools_reject_undeclared_arguments_too[*]`; `test_every_tool_schema_forbids_undeclared_arguments` |
| 14 | `src/search/mcp_server.py` `_StrictFastMCP`: rename `async def list_tools` → `async def _unused_list_tools` (removes the override; `call_tool` still enforces) | `python -m pytest tests/unit/search/test_mcp_server_filters.py` | `test_every_tool_schema_forbids_undeclared_arguments` only |

The "expected red" column is a **prediction** from the plan author's dry run on a scratch copy; it is not a record and claims nothing. The record is this task's own run: per row, the exact edit made, the FAILED test ids observed, and confirmation the tree was restored clean. Only after that run may any document say a mutation is pinned.

---

## Self-review

- **Spec coverage.** R1 → A1–A3 (retriever paths), B1/B2 (boundary), A1 `test_scoped_keyword_search_returns_only_the_scope` (L8). R2 → existing `test_resolve_specs.py` twin tests stay green unchanged (A2 Step 2/4). R3 → B1, B2, D1. R4 → C1, C2, S1. R5 → B2 (descriptions, `instructions`), E1. R6 → A1 `test_unscoped_search_still_reaches_both_tenants` (`retrieve()`) and `test_unscoped_deep_search_still_reaches_both_tenants` (`answer()`), A3 D9 note. D1–D11 → Global Constraints and the owning tasks; D10 (deploy) is operational, not a task. Leak inventory L1–L11 → one forcing input or pin each (L4/L5 by A1/A2 tests; L9/L10 are out of scope by the spec). "Docstrings that are wrong today" → A2/A3 (core, retriever), B1 (`FilterRequest`), B2 (`_to_search_filters`). §3.1 → file headers in B2 (length + import cap), C1, C2, A3 and C1 (test files), A1 (`core.py` import cap); function carve-outs above `_refine()` (A1), `list_documents()` (C1); `_register_search_tools()` (B2, 190 lines — pre-existing, `# rationale:`; the three description constants shrink it from what inline text would make it) — all three limits swept on the merged replay. §5.8 → A3. Gates → G1. Mutations 1–14 → M1.
- **Placeholder scan.** Every code step is a concrete block that was applied and run; no "TBD", no "similar to Task N".
- **Type consistency.** `scope` (keyword-only) everywhere `Retriever.retrieve` is called; `_BroadenOutcome` fields `chunks` / `signal` / `broadened` used identically in A3's producer and consumer; `tag_ids` is `tuple[int, ...]` on store models and `tuple[int, ...] | None` on `SourceDocument`, serialised as a list / `null`.
- **Review Focus.** Five lines, each with a test in its owning task (A1, B1 ×2, B2 ×2).

## Review rounds

| Round | Scope | Verdict | Outcome |
|---|---|---|---|
| 1 | full | NO-SHIP 1 major 9 minor | resolved in `80bfbcc` and this commit |
| 2 | incremental | NO-SHIP 1 major 2 minor | resolved in this commit |
| 3 | full certify | NO-SHIP 1 major 2 minor | resolved in this commit |

Round 1 resolution notes:

- F1 → Global Constraints §3.1 now carries all three limits; `# rationale:` above `_refine()` (A1), `list_documents()` (C1); B2's header covers the import cap (40 names before, 45 after: B2 adds five), A1 extends `core.py`'s header to its import count. F9 → header carve-outs on the four over-ceiling test files (A3, C1) — the repo already treats §3.1 as binding tests (`test_core.py` cites it). F2 → 23 warnings, measured on `ecaeb28`. F3 → the venv line heads every tool-running block; M1 says so in prose. F4 → track branches/worktrees named and created in *Tracks and file sets*; I1 aborts and reports on conflict. F5 → `test_unscoped_deep_search_still_reaches_both_tenants`. F6 → 16 sites (+ the factory). F7 → helper scripts go to the session scratchpad; Task 0's probe uses the worktree's git dir (in-repo, never committed — a session path cannot go in a public plan). F8 → `MagicMock` (what `make_pipeline_settings` returns, not `Settings`), `Path`, `TestClient`, `_McpApp`, `CallToolResult`, `SearchFilters | None`; JSON arguments are `dict[str, object]` (no `Any` left to justify); the `_StrictFastMCP.call_tool` override's `Any` gets a rationale. F10 → row 9 anchored on the `# outer-boundary catch.` comment.
- Re-verified on a fresh scratch replay of `ecaeb28` with every block applied in task order (no anchor missed or duplicated): `ruff check`, `ruff format --check`, `mypy src` clean; `mypy` on the eight new test modules clean (one pre-existing error in `tests/helpers/search.py`, identical on the base); `pytest -n auto` 3571 passed; A1's red set 6 failed / 3 passed; S1's red set 1 failed / 2 passed; a §3.1 sweep (file lines, executable body lines, imported names) of every touched file shows each exception carrying a `# rationale:`; the M1 row-9 anchor occurs once. No TypeScript changed this round.
- Follow-up (this commit, orchestrator decision): `80bfbcc` had given `_register_search_tools()` a `# rationale:` carve-out; this commit moved the three lengthened descriptions to module-level constants and dropped it, on a nested-closures-count-separately reading that round 2 rejected. Re-verified on a fresh scratch replay of `ecaeb28`, every block applied in task order: `ruff check`, `ruff format --check`, `mypy src` clean; `pytest -n auto` 3571 passed; the tool descriptions are byte-identical to the inline ones `80bfbcc` specified; [superseded by round 2: `_register_search_tools()` measures 190 by §3.1's literal count]; the §3.1 sweep lists `mcp_server.py` only for file length (918) and imports (40 → 45), both under its header; [superseded by round 2: the touched functions over 60 are `_refine()`, `list_documents()` and `_register_search_tools()`, each with its `# rationale:`].

Round 1 lesson-candidates:

- A §3.1 sweep measures all three limits (file lines, function body lines, imported names) on every touched file — tests included — after the plan's edits, not file length alone.
- A gate step's expected output (warning counts, skip counts) is measured on the base, never remembered.
- A parallel-track plan names each track's branch and worktree where it creates them, so the merge task carries no `<placeholder>` and its conflict rule fits the moment it runs.
- A type tightening reads the factory's real return type (`MagicMock`, not the class it imitates) and prefers `object` over a commented `Any` where the value is only passed through.

Round 2 resolution notes:

- R2-F1 → `# rationale:` above `def _register_search_tools(` (pre-existing 211 lines on `ecaeb28`, 190 on the merged replay, by §3.1's literal count); the description constants' purpose restated as shrinking the registrar; the Global Constraints §3.1 bullet, B2 prose, self-review, and the round-1 notes corrected. R2-F2 → `_client_and_headers()` returns a frozen `_ApiHarness` dataclass; both callers updated. R2-F3 → the three constants sit right after the imports (anchored on the end of the `TYPE_CHECKING` block).
- Re-verified on a fresh scratch replay of `ecaeb28`, every block applied in task order plus the documented A1 `ruff format` fix-up: `ruff check`, `ruff format --check`, `mypy src` clean; `pytest -n auto` 3571 passed.

Round 2 lesson-candidates:

- A ceiling-avoidance claim states its counting convention and checks it against the guideline's literal exclusion list; a convention the guideline does not state is an interpretation, flagged as one.
- Code moved to satisfy one rule is re-checked against its neighbours: hoisting strings to module constants triggers §3.5's placement rule.
- A type-tightening pass also checks shape rules (§5.8 three-element tuples), not just annotations.

Round 3 resolution notes:

- R3-F1 -> Task E1 names `docs/search.md` as out of scope (human doc, outside D8) and gains Step 4, which records the stale "Unknown keys are ignored" sentence and the `keyword_search` output field list (no `tag_ids`) for the PR body; no edit to `docs/search.md` is planned. R3-F2 -> every `; cd ..` block is now a subshell `(cd web && ...)` (D1 Steps 2 and 4; the `npm ci` lines too). R3-F3 -> A2 Step 2 points at Step 6.

Round 3 lesson-candidates:

- A change to a contract sweeps every human doc that states the old contract, not only the doc the spec authorised; the plan names any out-of-authority doc and routes it to the PR body.
- `cd X && ...; cd ..` returns the exit status of `cd ..`; any block whose exit code is the pass signal uses the subshell form `(cd X && ...)`.
- When steps are renumbered, grep the plan for "Step N" cross-references.
