# Verified reverse-proxy identity as a third credential kind

**Status:** implemented — `feat/cloudflare-access-identity`
**Date:** 2026-09-06
**Decision log:** `.claude/DECISIONS.md` — *2026-09-06 — Cloudflare Access identity as a third auth path, tried first*

> This repository is public. The spec names the **product** it integrates with
> — Cloudflare Access, which is the only issuer this code supports — because a
> reader cannot configure the feature without it. It names no *deployment*: no
> host, domain, tenant, account, audience tag or topology.

## Origin — the problem before the solution

Deployments that put an identity-aware reverse proxy in front of the search
server had no way to let the proxy's authenticated people be *themselves* in
the application. The proxy knows exactly who the caller is; the application
did not, because its only two credentials are its own session cookie and its
own API keys.

The workaround such deployments actually reach for is to have the proxy inject
**one shared API key** on every request. That works, and it destroys the reason
accounts exist: every action in the audit log is attributed to the one machine
identity that the proxy injects, not to the person who took it. Traceability is
the whole point of having per-person accounts, and a shared injected credential
is precisely the thing that removes it.

Password login was considered and rejected upstream of this change: where the
proxy already authenticates people (commonly with a second factor), a second
password prompt inside the application is a worse experience *and* a second
credential to leak, for no security gain.

## Requirements

1. A person authenticated by the proxy is resolved to **their own account**,
   with their own role, and appears as themselves in every log and audit trail.
2. The path must be **no weaker** than the cookie and API-key paths it joins.
3. It must be **off by default** and change nothing for deployments that do not
   use it.
4. It must not widen who can sign in beyond the accounts an administrator
   deliberately created.
5. Machine callers must keep working exactly as before.

## Design

### D0 — Cloudflare Access only, and say so

The implementation is Cloudflare-specific in two places that are not
configurable: the key set is fetched from `https://<team-domain>/cdn-cgi/access/certs`,
and the assertion is read from the `Cf-Access-Jwt-Assertion` header. Supporting
Authelia, oauth2-proxy or Pomerium is a code change, not a setting.

*Why it is written down rather than generalised:* one issuer is what the
deployment needed, and an abstraction over identity providers with exactly one
implementation is the overengineering this project's guidelines reject. But the
documentation must then **say** Cloudflare, or an operator sets two variables
against a different proxy and gets silent, total authentication failure — the
configuration reads as generic while the code is not.

### D1 — Verify the signed assertion, never the identity header

The proxy forwards both a plaintext identity header and a **signed assertion**
of the same identity. Only the assertion is trusted: the signature is checked
against the issuer's published key set, together with issuer, audience and
expiry.

*Why:* a plaintext header is forgeable by anything that can reach the origin
directly — a mis-scoped firewall rule, a container on the same network, a
second ingress path. A signature is not. Trusting the header would make this
credential strictly weaker than the two it joins, violating requirement 2.
The proxy vendor's own guidance is that header validation alone is insufficient
and the signature must be confirmed.

*Rejected:* trusting the header and relying on network restriction alone.
Network restriction is defence in depth, never a substitute for authentication.

### D2 — Tried first, before cookie and bearer

*Why:* were the cookie tried first, a stale session would outrank the proxy's
identity, and one browser could keep acting as another person for the whole
lifetime of that session — the exact failure the change exists to remove.

### D3 — Match only; never provision

A verified email resolves an **existing** account. An address with no account
is refused and logged.

*Why:* provisioning on first sight puts the set of people who can sign in
under the proxy's policy, which this application cannot read — violating
requirement 4. It also makes account deletion meaningless: the next request
recreates the account. An earlier revision of this change did auto-provision,
and every serious defect found in review was downstream of that one choice —
including suspend-then-delete silently restoring an active account, and an
ambiguous address creating one new account per request.

*Rejected:* provision-on-first-sight with a role floor. Simpler to write,
and it cannot express revocation.

### D4 — Yield, never swallow

The path returns "no person" — and falls through to cookie and bearer — for an
invalid assertion, a **machine** caller (a service-token assertion is validly
signed but carries no identity claim), an address with **no** account, an
address held by **more than one** account, or a **suspended** account.

*Why (machine):* swallowing a machine caller would discard the API-key scope
model and the audit linkage from a request to the key that made it —
violating requirement 5.
*Why (ambiguous):* treating "several matches" as "no match" is a fail-open
collapse; with provisioning still present it produced an account per request.
Ambiguity is refused explicitly, not folded into absence.

### D5 — No scopes

A caller resolved this way carries no API-key scopes and is bounded by their
account's role alone — identical to a cookie session. It grants nothing a
cookie session does not.

### D6 — Environment-only configuration

`SEARCH_ACCESS_TEAM_DOMAIN` and `SEARCH_ACCESS_AUD` are read straight from the
environment and are deliberately absent from the configuration table.

*Why:* every other setting is editable through `PUT /api/settings`. Who the
application *trusts to assert identity* must not be. They are also read
without building the full settings object, so an unrelated missing variable
cannot break sign-in. Both unset disables the path entirely (requirement 3).

### D7 — An explicit cross-site check

The cookie path's CSRF defence is `SameSite=Strict` on the application's own
cookie. This path is not authenticated by that cookie, and the proxy's cookie
policy is outside this repository's control, so state-changing requests carry
an explicit `Origin` / `Sec-Fetch-Site` check.

*Why:* inheriting a defence that does not apply is how a path silently loses
it. Do not remove the check on the grounds that the proxy's cookie looks safe.

### D8 — Key rotation must actually rotate

The key-set client caches with a time limit and refuses the per-key cache that
never expires, so a signing key rotated out — including one rotated out
*because it leaked* — stops being trusted. A forced refresh on an unknown key
id is rate-limited so an attacker cannot use unknown key ids to hammer the
issuer.

## Breaking change

`GET /api/index/{status,activity,failed}` moved from read-only+`api` scope to
**admin only**, and the `/index` route and nav link with it. Daemon
heartbeats, reconcile history and the failed-document list are operational
detail for whoever runs the deployment, not general-purpose read data. This is
an owner decision, not a consequence of the auth change; it is called out here
because it is the same release.

## Verification

Each mutation listed here was **run** — the code was broken in that specific
way and the suite confirmed to go red on a named test. The list is what has
been established, not a claim about every line:

| Mutation | Killed by |
|:---|:---|
| Widen the accepted algorithms beyond RS256 | `test_only_rs256_is_accepted` |
| Hardcode the issuer instead of deriving it from the team | `test_the_team_parameter_is_what_the_issuer_follows` |
| Hardcode the key-set URL to one tenant | `test_the_key_set_url_is_built_from_the_configured_team` |
| Read the assertion from a different header | `test_the_assertion_is_read_from_the_cloudflare_header` |
| Re-enable the non-expiring per-key cache | `test_the_per_kid_key_cache_stays_disabled` |
| Drop the key-id guard | `test_a_token_with_no_kid_is_refused_without_spending_a_refresh` |
| Treat an ambiguous address as an absent one | `test_an_ambiguous_address_is_refused_and_provisions_nothing` |
| Provision on a missed match | `test_deleting_an_account_revokes_access` |
| Put either `SEARCH_ACCESS_*` variable in `CONFIG_KEYS` | `test_config_keys_has_ninety_entries` |

Three of those rows exist because an earlier revision of this document
claimed coverage it did not have, and a reviewer ran the mutations.

The issuer is the instructive one. A first attempt spied on the argument
passed to `jwt.decode` and asserted it equalled the configured team — which a
hardcoded issuer *also* satisfies, because the test only ever passed one team.
The mutation was run and survived. It is now killed by a test that mints a
token for a *second* team and verifies it under that team: only an issuer
derived from the argument can accept it.

The other two are D0's own points, and both were unguarded for the same
reason — a fixture that accepted anything. The key-set URL was checked by a
`urlopen` stub written `def _urlopen(*_a, **_k)`, discarding the URL, so
pinning the whole endpoint to one tenant kept the suite green. The header name
was covered only by tests whose stubbed verifier ignored the token it was
handed, so renaming `Cf-Access-Jwt-Assertion` kept the suite green too. Either
one is a silent, total authentication outage reachable by an ordinary
refactor. A test that asserts a value is not the same as a test that pins a
behaviour, and a fixture that accepts every input pins nothing at all.
