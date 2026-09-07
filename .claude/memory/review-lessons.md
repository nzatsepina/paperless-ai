# Review lessons — recurring finding classes

Standing checks distilled from Large-Change-Workflow gate rounds. Apply these
when writing or reviewing specs, plans, and code in this repo — before a gate
does it for you. Living file: add a class when a finding recurs, sharpen one
when it sharpens, delete one that stops being true.

## Spec & plan gates

- **Grep-receipt every "X is in file Y" claim.** The single most-repeated
  finding across the spec and plan gates (3 rounds each) was invented or wrong
  harness/symbol locations — naming a helper in the wrong file, calling a
  function a "fixture", asserting a test path that did not exist. Any sentence
  in a spec or plan that locates a symbol, test, or fixture carries a
  `grep`-verified anchor, never a remembered one.
- **Lint and run the code a plan shows.** Extracting the plan's snippets and
  running `ruff` / `pytest` on them caught real defects cheaply — `F401` residue,
  wrong kwarg names, `caplog` where the project uses `capture_logs`. A plan's
  code blocks are code; check them like code.
- **A new early-return / skip branch must state its return value** wherever a
  downstream consumer switches on it. "Reuses the existing primitive" and
  "routes through the existing code path" are different claims — say which one
  is true.

## Fail-safe / untrusted-input code

- **Every parser gets an explicit malformed-input decision, and it fails
  closed.** A garbled probe row must *raise*, never silently read as "no signal".
  The gates repeatedly flagged fail-*open* parsers on untrusted PDF bytes; the
  safe direction here is to over-OCR, so any ambiguity resolves to "not
  born-digital".
- **A subprocess timeout must live in the read loop, not just `proc.wait()`.**
  The plan gate's one CRITICAL was a decorative timeout: a Poppler binary that
  spins with no output would hang a worker because the deadline sat only on
  `wait()`, not on a `select`-based read. Any subprocess over untrusted input
  needs a read-deadline **and** a hard output cap (decompression-bomb defence).

## Implementation review

- **A mocked test seam does not guard the real logic beneath it.** The
  max-vs-sum coverage invariant had a "test" that mocked `_probe_signals`, so it
  never exercised the parser it claimed to protect. For a load-bearing
  invariant, test the actual function against an input that would flip under the
  wrong variant — not a mock sitting above it.
- **Prefer a pair or a dataclass to a 3-tuple return** (CODE_GUIDELINES.md
  §5.8). A three-or-more positional unpack at the call site is a review finding
  on sight; the module usually already has a frozen dataclass to reach for.

## Mutation testing

- **A spy test asserts a value; it does not pin a behaviour.** The Access
  round's own example: `test_the_issuer_is_derived_from_the_configured_team`
  spied on the `issuer=` argument and asserted it equalled the configured team
  — but every call in the file passed the *same* team, so replacing the
  expression with that literal left the suite green. The mutation was run and
  survived. A parameter is only pinned by a call that passes a **second,
  different** value (`OTHER_TEAM`, `OTHER_AUD`). Before claiming a mutation is
  covered, run it.
- **State a mutation claim only after running the mutation.** The spec asserted
  six pinned mutations; five were real and one was not, and the false one was
  found by a reviewer rather than by the author. If a document says "this is
  pinned", the author has broken the code that way and watched a test fail.

## Public-repo hygiene

- **Documentation written vendor-neutrally for a vendor-specific
  implementation is a false promise, not good hygiene.** Keeping the
  *deployment* out of a public repo is right; generalising the *product* is
  not. The Access docs first described `SEARCH_ACCESS_TEAM_DOMAIN` as "the
  hostname of the identity-aware reverse proxy", while the code hardcodes
  `/cdn-cgi/access/certs` and the `Cf-Access-Jwt-Assertion` header — so an
  operator on Authelia would have configured it and had every request fail
  silently, and a Cloudflare operator would have set their app's hostname
  rather than the team domain. Name the product; hide the host, domain,
  tenant, account, audience tag and topology.
- **Reasoning comments leak deployments too.** Comments asserting that one
  named role alone sees the logs, describing the credential set of the
  particular installation, or naming a gendered individual as the only viewer
  of a screen all shipped in code and test docstrings. State the property of the *software*
  ("operational state is admin-gated", "where this path is the only usable
  credential"), never of the people running one instance of it. **And sweep
  the class, not the instance:** the first fix restated three comments and a
  module docstring sixty lines above one of them survived; the second shipped a
  `review-lessons` entry claiming the class was eliminated alongside four live
  examples; the third missed one more in a file that same entry named as clean.
  Three rounds, because each sweep was a grep hand-written from the instances
  already known. **This lesson is the control — there is no
  mechanical check.** One was built and then removed on the repository owner's
  instruction (see `DECISIONS.md`, 2026-09-07). Its phrase list was overfitted to
  the exact strings one session had used, and it was twice declared to cover the
  class while covering half. Read that as a warning about *this* lesson too: a
  sweep written from the instances already known misses their siblings every
  time, so sweep for the shape — a sentence asserting something about one
  installation, its credential set, its hostnames, or the people running it —
  not for the words a previous round happened to use.

- **Sanitise before the *first* commit, not the last.** Host / topology / PII
  removed only in the tip commit still ships in the branch's earlier commits,
  and the whole history is pushed to the public repo. The secret-scan gate
  caught a topology string that had already been "sanitised" in the final
  commit — it survived in earlier ones. Deleting a line in a later commit does
  not clean git history; the fix is a history rewrite, and it is far cheaper to
  keep the value out from commit one. See [[public-repository]].

## Empirical calibration

- **Measurement beats an argued preference on a contested formula.** The
  max-vs-sum coverage choice was settled by re-running the detection probe
  against the operator's ground-truth corpus: the sum variant flipped a
  known born-digital doc to OCR, max held. When a ground-truth set exists,
  measure the decision — do not debate it.
