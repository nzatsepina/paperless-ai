# Decisions

<!-- Claude-maintained, append-only. Entries are never edited or deleted; a
reversal gets a new dated entry that names what it supersedes. Every entry
starts with a heading of the form:

    ## YYYY-MM-DD — <short decision title>

kb-context.sh extracts titles by that pattern — this format and that script
are a coupled contract; change them only together, in the CLAUDE repo.

Entry body shape (Spec/Affects/Supersedes lines only when applicable):

    **Decision:** <what was decided>
    **Why:** <the reason — trade-offs considered>
    **Spec:** .claude/specs/<file>.md
    **Affects:** <KB doc paths this decision touches, comma-separated>
    **Supersedes:** <date/title of the earlier entry, only if a reversal>

Delete nothing above when appending; append new entries at the end of file. -->

## 2026-07-15 — Adopt GPT-5.6, refresh reasoning efforts, add Flex tier

**Decision:** OpenAI defaults move to gpt-5.6-luna/terra (Sol selectable,
never default); reasoning-effort choices become the live-verified {none, low,
medium, high, xhigh}, with stored "minimal" coerced to "none"; OCR +
classifier run on the Flex service tier behind `OPENAI_FLEX_TIER` (default
on) with retry-until-done capacity-429 semantics; every OpenAI call names its
`service_tier` explicitly. Batch API, the Responses API migration, and any
embedding change are rejected for now.
**Why:** "max" is excluded from the reasoning-effort set — the docs list it
but the live API rejects it. Batch/Responses/embedding changes were weighed
and rejected — see spec sections D3/D10 for the trade-offs considered.
**Spec:** `.claude/specs/20260715-flex-and-56-models.md`
**Affects:** common/config, common/llm, ocr, classifier, search, web settings

## 2026-07-15 — Remove GATES.md's fulfilled reconciliation note

**Decision:** Delete the three-line note in `GATES.md` stating gates 9/10 were not yet
documented in `TESTING.md` — the same commit documents them there, fulfilling the note.
**Why:** The note was a self-scheduled reminder, not a gate; once fulfilled it would lie.
No gate row was removed or edited — the 10-gate table is untouched. Approved by: human
(operator, 2026-07-15), per the gate's removal-needs-a-record rule.
**Affects:** `.claude/GATES.md`, `.claude/docs/TESTING.md`

## 2026-07-15 — Migrate GATES.md to the canonical stanza grammar

**Decision:** Rewrite `GATES.md` from the ad-hoc table format (authored earlier today)
into the canonical stanza grammar from the config repo's `templates/kb/GATES.md` —
`### gate: <id>` stanzas with kind/why/added/mandated-by-human fields and fenced
commands, plus the template's standard anti-cheat and change-control sections.
**Why:** The kb-gate's push-time validator parses only the canonical grammar; the table
format read as "no gates declared" and blocked every push. All ten commands are
unchanged — this is a format migration, not a gate change. Approved by: human
(operator, 2026-07-15 — "approved", in response to the explicit rewrite proposal).
**Affects:** `.claude/GATES.md`

## 2026-07-15 — Correct the LLM-budget claim in CODE_GUIDELINES.md

**Decision:** Amend §14.3 and §10.6 — the "three LLM calls per query" ceiling becomes the
real formula `(2 + j) × (1 + SEARCH_MAX_REFINEMENTS)`, six at shipped defaults, citing
`search/core._max_llm_calls`.
**Why:** The judge gate plus the refinement loop made "three" false long before this
branch; the corrected code docstrings cross-referenced §14.3 and sent readers to the lie.
Human-owned law, edited only on explicit operator instruction: "You are allowed to edit
the CODE_GUIDELINES.md to fix this" (2026-07-15).
**Affects:** `CODE_GUIDELINES.md` §14.3, §10.6

## 2026-07-21 — Skip AI OCR on born-digital PDFs
**Decision:** A deterministic poppler gate in the OCR worker skips vision-OCR for PDFs that
are already born-digital — detected on the *original* file (`pdftotext` per-page text yield +
`pdfimages` largest-image page-coverage + `pdffonts` `GlyphLessFont`) — while AI-OCRing scans,
images and scanner-produced searchable scans. Default on, whole-document, three settings-UI
config keys (`OCR_SKIP_BORN_DIGITAL`, `OCR_BORN_DIGITAL_MIN_CHARS`, `OCR_BORN_DIGITAL_TAG_ID`),
fail-safe to OCR on any doubt. A skip is a tags-only `PRE→POST` PATCH (content untouched),
breaker-neutral; a permanent write failure quarantines.
**Why:** The daemon re-OCR'd every tagged document, burning vision tokens on born-digital PDFs
that already carry a perfect text layer. Coverage uses the largest image (not the sum) because
a clipped-sum variant flips an operator-confirmed born-digital doc (image-heavy page) to OCR;
`GlyphLessFont` closes the Tesseract-family searchable-scan subclass. Every failure mode is
quality-only (falls through to OCR), never data loss — which is what makes default-on safe.
Empirically validated 9/9 against real documents on the operator's instance.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md
**Affects:** `docs/PIPELINES.md`, `docs/modules/ocr.md`, `docs/CONFIGURATION.md`

## 2026-08-15 — Born-digital gate: text floor default 1, blank pages exempt
**Decision:** `OCR_BORN_DIGITAL_MIN_CHARS` default 50 → 1, and the per-page text floor now applies
only to a page that also carries a raster (`pdfimages` row, ppi 0 included) — a textless, imageless
page is a blank verso, a divider or (rarely) a vector-outline page — not a scan. Whole-document rule, `COVERAGE`, tags-only skip and the
exposed key are unchanged.
**Why:** The first real booklet (prod doc 1525, 59 pages) went through 59 vision calls because its
cover page held 44 chars + a logo — one under the shipped floor. The 9-doc calibration set had no
sparse born-digital page, so 50 sat in a gap with no low-side data and contradicted D4's own "has a
text layer vs none" semantics; a blank page is unfixable by tuning at any floor ≥ 1. Rejected:
intermediate defaults (arbitrary, fail folio-only versos), a new sparse-page image threshold (no
data), per-page routing (D8 v2 — its own spec; 0 mixed docs in the census). Operator: "so should
we do your initial recommendation 1 and 2?" → "do it. commit directly to main, small change, then
push." (2026-08-15).
Follow-ups landed in the same push on explicit operator instruction ("fix the human doc. also fix
the follow-up defect found", 2026-08-15): the human doc `docs/ocr-pipeline.md` corrected (default,
raster condition, honest residual — human-owned prose, edited only on that instruction), and
`_parse_max_coverage` now reads the ppi columns from the right so inline images (`[inline]`, one
token) no longer fail the whole gate closed.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md (*Amendments*, 2026-08-15)
**Affects:** `src/ocr/born_digital.py`, `src/common/config/_settings.py`, `web/src/features/settings/fieldModel/sections.ts` (hint copy), `docs/ocr-pipeline.md`

## 2026-08-17 — Born-digital gate: a mangled text layer routes to OCR
**Decision:** the gate gains a fourth signal from the `pdftotext` output it already holds — a count of
`[A-Za-z];[A-Za-z]` (a semicolon glued between two letters); any hit → `mangled-text-layer`,
skip=False, logged as `mangled_hits` on every decision. Presence signals, thresholds and the
tags-only skip are unchanged; spec non-goal 3 is narrowed by exactly this one structural tell.
**Why:** prod doc 1523 (an Outlook-for-Mac print-to-PDF, macOS Quartz PDFContext, Calibri/Aptos)
passed every presence signal and was skipped, keeping ngx content in which every `ti`/`tt`/`ft`/`ffi`
ligature had become `;`/`5`/`C`/`m` (`mee;ng`, `le5er`, `draC`, `omcer` in shape; the document's
words are private) — Quartz writes a `ToUnicode` that maps those ligature glyphs to single wrong
characters (CMap dump on the pristine original; poppler 26.03 reproduces it). Pre-gate the vision
path rasterised and was immune. Rejected: a `Producer` sniff (over-broad, producer-bound), a
`ToUnicode` collision parser (a CMap parser for one observed producer), a `5`-in-word second tell
(hex/serial false positives, no measured recall gain on n = 1), an LLM judge (D1). Known residuals
recorded in the spec: `tt`/`ft`/`ffi`-only or word-initial-`ti` mangling still skips, and the
documented `ti`→U+10019F (PUA; shown as `Ɵ` U+019F once truncated) variant is missed by the `;`
tell — detectable via a PUA-class tell, left unaddressed on n = 0; semicolon-delimited data,
minified CSS/JS and `;`-joined URLs over-OCR. The tell is checked last so scans keep their scan
reason. Count uses `finditer` (a `findall` list on the 32 MiB probe cap peaks ~500 MB RSS vs ~46 MB
— the D6 bomb budget). Census: 1 of 16 skips affected; verified on all 16 real originals after the
change (1523 → OCR, 15 unchanged). Operator: "Let's go with A. commit directly to main and push."
(2026-08-17). `docs/ocr-pipeline.md` (human doc) is NOT edited: the 2026-08-15 edit was "only on
that instruction", no standing licence exists, and this approval did not name the human doc — its
now-stale signal list ("three signals") is reported to the operator for a separate yes. Adversarial
review (Opus): R1 NO-SHIP on three majors — a verbatim line of the operator's private document in
the test fixture/spec/decision (redacted to synthetic examples; the unpushed commit rebuilt so no
history carries it), the `findall` amplification, an overstated "full recall" claim; R2 NO-SHIP on
one major — a human-doc edit justified by a "precedent" the cited entry itself disclaims (hunk
reverted, reported instead) — plus minors (reason precedence, a false "uppercase-only" residual,
inconsistent RSS multipliers, "one vision pass" understated on long documents); R3 NO-SHIP on one
major of the reviewer's own making — its R2 "`ti`→`O`, undetectable" residual was a us-ascii
archive flattening of `Ɵ` (U+019F), which is detectable — corrected to the real character and its
true status; R4 SHIP with two minors (the residual's font attribution and its extraction target
— U+10019F verbatim from `pdftotext`, not the truncated `Ɵ`; two KB row imprecisions), fixed
before push.
**Spec:** .claude/specs/20260721-born-digital-ocr-skip.md (*Amendments*, 2026-08-17)
**Affects:** `src/ocr/born_digital.py` (`docs/ocr-pipeline.md` stale pending operator instruction)


## 2026-09-06 — Cloudflare Access identity as a third auth path, tried first

Verified Cloudflare Access assertions (`Cf-Access-Jwt-Assertion`, JWKS-signature + issuer/audience/
expiry checked) now resolve a caller in `resolve_caller`, ahead of the session cookie and bearer
API key. A verified `email` claim resolves an EXISTING user (match-only; an unknown address is refused) with that account's OWN role, matched on
`email` — `validate_username` forbids `@`, so an address can never be a username) and behaves like a cookie session (`scopes=None`, role-bounded only). A valid assertion
with no `email` claim (the service-token/machine case, `common_name` instead) returns `None` and
falls through unchanged to the cookie/bearer paths — swallowing a machine caller here would discard
the API-key scope model and the `api_key_id` audit linkage. `SEARCH_ACCESS_TEAM_DOMAIN` /
`SEARCH_ACCESS_AUD` are environment-only and deliberately absent from `CONFIG_KEYS`: `PUT
/api/settings` must not be able to repoint who the app trusts. `access_config()` reads
`os.environ` directly rather than building `Settings`, so an unrelated missing required variable
(e.g. `PAPERLESS_TOKEN`) cannot break login. Both variables unset disables the branch entirely;
cookie and API-key auth are unchanged — the correct default for any deployment not sitting behind
Cloudflare Access. `PyJWT[crypto]` moved from a transitive to a declared dependency, since auth
must not depend on another package's dependency graph surviving a bump.

Separately, `GET /api/index/{status,activity,failed}` moved from `readonly`+`api` to admin-only —
a deliberate requirement change — daemon heartbeats, reconcile history and the failed-document
list are operational state rather than archive data, and administrators alone are to see them —
not a gate-driven test change.
**Affects:** `src/search/access_jwt.py`, `src/search/deps.py` (`resolve_caller`, `access_identity.access_user`),
`src/search/index_routes.py`, `pyproject.toml`

## 2026-09-07 — Human docs reconciled to the third auth path

The auth change landed with `CODE_GUIDELINES.md` §10.1 amended but every other human-facing
document still describing the pre-change system — `docs/search.md`'s RBAC table documented the
`/api/index/*` breaking change *backwards* (`Read-only+`, so an operator following it would mint a
credential that 403s), `DESIGN.md` §12.2 listed the Index nav link as visible to all authenticated
users, `README.md` counted "two kinds of credential", and `docs/configuration.md` did not mention
`SEARCH_ACCESS_TEAM_DOMAIN` / `SEARCH_ACCESS_AUD` at all. Claude does not edit the human tree
unasked and was explicitly asked to here, so the reconciliation is recorded rather than left as an
unexplained boundary crossing. (The instruction itself is not quoted: a public repository is the
wrong place to reproduce a person's words verbatim.) Files changed: `README.md`, `DESIGN.md` (§12.2, §13.5, §14.6),
`docs/search.md`, `docs/configuration.md`, `docs/deployment.md`, `docs/store.md`,
`docs/indexer.md`, `docs/architecture.md`, and two dead cross-references in `CODE_GUIDELINES.md`
§10.1 (a self-citation to a rule that does not exist, and a `§4.4` pointing at "Domain language
wins" rather than the web-redesign spec). The docs name the **product** — Cloudflare Access — because
the feature cannot be configured without it: the key-set path and the assertion header are
Cloudflare's, and a first pass that wrote only "an identity-aware reverse proxy" promised
vendor-agnostic support the code does not have, and misdescribed `SEARCH_ACCESS_TEAM_DOMAIN`
as the application's hostname rather than the Access team domain. An adversarial round caught
both. This repository is public and still names no *deployment* — no host, domain, tenant,
account, audience tag or topology.

`.claude/INDEX.md`'s freshness stamps cited a pre-amend commit that was not an ancestor of the
branch and would not have survived a push; repointed, along with the OPERATIONS row, which had
been edited in the same commit but left at an older stamp. **Do not cite a branch SHA in this
file while the branch can still be rewritten** — this entry did, twice, and a later rewrite
orphaned both citations. Cite the file and the fact instead.

Reasoning comments that described the *deployment* rather than the software were restated: a
public repository should not assert that one named role alone sees the logs, nor describe the
credential set of the particular installation it was written on. The first pass restated three of them and missed four more —
including the `index_routes.py` module docstring sixty lines above the comment it did fix — and
a following review round caught that while a `review-lessons.md` entry claiming the class was
eliminated was already committed. The round after *that* found another live instance in
`src/search/access_jwt.py`, again beside a record asserting the file was clean — three rounds,
the same false-completeness claim each time, because each sweep was a hand-written grep shaped to
the instances already known.

A mechanical gate was built to replace that judgement, and then removed — see the entry below.
The instances themselves were all corrected, and the standing lesson in
`.claude/memory/review-lessons.md` remains the control.

`src/search/index_routes.py`, `src/search/access_jwt.py`, `web/src/routes.test.tsx`,
`tests/integration/test_index_api.py`, `tests/unit/search/test_access_jwt.py`,
`tests/unit/search/test_access_identity.py` and `CODE_GUIDELINES.md` §10.1 now state the property
of the software. The `index_routes.py` *inline comment* previously said its deciding document was
unresolvable from this repository and now cites the spec added here; the module docstring above it
still cites the never-committed web-redesign spec, as most of this repository does — a
repo-wide convention left alone rather than changed on this branch.
**Spec:** `.claude/specs/20260906-verified-proxy-identity.md`
**Affects:** `README.md`, `DESIGN.md`, `CODE_GUIDELINES.md`, `docs/search.md`, `docs/configuration.md`, `docs/deployment.md`, `docs/store.md`, `docs/indexer.md`, `docs/architecture.md`, `.claude/INDEX.md`, `.claude/GATES.md`, `src/search/index_routes.py`, `src/search/access_jwt.py`, `web/src/routes.test.tsx`, `web/src/components/layout/BottomTabBar/BottomTabBar.stories.tsx`, `tests/integration/test_index_api.py`, `tests/unit/search/test_access_jwt.py`, `tests/unit/search/test_access_identity.py`, `tests/unit/common/test_config.py`


## 2026-09-07 — Remove the `no-deployment-prose` gate

**Provenance: human.** Instruction, verbatim: *"drop the whole thing then push and deploy. just
make sure that the drop is justified"*, following the question *"wait so are the gates even needed
if you added it ?"*. A human decision overrides the panel requirement for removing a gate
(`GATES.md`, "Changing gates"), so no panel was convened. The id is listed under `## Retired` and
can never be reused.

**What it was.** Added earlier the same day, monocratic, after the same class of leak — comments
and docstrings asserting facts about one installation rather than about the software — survived
three consecutive review rounds, twice beside a record claiming it had been swept. It grew a
second half (host-shaped tokens against an allowlist) after a fourth round found a live FQDN that
the phrasings-only version passed.

**Why removing it is right, not a retreat.**

1. *It was calibrated to one session's mistakes.* The phrase list held thirteen literal English
   strings, every one of them text written during the session that added the gate. A future
   instance of this class will not use those words. A check that only recognises the errors
   already made is overfitting, and it would have been carried by every future contributor.
2. *Almost everything it ever caught was already being caught.* Every phrasing hit was text the
   review rounds had flagged or would have flagged, and which was being deleted anyway. Exactly
   one finding was independent: a real FQDN in `src/search/mcp_server.py`, and that arrived with
   an upstream commit and names the upstream maintainer's own host, already public in the upstream
   repository. One independent catch does not carry a permanent gate.
3. *It never covered the class, and a partial gate on a "never do X" rule is worse than none.*
   Bare hostnames, IP literals, non-ASCII labels and every TLD outside a fixed set passed it. A
   private-range IP check was written and measured at seven false positives in this tree, across
   four files: the `10.0.0.0/8` CIDR example in `README.md`'s own `SEARCH_FORWARDED_ALLOW_IPS`
   row, the same literal in `tests/unit/common/test_config_search.py`, and fixture client
   addresses in `tests/unit/search/test_login_throttle.py` and
   `tests/unit/search/test_sessions_lifecycle.py`. Nothing separates a documentation example from
   a real host at that shape, so it cannot be checked mechanically here at all. Twice the gate was declared to cover the class while covering half, which is the
   *same* false-completeness defect it existed to prevent, one level up.
4. *It cost more than it returned.* Three of the six commits then on the branch were wholly gate
   work, and rounds 4, 5 and 6 each found defects in the gate itself — none found a defect in the
   auth change it was guarding.

**What replaces it.** Nothing mechanical, deliberately. `.claude/memory/review-lessons.md` carries
the lesson as a live control and now warns against the failure that sank the gate: sweep for the
*shape* — a sentence asserting something about one installation, its credentials, its hostnames or
its people — never for the words a previous round happened to use. The `gitleaks` pre-push scan and
the `secret-scanner` semantic tier are unaffected and still cover credentials, which was always the
higher-severity class.

**What is kept.** Every instance the gate found stays corrected: the restated comments and
docstrings across `src/`, `tests/` and `CODE_GUIDELINES.md`, the hostname removed from
`src/search/mcp_server.py`, and the branch history rewritten so that no commit message describes
the deployment. (Not the same as "matches none of the gate's patterns": this entry's own commit
says "on the repository owner's instruction", which the removed phrase list would have flagged.
It describes repository governance, not an installation, and the substantive claim is the one
that matters.) Removing the check does not un-fix what it found.

**Reading this after the fact.** The branch history was rebuilt from its final tree before it was
ever pushed, so the commits and files this entry describes — the gate script, its test, the six
commits — exist in no published commit. The record is here because the history deliberately does
not carry it.
**Affects:** `.claude/GATES.md`, `.claude/INDEX.md`, `.claude/memory/review-lessons.md`, `.claude/gates/no-deployment-prose.py` (deleted), `tests/unit/test_no_deployment_prose_gate.py` (deleted)

## 2026-09-07 — Round-7 minors: what was fixed, and two rebuttals

The seventh adversarial round returned SHIP with seven minors. Recorded here because the loop
rule is that nothing reported is silently dropped.

**Fixed.** The removal entry above understated its own false-positive measurement (four files, not
three — `tests/unit/common/test_config_search.py` carries the same `10.0.0.0/8` literal); gave two
different round counts in one paragraph; asserted "no commit message carries the phrasings" when
the docs commit says "on the repository owner's instruction", which the removed phrase list would
have matched; and cited a script, a test and six commits that exist in no published commit without
saying the history had been rebuilt. All corrected in place.

`src/common/config/_loader.py`'s docstring claimed `APP_DB_PATH` and `INDEX_DB_PATH` are "never
read from the table". Only `APP_DB_PATH` is enforced — it is re-injected after the merge. `stored`
is merged unfiltered, so a hand-inserted `INDEX_DB_PATH` row *would* win, which is what
`docs/configuration.md` now says. The docstring contradicted shipped documentation and the
documentation was right.

**Rebutted — the `# nosec B608` in `appdb.users.get_by_email` is NOT a no-op.** The round reported
it as a dead suppression protecting nothing, citing bandit's "nosec encountered … but no failed
test" line, and recommended removing it. Removed and measured: `bandit -r src/ -ll` goes from
no reported issues to one Medium-severity B608 in `src/appdb/users.py` (`get_by_email`), and its exit code
from 0 to 1 — the `python-security` gate turns red, and CI's `security-scan` job with it. (The
first version of this sentence said "1 medium to 2", reading bandit's *by confidence* tally as a
severity count. Corrected; the exit-code claim was always the load-bearing one.) The suppression is
load-bearing. Restored. The finding was wrong, and only running it showed that; this is the second
recommendation in two rounds that did not survive measurement (the other proposed a private-IP
check reported as near-zero false positives, measured at seven).

**Rebutted — the two `BREAKING CHANGE:` footers in the feature commit stay.** `CODE_GUIDELINES.md`
§16.1 speaks of *a* footer, and consolidating them is a formatting improvement that would cost
another history rewrite of an already-rewritten branch. Both breaks — the `/api/index/*` RBAC move
and the registry move — are stated explicitly and neither is hidden. Not worth re-orphaning the
KB stamps a third time, which is a defect this branch has already produced twice.
**Affects:** `.claude/DECISIONS.md`, `src/common/config/_loader.py`

## 2026-09-17 — `/settings/keys` gated on Member, not Admin

The SPA gated the API-keys screen on `admin` (`RequireAdmin` in `web/src/routes.tsx`), but the
server already permits Member-and-above: `require_key_management` (`src/search/deps.py`) ranks
the endpoint at `member`, and `_list_api_keys` (`src/search/api_key_routes.py`) scopes a
non-admin's listing to their own keys. The SPA contradicted its own backend contract and left
Members with no way to mint keys the API already grants them.

Fixed with a new `RequireMember`/`MemberGate` guard (`web/src/routes.tsx`), mirroring
`RequireAdmin`/`AdminGate`. `/settings/keys` now uses it; `/settings` and `/settings/users` stay
admin-only. `AppNavBar.tsx`'s `NAV_LINKS` gained a `memberOnly` flag and an "API keys" entry shown
only to the `member` role (an admin already reaches the screen from the Settings side nav; a
`readonly` user is turned away by `MemberGate` regardless). `SettingsLayout.tsx` gained an
exported `MEMBER_SETTINGS_NAV_GROUPS` (just the "Access control → API Keys" item) and an optional
`groups` prop, defaulting to the full admin set; `APIKeysScreen.tsx` passes the member rail when
the caller is not an admin, so a Member's side nav doesn't offer links that would bounce them back
to `/`.
**Affects:** `web/src/routes.tsx`, `web/src/features/shell/AppNavBar/AppNavBar.tsx`, `web/src/components/layout/SettingsLayout/SettingsLayout.tsx`, `web/src/features/access/APIKeysScreen/APIKeysScreen.tsx`, `web/src/pages/KeysPage.tsx`, `.claude/docs/modules/web.md`

## 2026-09-17 — PyJWT stays unpinned past 2.14; test harness follows both fetch boundaries

CI went red on `main` with `test_access_jwt.py` failing across the board once PyJWT 2.14 resolved:
`PyJWKClient.fetch_data` moved from calling `urllib.request.urlopen` directly to building an
opener (carrying a no-redirect handler) and calling `opener.open`. The suite's fixtures patched
only `urlopen`, so on 2.14 the fake JWKS was never served, `verify_access_email` reached for the
real network, and every verification returned `None` — reading as a broken verifier rather than a
stale fixture. `pyproject.toml`'s `PyJWT[crypto]~=2.13` admits both versions, so both are
genuinely reachable: CI resolves the newest, a developer's venv may hold the older.

Deliberately not pinning below 2.14: the change is a security hardening (JWKS fetches no longer
follow redirects), and `PyJWT[crypto]` is already a declared dependency specifically so this
auth path does not rest on another package's dependency graph (2026-09-06 entry) — pinning out a
hardening to keep a test green is the cheat `GATES.md` warns against. Fixed by patching both
boundaries: `_patch_fetch` in the test module is the one place that knows which PyJWT version is
installed, shared by the `fetches` fixture and `test_a_malformed_key_set_does_not_raise`.
**Affects:** `tests/unit/search/test_access_jwt.py`, `pyproject.toml`, `.claude/docs/TESTING.md`
