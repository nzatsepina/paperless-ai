# Caller filters are a hard search scope

**Status:** draft — `fix/caller-scope-hard`
**Date:** 2026-10-02
**Decision log:** `.claude/DECISIONS.md` — entry to be added with the implementation (*caller filters are a hard scope; recall insurance relaxes only planner filters*)

> This repository is public. The spec describes properties of the software —
> "a multi-tenant caller scopes requests by tag" — and names no deployment: no
> host, container, domain, client, downstream project, real taxonomy id or
> person. Every id below is a placeholder.

## Origin — the problem before the solution

A caller that serves several tenants from one archive keeps them apart by tag:
every search it issues carries `filters.tag_ids=[<tenant tag>]`, and it relies
on the server returning only documents carrying that tag. The server does not
honour that. Three recall-insurance mechanisms, added upstream to recover from
*the planner's* mis-resolved filter guesses, also relax the *caller's* filter:

filter-stripped "twins" of every filtered spec (`_append_unfiltered_twins()`),
a retry of an empty first pass with the caller filter set to `None`
(`_retrieve_with_broaden()`), and twins again on the refinement re-plan (`_refine()`).

So a tag-scoped `semantic_search` — which always carries filters and never
carries planner guesses — runs two unfiltered passes on every call and returns
other tenants' documents, fused into the same ranked list. A caller cannot
detect it: results carry no tag information. The only safe workaround is to
avoid semantic search altogether, giving up its recall.

The upstream design documents the drop as deliberate (`docs/search-pipeline.md`,
"Broaden-and-retry": *"A user-set filter is not the cause of a mis-resolved
planner filter, so it is dropped too"*). This spec reverses that decision for
caller-supplied filters only.

## Requirements

1. **R1 — hard scope.** On every search entry point (MCP `semantic_search`,
   `deep_search`, `keyword_search`; HTTP `POST /api/search`, `/api/search/stream`)
   every returned document satisfies every caller filter; no path, current or
   future, may drop or loosen one. Mechanically guaranteed for every path through
   `Retriever` (semantic, deep, web — D2); `keyword_search` never enters
   `Retriever` and is held by test only (L8).
2. **R2 — planner recall insurance kept.** Twins and broaden still strip filters
   the planner *inferred*.
3. **R3 — fail closed.** A malformed caller filter is rejected with a clear error.
4. **R4 — verifiable.** Results expose each source's tag ids.
5. **R5 — stated.** MCP tool text says filters are a hard scope and `tag_ids` AND.
6. **R6 — unscoped callers unchanged.** No filters → the same documents as today,
   except that a broaden that would repeat pass 1 is skipped (D9) — and with it
   the incidental second embedding attempt that broaden made today (see D9).

## Decisions (human, binding)

- **D1 — caller filters are a hard scope; planner filters stay relaxable.**
  "Caller filters" means `ui_filters` as built by `to_search_filters()`
  (`src/search/wire/search.py`) from the MCP tool argument or the HTTP request
  body. Twins (L1), broaden-and-retry (L2), refinement twins (L3) and any future
  relaxation may strip planner guesses only. *Why:* the caller uses tag filters
  to keep one tenant's documents out of another's results; silent broadening
  defeats the only isolation it has. Recall insurance exists to recover from the
  planner's mistakes, and a caller filter is not a planner mistake.
- **D2 — one choke point plus site fixes.** `Retriever.retrieve()` takes the
  caller scope and `_run_passes()` intersects every spec's filters with it before
  any store call. The individual sites are fixed too, so they stop producing
  specs the choke point would collapse into duplicates. *Why:* a per-site fix is
  only as good as the next author's memory — a new relaxation path, or an
  upstream merge re-adding one, is caught by the choke point without anyone
  remembering the rule. **Limit:** the choke point covers only paths that
  enter `Retriever`. `SearchCore.keyword_search()` hands `ui_filters` straight
  to `keyword_document_search()` / `list_documents()` and never reaches it, so a
  future edit there is caught only by the L8 end-to-end test, not by D2.
- **D3 — reject malformed filters at the boundary (fail closed).** Unknown keys,
  non-ISO `date_from` / `date_to`, and an explicitly empty `tag_ids` — on both
  MCP and HTTP (D11). *Why:* a typo'd key (`tag_id`) or `tag_ids: []`
  today yields an unscoped search with no error — a hard-scope contract with a
  fail-open input is hollow (CODE_GUIDELINES §1.11).
- **D4 — results carry `tag_ids`.** `semantic_search`, `deep_search` (same
  `SourceDocument` type) and `keyword_search` results include each document's
  tag ids. *Why:* lets a client verify the scope held, and gives a post-deploy
  receipt ("every source carries the scope tag").
- **D5 — the contract is stated.** MCP tool descriptions and the server
  `instructions` say filters are a hard scope, never relaxed. *Why:* agents rely
  on what the tool text promises.
- **D6 — multiple `tag_ids` stay AND.** `build_filters()`
  (`src/store/reader/_filters.py`) adds one `EXISTS` clause per id. Documented
  explicitly, not changed. *Why:* any-of semantics is new scope (see Rejected);
  today the twins and broaden re-admitted single-tag documents and hid the AND,
  so a multi-tag caller will see fewer results after this change — the docs and
  tool text must say so.
- **D7 — the web UI gets the same semantics.** `_search()` and `_search_stream()`
  (`src/search/routes.py`) pass the same `ui_filters` to `core.answer()`.
  Recorded as an intended behaviour change: a filtered web search that matches
  nothing now returns the existing "empty_retrieval" no-match instead of
  unfiltered results. *Why:* it is the same concept; keeping the old behaviour
  for the web alone would need a flag plumbed through core — machinery for a
  behaviour nobody asked to keep.
- **D8 — `docs/search-pipeline.md` is edited.** The human authorised editing this
  human doc to record the reversal of the upstream "user filter is dropped too"
  design and to add the missing description of twins.
- **D9 — skip a broaden pass that repeats pass 1.** With a hard scope and no
  planner guesses (always the case for `semantic_search`), the broadened specs
  resolve to the same searches as pass 1; re-running them re-pays the embedding
  call and falsely reports `broadened: true`. *Why:* review finding — pointless
  work and a lying trace. **Consequence (to be acknowledged by the human):** once
  twins keep the caller scope, every twin equals what `broaden_plan()` + scope
  resolves to, so the broadened searches are a subset of pass 1 whenever every
  twin ran. Broaden-and-retry then fires **only when `max_specs` truncated the
  twins** — that is, when the resolved pass-1 specs already number at least
  `SEARCH_PLANNER_MAX_SPECS`, so `_append_unfiltered_twins()` breaks on
  `len(out) >= max_specs` before appending any twin, and at least one of them
  resolved to a real planner filter. (The planner itself caps the plan at
  `max_specs` — `capped = tuple(planned_specs[:max_specs])` in
  `src/search/planner.py` — so "more specs than the cap" never reaches
  `resolve_specs()`.) D9 nearly retires broaden; it is kept, not deleted, because
  it still covers the truncated case at no cost otherwise.
  **Second consequence — the incidental embedding retry is gone, deliberately.**
  When the embedding call fails, `_embed_queries()` returns `[]` on
  `EMBEDDING_FAILURE_EXCEPTIONS` and `_run_passes()` runs no vector pass; today
  the broaden re-calls `embed`, which could succeed after a transient outage.
  Under D9 the broadened keys equal pass 1's, so that second call is skipped.
  Retrying a transient embedding failure is the job of the `@retry` on
  `EmbeddingClient._embed_batch()`, which `EmbeddingClient.embed()` calls
  (`src/common/embeddings.py`), not of a recall
  mechanism that retried by accident; R6 is exact with that stated.
- **D10 — deploy is operational, not code scope.** After the human merges, the
  maintainer redeploys the published image; see *Deploy note*.
- **D11 — `tag_ids: []` is rejected on both surfaces; the SPA stops sending it.**
  *(Taken at spec gate round 1, replacing an MCP-only rule; presented for the
  human's approval with this spec.)* An explicitly present, empty `tag_ids`
  is rejected on MCP **and** HTTP, and the SPA omits `tag_ids` from the request
  body when no tag is chosen (*Boundary validation*, "SPA request body").
  *Why:* fail-closed boundary, consistent with the human's D3 decision to reject
  malformed filters. `POST /api/search` and `/api/search/stream` are not
  SPA-only: they sit behind `require_api_scope` (`src/search/api.py`,
  `src/search/deps.py`) and README.md / `docs/configuration.md` describe API
  keys as the credential of programmatic callers. A programmatic multi-tenant
  caller whose tenant-tag lookup yields `[]` would otherwise get an unscoped
  200 over HTTP — exactly the Origin's failure, on the surface the old rule left
  open. The only reason HTTP accepted `[]` was that the SPA always sends it;
  changing the SPA removes that constraint at its source instead of keeping a
  fail-open contract to suit one client.

## Leak inventory

Every path where `ui_filters` can be dropped or loosened. Anchors are
`file — symbol`; all grep-verified on `86ab49f`.

| # | Tools | Site | Mechanism | Verdict |
|---|---|---|---|---|
| L1 | semantic_search, deep_search, web | `src/search/retriever.py` — `_append_unfiltered_twins()`, enabled by `resolve_specs(max_specs=…)` from `src/search/core.py` — `SearchCore._retrieve_phase()` | `replace(spec, filters=_EMPTY_FILTERS)` | **Leaks.** `raw_rag_plan()` (`src/search/refinement.py`) yields one semantic + one keyword spec with empty guesses, so every filtered `semantic_search` gets two unfiltered twins |
| L2 | same | `src/search/core.py` — `SearchCore._retrieve_with_broaden()` | `resolve_specs(broaden_plan(plan), facets, ui_filters=None, …)` | **Leaks** whenever pass 1 is empty (scope with no matching chunks; embedding outage + no in-scope FTS hit) |
| L3 | deep_search, web | `src/search/core.py` — `SearchCore._refine()` | `resolve_specs(replan_outcome, …, max_specs=…)` re-adds twins | **Leaks** on every refinement pass |
| L4 | all three | `src/search/retriever.py` — `_make_safety_net_spec()` / `_broad_semantic_base()` | base is `_EMPTY_FILTERS` but passes through `_intersect(…, ui_filters)` | **Not a leak.** Only its twin (L1) leaks. Not a fix site |
| L5 | all | `src/search/retriever.py` — `_resolve_one_spec()` / `_intersect()` | dates narrow; caller correspondent/doctype override; tags union (AND) | Narrows correctly |
| L6 | MCP all, HTTP | `src/search/wire/search.py` — `FilterRequest` (Pydantic default `extra="ignore"`), via `src/search/mcp_server.py` — `_to_search_filters()` | `{"tag_id": N}`, `{"tags": [N]}`, `{"tag_ids": []}` → unscoped search, no error | **Fail-open boundary** |
| L7 | all | `src/store/reader/_filters.py` — `_exclusive_upper_bound()` | malformed `date_to` → upper bound silently omitted; `date_from` never validated | **Fail-open dates** (caller input) |
| L8 | keyword_search | `src/search/core.py` — `SearchCore.keyword_search()` → `keyword_document_search()` (`src/store/reader/_ranked.py`) / `list_documents()` (`_browse.py`, via `build_browse_where()` → `build_filters()`) | none | Clean |
| L9 | fetch_documents | `SearchCore.fetch_documents()` → `assemble_fetched()` (`src/search/fetch.py`) | no filters argument; any id fetchable | Has no scope to drop; out of scope (see Rejected) |
| L10 | deep_search, web | `SearchCore._cache_key()` → `build_cache_key(filters=ui_filters, …)` (`src/search/cache.py`), store from `get_search_result_cache()` | keyed on the caller filters | Clean; in-process, so a restart clears pre-fix entries |

## Design

### Choke point (D2)

- `Retriever.retrieve(specs, *, scope: SearchFilters | None)` — `scope` is a
  **required keyword argument with no default**, so no call site can omit it by
  accident; a deliberate `scope=None` means "no caller scope".
- `Retriever._run_passes()` computes, per spec, `_intersect(spec.filters, scope)`
  and passes that to `StoreReader.vector_search()` / `keyword_search()`.
  `_intersect()` already lives in `retriever.py` and is idempotent (later/earlier
  date of equal bounds, caller value wins, `_union_ids()` de-duplicates), so
  applying it to an already-intersected spec changes nothing. A unit test pins
  idempotence.
- Call sites to update (all grep-verified): `src/search/core.py` —
  `_retrieve_with_broaden()` (×2) and `_refine()`; `src/search/api.py` builds the
  `Retriever` (constructor unchanged). Tests calling `retrieve(specs)` gain
  `scope=None` (about 28 call sites): `tests/unit/search/test_retriever_multispec.py`,
  `tests/unit/search/test_retriever.py`,
  `tests/integration/test_salary_april_regression.py`. (`tests/helpers/search.py`
  and `tests/e2e/test_index_then_search.py` only construct a `Retriever`.)
- `SearchCore._retrieve_with_broaden()` gains a `ui_filters` parameter (today it
  has none) and passes it as `scope` to both `retrieve` calls; `_refine()`
  already receives `ui_filters`.
- **§5.8 fix, in this PR.** `_retrieve_with_broaden()` today returns the 3-tuple
  `tuple[list[RetrievedChunk], RetrievalSignal, bool]`, unpacked positionally by
  its one caller, `_retrieve_phase()` (`chunks, signal, broadened = …`). This
  change touches the function and adds a third return branch (D9), so per the
  CODE_GUIDELINES preamble ("the divergence is fixed in the PR that next touches
  it") it is fixed here: the return becomes a new module-private frozen
  dataclass `_BroadenOutcome` (`chunks: list[RetrievedChunk]`,
  `signal: RetrievalSignal`, `broadened: bool`), declared in
  `src/search/core.py` beside `_RetrievalPhaseResult` with the same
  `@dataclass(frozen=True, slots=True)` decorator. A dataclass, not a pair:
  the pair `(retrieve() result, broadened)` would nest a tuple inside a tuple
  and still be unpacked positionally; `_RetrievalPhaseResult` is the module's
  own precedent for exactly this.

### Site fixes

- **L1 / L3 — twins keep the caller scope.** `_append_unfiltered_twins()` takes
  `ui_filters` from `resolve_specs()`; a twin's filters become
  `_intersect(_EMPTY_FILTERS, ui_filters)` — planner guesses stripped, caller
  scope kept, normalised by `_union_ids()` so `_retrieval_key()` dedup catches a
  twin identical to its original. For `semantic_search` both twins dedup away;
  for a planner spec with guesses plus a caller scope the twin is
  "caller scope only". A spec whose only filters are the caller scope yields a
  twin equal to itself, which the existing dedup drops — no new predicate is
  needed. With `ui_filters=None` behaviour is unchanged (R6).
- **L2 — broaden keeps the caller scope.** `_retrieve_with_broaden()` resolves
  `broaden_plan(plan)` with `ui_filters=ui_filters`, not `None`.
- **D9 — skip the identical broaden.** Compare the de-duplicated **set** of
  `_spec_search_key()` (`src/search/core.py`) over pass-1 specs and broadened
  specs; `_specs_equal()` is positional and length-sensitive, and pass 1 carries
  twins and the date safety net that the broaden resolve (no `query`, no
  `max_specs`) does not, so it cannot be reused as is. The skip compares
  *searches run*: if every broadened search key is already in pass 1's key set,
  the broaden would add nothing. **Return value of the skip branch:**
  `_BroadenOutcome(chunks=[], signal=<pass-1 signal>, broadened=False)`. Consumers: `_retrieve_phase()` writes `broadened` into the
  `retrieve` trace detail; the empty `chunks` reach the existing
  `reason="empty_retrieval"` no-match in `_answer_uncached()` exactly as an
  empty broaden does today.

### Docstrings that are wrong today (fixed in the same diff)

`SearchCore.answer()` ("authoritative and bypass free-text filter resolution"),
`SearchCore.retrieve()` ("authoritative when set"), `_retrieve_with_broaden()`
("a UI-set filter … does not survive the broaden"), `_retrieve_phase()` (twins
as "a bad filter can never silently exclude the answer"), `resolve_specs()`
(`query` / `max_specs` args describing the broadened pass as dropping all
filters), `_append_unfiltered_twins()`, `FilterRequest` ("Extra keys are
ignored"), mcp_server `_to_search_filters()` ("Unknown keys are ignored").

## Boundary validation (D3)

All on `FilterRequest` (`src/search/wire/search.py`), the single parse for both
surfaces (MCP via `_to_search_filters()`, HTTP via `SearchRequest.filters`), so
every check holds identically on MCP and HTTP.

| Check | HTTP | MCP | Evidence the SPA is unaffected |
|---|---|---|---|
| Unknown key → reject (`model_config = ConfigDict(extra="forbid")`) | yes | yes | The SPA sends exactly the five known keys: `paramsToFilters()` (`web/src/lib/parseSearchParams.ts`) builds them, `web/src/features/search/useStreamingSearch.ts` posts `{ query, filters }` verbatim |
| `date_from` / `date_to` not a valid ISO date → reject | yes | yes | SPA dates come from native `type="date"` inputs (`web/src/components/patterns/FilterControls/FilterControls.tsx`), always `YYYY-MM-DD` |
| Explicit `tag_ids: []` → reject | yes | yes | Today the SPA *always* sends `tag_ids`, `[]` when no tag is chosen (`paramsToFilters()` always sets it). The SPA change below omits it when empty, so an untagged web search sends no `tag_ids` key (D11) |

- **Date rule.** A value is accepted only when `normalise_iso_date()`
  (`src/search/dates.py`) returns a date **and** the whole string parses with
  `datetime.fromisoformat()`; it is stored as that `YYYY-MM-DD`. Both checks are
  needed: `normalise_iso_date()` alone validates only the first ten characters
  (`"2025-04-25junk"` passes), and `fromisoformat()` alone accepts compact and
  week forms (`"20250425"`) the store's lexical comparison cannot use. Anything
  else raises. `date_from > date_to` is not rejected: it
  narrows to nothing, which cannot leak. `_exclusive_upper_bound()` keeps its
  tolerance — planner dates are already validated in `_resolve_dates()`, and
  caller dates can no longer reach it malformed.
- **Empty tag list (both surfaces, D11)** is a `model_validator(mode="after")` on
  `FilterRequest`: `"tag_ids" in self.model_fields_set and not self.tag_ids`
  raises. `model_fields_set` is what tells an explicit `[]` from an omitted key
  (`tag_ids` keeps its `default_factory=list`); `src/search/wire/api_keys.py`
  already uses `model_fields_set` the same way. `filters` omitted, `None` or `{}`
  still means "no filters" — an empty object names no constraint, so nothing is
  dropped.
- **SPA request body (D11).** `paramsToFilters()`
  (`web/src/lib/parseSearchParams.ts`) is **not** changed: its `FilterRequest`
  is UI state, and `FilterControls`, `ActiveFiltersStrip` and
  `features/search/filters.ts` read `filters.tag_ids` as a required array. The
  omission happens where the wire body is built. Both senders today do
  `JSON.stringify(body)` on a `SearchRequest`: `search()`
  (`web/src/api/client/search.ts`, `POST /api/search`, used by `MatchCard` via
  `useSearch`) and `streamSearch()` (`web/src/api/client/searchStream.ts`,
  `POST /api/search/stream`, used by `useStreamingSearch`). One new exported
  function in `web/src/api/client/search.ts` — `toSearchRequestBody(body:
  SearchRequest): string` — serialises the body with `filters.tag_ids` removed
  when it is empty; both senders call it instead of `JSON.stringify(body)`.
  `searchStream.ts` imports it from `./search` (ESLint boundaries allow `api` →
  `api`; its "Allowed deps" header gains `search`). `FilterRequest.tag_ids`
  stays required in `web/src/api/types/search.ts`; the backend field already
  defaults to `[]`, so an absent key is valid on the wire.
- **Error contract.** A rejected filter surfaces to the caller as a clear
  message naming the offending key or value — never the sanitised
  "search failed — see server logs". Today `_run_search_tool()` converts filters
  *inside* its outer-boundary `try`, which swallows a validation error.
  Conversion moves into `_dispatch()` (mcp_server), **before** `_run_tool()` —
  as `keyword_search` already converts before `_run_tool()`, and as
  `fetch_documents` validates "BEFORE dispatch" — so a rejected filter never
  resolves the core, checks the spend quota or takes the semaphore;
  `_run_search_tool()` then receives `SearchFilters | None`. `_run_tool()` has
  no catch-all of its own (read), so the error reaches the client as raised.
  Pydantic 2's `ValidationError` subclasses `ValueError`; it is caught as `exc`
  and re-raised with `raise ValueError(<field name + Pydantic's message>) from exc`
  (CODE_GUIDELINES §6.3 — the message carries no secret or internal state, so the
  traceback is kept; `from None` is reserved for the sanitised path). HTTP gets
  FastAPI's standard 422.
- **Intended behaviour change:** a hand-edited web URL such as `?from=junk` now
  returns 422 instead of a silently unbounded search.

## Result shape change (D4)

- `IndexedDocument` and `DocumentSummary` (`src/store/models.py`) gain a
  required `tag_ids: tuple[int, ...]` — the raw ids from the row's `tag_ids` JSON
  (already parsed by `_parse_tag_ids()` in `get_documents()`,
  `src/store/reader/_lookups.py`, and in `list_documents()`,
  `src/store/reader/_browse.py`), not the name-resolved list, so a tag missing
  from the taxonomy cannot hide an id. Required, not defaulted, so a new
  construction site cannot silently report "no tags". Construction sites
  (`rg -c "\bIndexedDocument\(|\bDocumentSummary\("`): `IndexedDocument` —
  `_lookups.py`, `tests/helpers/factories/_search.py`,
  `tests/unit/store/test_schema.py`; `DocumentSummary` — `_browse.py`,
  `_lookups.py`, `tests/unit/store/test_models.py`,
  `tests/unit/search/test_fetch.py`, `test_mcp_server_fetch.py`,
  `test_mcp_server_keyword_search.py`, `test_document_routes.py`,
  `tests/unit/search/wire/test_library.py`.
- `SourceDocument` (`src/search/models.py`) gains
  `tag_ids: tuple[int, ...] | None = None` **after** `relevance_tier` (the last,
  defaulted field — a non-default field after it is a `TypeError`), filled in
  `_build_source()` (`src/search/sources.py`) from the indexed row, or `None`
  when the row was pruned mid-request (that function's documented race).
  `None`, not `()`: `()` means "this document has no tags", which for a scoped
  search would read as a leak; a pruned row's tags are *unknown* — the genuine
  absence CODE_GUIDELINES §5.4 reserves `None` for — and `_build_source()`
  already sets `title`, `correspondent`, `document_type` and `created` to `None`
  in that case. The D4 receipt treats a `null` `tag_ids` as unverifiable, not
  failed.
  `semantic_search` and `deep_search` serialise `SearchResult` with
  `dataclasses.asdict` in `_serialise_result()`, so both carry it with no further
  change.
- MCP `keyword_search` adds `"tag_ids": list(hit.document.tag_ids)` to each
  document object.
- HTTP response models (`SourceDocumentResponse`, the library summary in
  `src/search/wire/library.py`) are built field by field and stay unchanged: no
  web consumer needs the ids, and the SPA's wire types mirror the backend models
  exactly (`web/src/api/types/search.ts` header), so adding them there is a TS
  change with no user.

## Tests & verification

Lesson applied (`review-lessons.md`, "A mocked test seam does not guard the
real logic"): the invariant is proven against a **real SQLite store**, not a
spied mock.

### Two-tenant fixture

`seed_pipeline_document()` (`tests/integration/conftest.py`) hardcodes
`tag_ids=()`; it gains a `tag_ids: tuple[int, ...] = ()` keyword. A new
integration module (proposed `tests/integration/test_caller_scope.py`) seeds a
`StoreWriter` with tenant A (placeholder tag `TAG_A`) and tenant B (`TAG_B`),
both containing the query term, B's chunks on the query axis (`AXIS_BOILER`) and
A's off it (`AXIS_OTHER`) — so any unscoped pass ranks B *first* and a leak
cannot hide below the top-K cut. Assertion everywhere: **every returned
`document_id` carries the scope tag** (read back from the store, not from the
new `tag_ids` field, so the check does not depend on the code under test).

### One forcing input per leak site

| Leak | Input | Must hold |
|---|---|---|
| L1 | `SearchCore.retrieve()` (the `semantic_search` path) scoped to `TAG_A` | only A documents |
| L1 via L4 | same, dated query ("… in 2024") so the date safety net fires and is twinned | only A documents |
| L2 (empty scope) | scope to a tag no document carries | empty sources, no A/B leak |
| L2 (outage) | embedding client raises a member of `EMBEDDING_FAILURE_EXCEPTIONS` (`src/common/embeddings.py`); query term present only in B's text, so the scoped FTS pass is empty | empty sources |
| L3 | `SearchCore.answer()` scoped to `TAG_A`, `ScriptedLLMClient` (`tests/helpers/llm.py`) with `needs_more_response_json()` then `answered_response_json()` and a `replan_response` | only A documents in the final sources |
| L8 | `keyword_search` scoped to `TAG_A`, with and without a query | only A documents |
| R6 | `SearchCore.retrieve()` / `answer()` with no filters | B and A both reachable, as today |

### Defence-in-depth means per-layer tests

The choke point catches every site, so reverting one *site* fix alone leaves the
end-to-end tests green. Each layer therefore has its own pin:

- **Choke point:** a `Retriever` given a spec with *no* filters and
  `scope=<TAG_A filters>` calls the store with the scope — asserted over
  `call_args_list` for every vector and keyword call, with a second test passing
  a **different** scope (`TAG_B`) so the value is pinned, not a literal.
- **`_intersect()` idempotence:** `_intersect(_intersect(f, s), s) == _intersect(f, s)`
  for dates, ids and duplicate tag ids.
- **L1/L3 sites:** `resolve_specs(…, ui_filters=<scope>, max_specs=…)` — every
  twin's filters equal `_intersect(_EMPTY_FILTERS, scope)`; for `raw_rag_plan()`
  with a scope, no twin is appended. Existing twin tests in
  `tests/unit/search/test_resolve_specs.py` (`ui_filters=None`) stay green
  unchanged (R2/R6).
- **L2 site:** `_retrieve_with_broaden()` resolves the broadened plan with the
  caller scope — observed on the specs passed to the second `retrieve()` call
  (a spy on `Retriever.retrieve`, reading its `specs` argument, not the store
  call, which the choke point would scope anyway). **L3 path:** `_refine()`'s
  re-plan specs carry the scope (it already passes `ui_filters`; pinned so a
  later edit cannot drop it). Observation point: the `refine` phase detail —
  `new_specs[*].filters.tag_ids`, emitted by `_emit_refine_marker()` from
  `_spec_detail_for_resolved(new_specs)` (`src/search/core.py`). The store
  mock's `call_args` cannot be the pin: the choke point re-applies the scope
  there, so it stays green under mutation (4).
- **D9:** a scoped `semantic_search` with an empty pass 1 embeds once, makes no
  second retrieve, and reports `broadened: false`; a plan whose twins were cut —
  at least as many planner specs as `SEARCH_PLANNER_MAX_SPECS`, each resolving to
  a real filter (a facet set containing the guessed name) — still broadens.
- **End to end:** the forcing-input table above, which is red on `86ab49f`.

### Existing tests

- `tests/unit/search/test_core_sources.py` — `TestUiFilters.test_ui_filters_are_passed_to_vector_search`
  passes for the wrong reason: `_embedding_client()` returns one vector for two
  semantic specs (original + twin), `zip` in `Retriever._run_passes()` drops the
  twin, and the test reads only `call_args`. Fix: `side_effect` sized per text
  (as `make_axis_embedding_client()`) and assert over every call in
  `call_args_list`; it must be run red on `86ab49f` before it counts.
- Tests encoding the old drop are **inverted or re-targeted, never deleted**
  (GATES: a red gate is not greened by deletion):
  `tests/unit/search/test_core.py` — `test_broaden_retry_runs_before_giving_up`
  and `tests/unit/search/test_core_trace.py` —
  `test_retrieve_detail_marks_broadened_on_second_pass` are re-targeted to a
  twin-capped setup — at least as many planner specs as
  `SEARCH_PLANNER_MAX_SPECS`, each resolving to a real filter — the only case
  where broaden still differs from pass 1 under D9. Both use `make_facet_set()`
  today, whose empty taxonomy drops their `correspondent` guess, so their spec
  resolves to `_EMPTY_FILTERS` and has no twin to cap; the re-target therefore
  also needs a facet set that contains the guessed correspondent.
  `test_retrieve_detail_reports_counts_and_not_broadened` is checked.
- Every `retrieve(specs)` test call gains `scope=None`.

### Boundary tests

- `FilterRequest` unit tests: `{"tag_ids": []}` rejected, `{}` and omitted
  `tag_ids` accepted as "no tag constraint".
- MCP (`tests/unit/search/test_mcp_server.py`,
  `test_mcp_server_keyword_search.py`): for `semantic_search`, `deep_search`,
  `keyword_search` — `{"tag_id": N}`, `{"tags": [N]}`, `{"tag_ids": []}`,
  `date_from`/`date_to` of `"junk"`, `"2025-04-25junk"`, `"20250425"` each
  rejected with a message naming the key, and **not** the sanitised
  "search failed" text; `"2025-04-25T00:00:00+00:00"` accepted and normalised;
  `{}` and omitted filters mean no filters.
- HTTP (`/api/search` and `/api/search/stream`): unknown key → 422; bad date →
  422; `tag_ids: []` → 422; filters without a `tag_ids` key → 200.
- SPA (vitest, beside the existing `web/src/api/client.test.ts` and
  `web/src/api/client/searchStream.test.ts`): `toSearchRequestBody()` drops an
  empty `tag_ids` and keeps a non-empty one; `search()` and `streamSearch()`
  each send a body with no `tag_ids` key for an untagged search, asserted on the
  mocked `fetch` body.
- Result shape: `tag_ids` present on `semantic_search` / `deep_search` sources
  and `keyword_search` documents; `None` (JSON `null`) for a pruned row.

### Mutations — to be run, not yet run

Each must turn a test red; recorded only after it has been run: (1) choke point removed from `_run_passes()`; (2) twin
filters back to `_EMPTY_FILTERS`; (3) broaden back to `ui_filters=None`;
(4) `_refine()` resolving with `ui_filters=None` (the L3 unit test reading the
`refine` phase detail's `new_specs[*].filters` must go red); (5) D9 skip removed; (6) `extra="forbid"` removed; (7) date validator
removed; (8) the `FilterRequest` empty-`tag_ids` validator removed (MCP and HTTP tests
go red); (9) filter conversion moved back
inside the `try`; (10) choke point **and** each site reverted together → the
end-to-end table goes red; (11) `toSearchRequestBody()` returning
`JSON.stringify(body)` unchanged → the SPA tests go red.

### Gates

`.claude/GATES.md` — `python-tests`, `python-types`, `python-lint`,
`python-security` must be green, and — since D11 changes `web/src/api/client/`
— the five `web-*` gates too.

## Docs (D8)

`docs/search-pipeline.md` (human doc; edit authorised by the human):
"Broaden-and-retry" — replace the "dropped too" sentence with the reversal and
its why; "UI filter intersection" — state that caller filters are a hard scope
re-applied at the retriever and that multiple `tag_ids` are ANDed; add the
missing description of recall twins (planner-only); update the flowchart node
"broaden: drop all filters" and the `retriever.py` row of the File Index. MCP
`instructions` and the three tool descriptions in `src/search/mcp_server.py`
gain one sentence each (D5, D6). The KB is updated by the push gate's
kb-updater.

## Deploy note (D10)

Not code scope. After the human merges, CI publishes the image; the maintainer
records the **currently running image digest** (the rollback target) and then
redeploys the search service from the published image. The restart also clears
the in-process result cache (L10), which may hold pre-fix answers.

## Rejected / deferred

- **Optional `filters` on `fetch_documents`** — deferred: new scope and one store
  lookup per id; callers already pin the ids they fetch from scoped search
  results, which now carry `tag_ids` to check against.
- **Planner metadata naming other tenants' taxonomy in `deep_search`** — residual,
  deferred. The planner sees the whole taxonomy (`build_planner_taxonomy_block()`,
  `src/search/prompts.py`) and `_serialise_result()` keeps `plan`, so a planner
  guess can name another tenant's correspondent. No documents leak; the result
  set is scoped.
- **Offering the fix to the upstream project** — a separate human decision; the
  fork carries the divergence in `retriever.py`, `core.py`, the wire model and
  the doc.
- **Any-of tag semantics** — new scope (a new filter field); AND stays (D6).
- **Rejecting empty `tag_ids` on MCP only, accepting `[]` on HTTP as "no tag
  constraint"** — the round-0 rule, rejected at spec gate round 1 (D11). Its
  only argument was that the SPA always sends `[]`; it left programmatic
  API-key callers of `/api/search` fail-open on the Origin's exact scenario.
  Changing the SPA's request builder removes the constraint instead.
- **Omitting empty `tag_ids` in `paramsToFilters()` / making
  `FilterRequest.tag_ids` optional in TS** — rejected: that `FilterRequest` is
  UI state read as a required array by `FilterControls`,
  `ActiveFiltersStrip` and `features/search/filters.ts`; the omission belongs
  at the wire serialiser (`toSearchRequestBody()`), not in the UI model.
- Also rejected, with reasons where decided: per-site fix without a choke point
  (D2), old semantics kept for the web UI (D7).

## Risks

- **Recall drop for filtered callers** — intended. A wrong-tag call now returns
  empty instead of other tenants' documents; a caller that treats zero results
  as proof of absence should first check the tag's document count with
  `list_filters`.
- **Multi-tag callers see fewer results** (D6) — previously masked by twins and
  broaden.
- **Broaden-and-retry nearly retired** (D9 consequence) — reachable only when
  the twin cap truncated; planner-guess recovery now relies on the twins.
- **Clients sending unknown keys, non-ISO dates or an empty `tag_ids` now fail
  loudly** — intended; the SPA is unaffected once it omits an empty `tag_ids`
  (D11). The SPA ships in the same image (the `Dockerfile` frontend stage builds
  `web/dist`), so backend and SPA deploy together; only a browser tab still
  running the pre-deploy bundle 422s an untagged search, until it reloads.
- **Upstream merge conflicts** in touched files; the choke point stops a merge
  silently reopening the leak.
- **Over-ceiling files.** `retriever.py` (945 lines) and `core.py` (2133) already
  exceed the 500-line ceiling; touched functions stay within §3.1.

## Verification evidence (re-run at spec gate round 1, on `994f3b3`)

`git diff --stat 86ab49f 994f3b3 -- src tests web` is empty, so every anchor
verified on `86ab49f` above still holds. Each command below runs as written with
ripgrep (`|` alternation), from the repository root; the trailing comment is
what it printed. Kept in a fenced block, not a table, so no Markdown escaping
alters the command.

```sh
rg -c "def |_EMPTY_FILTERS" src/search/retriever.py                          # 28
rg -c "resolve_specs|_retrieve_with_broaden|ui_filters=None" src/search/core.py  # 10
rg -c "filters|FilterRequest" src/search/mcp_server.py                       # 49 (plus a read of _run_tool())
rg -n "date_from|tag_ids" web/src | wc -l                                    # 152
rg -c 'type="date"' web/src/components/patterns/FilterControls/FilterControls.tsx  # 2
rg -n "\.retrieve\(" tests src | wc -l                                       # 46
rg -c "retriever\.retrieve\(" tests                                          # multispec 7, test_retriever 19, salary_april 1 = 27
rg -n "broaden|twin|_EMPTY_FILTERS|ui_filters=None" tests | wc -l            # 99
rg -c "\bIndexedDocument\(|\bDocumentSummary\(|\bSourceDocument\(" tests src  # 22 lines across 12 files
rg -c "JSON.stringify\(body\)" web/src/api/client/search.ts web/src/api/client/searchStream.ts  # 1 and 1 (D11's two senders)
rg -c "model_fields_set" src/search/wire/api_keys.py                         # 2 (precedent for the D11 validator)
rg -c "require_api_scope" src/search/api.py                                  # 3 (search routes are API-key callable)
rg -c "capped = tuple\(planned_specs\[:max_specs\]\)" src/search/planner.py  # 1 (planner cap, D9)
rg -c "_BroadenOutcome|toSearchRequestBody" src web/src                      # no output, exit 1: both new names are free
```

`python -c 'datetime.fromisoformat(…)'` in the repo venv: `2025-04-25` ok,
`2025-04-25T00:00:00+00:00` ok, `2025-04-25junk` rejected, `20250425`
**accepted**. `pydantic.VERSION` → `2.13.5`.

## Review rounds

| Round | Scope | Verdict | Outcome |
|---|---|---|---|
| 1 | full | NO-SHIP 2 major 7 minor | resolved in the commit `docs(spec): resolve spec gate round 1` |

Round 1 lesson-candidates:

- Recorded verification commands must be copy-paste reproducible in the named
  tool — a grep-BRE `\|` pasted into an `rg` record yields zero matches and a
  record nobody can re-run.
- A boundary decision justified by "the only client does X" must enumerate the
  clients first; any `/api/*` endpoint behind `require_api_scope` has
  programmatic API-key callers, not just the SPA.
- A skip/short-circuit that avoids "pointless repeated work" must list the
  incidental retries it also removes (here: the broaden's second embedding call).
