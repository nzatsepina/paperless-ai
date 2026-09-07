"""Cloudflare Access assertion verification for the search app.

Cloudflare Access puts a signed JWT on every authenticated request in the
``Cf-Access-Jwt-Assertion`` header. Verifying that signature is strictly
stronger than trusting ``Cf-Access-Authenticated-User-Email``: Cloudflare's own
guidance is that validating the header alone is not sufficient and the JWT and
signature must be confirmed, and a signature cannot be forged by anything that
reaches the origin directly.

Two assertion shapes arrive here and only one carries a person:

* a **user** assertion, issued after someone passes the one-time PIN, carries
  an ``email`` claim;
* a **service-token** assertion, issued for a machine (the MCP clients), is
  equally valid and signed but carries ``common_name`` — the token's Client ID
  — and **no** ``email``.

:func:`verify_access_email` therefore returns ``None`` for a machine caller as
well as for an invalid token, and the caller falls through to the cookie and
bearer paths. Swallowing a machine caller here would discard the API-key scope
model and the ``api_key_id`` audit linkage.

Allowed deps: jwt, structlog. Forbidden: sqlite3, FastAPI, appdb, store.
"""

from __future__ import annotations

import os
import threading
import time
from functools import lru_cache

import jwt
import structlog
from jwt import PyJWK, PyJWKClient

log = structlog.get_logger(__name__)

#: How long PyJWKClient may reuse a fetched key set before re-fetching.
_JWKS_CACHE_SECONDS = 600

#: Deadline for the JWKS fetch. PyJWKClient defaults to 30s, and this call sits
#: on the authentication path that runs BEFORE the cookie and bearer paths — a
#: slow key endpoint would stall every request, sessions included.
_JWKS_TIMEOUT_SECONDS = 5


@lru_cache(maxsize=4)
def _jwks_client(team_domain: str) -> PyJWKClient:
    """Return the process-wide :class:`PyJWKClient` for *team_domain*.

    ``cache_keys`` is deliberately left OFF. It enables PyJWT's per-``kid``
    LRU, which has **no time-based expiration** — a signing key rotated out
    would stay trusted for the process lifetime. ``lifespan`` bounds the key
    *set* cache, which already removes the per-request round trip.

    Args:
        team_domain: The Access team domain, e.g.
            ``example.cloudflareaccess.com``.
    """
    return PyJWKClient(
        f"https://{team_domain}/cdn-cgi/access/certs",
        lifespan=_JWKS_CACHE_SECONDS,
        timeout=_JWKS_TIMEOUT_SECONDS,
    )


#: Minimum gap between forced key-set refreshes. Bounds two opposite hazards
#: with one number: an attacker choosing random ``kid`` values can force at
#: most one outbound fetch per window, and a genuine key rotation is picked up
#: within one window rather than waiting out the whole key-set cache.
_REFRESH_MIN_INTERVAL_SECONDS = 60.0

_last_forced_refresh = 0.0
#: Guards the check-and-set above.
#:
#: **Deliberately untested, and this is the rebuttal rather than an omission.**
#: Removing this lock survives every mutation attempt: the check-and-set is a
#: handful of bytecodes with no I/O between them, so threads do not interleave
#: there without instrumenting the production path for the test's benefit — a
#: barrier plus a slowed fetch was tried and still did not observe it. A test
#: that cannot fail is worse than none, so the lock stands on reasoning: it is
#: correct, it is cheap, the fetch happens OUTSIDE it so callers are not
#: serialised behind a 5-second network call, and without it the documented
#: one-per-window bound is simply false. Without it the window is not a bound at all:
#: `resolve_caller` is a sync dependency, so it runs on the threadpool, and N
#: workers can all pass the `if` before any performs the assignment — the
#: actual limit would be min(threadpool, concurrency) fetches per window, not
#: one, which is precisely the stall the docstring warns about.
_refresh_lock = threading.Lock()


def _key_for_kid(client: PyJWKClient, kid: str | None) -> PyJWK | None:
    """Return the signing key for *kid*, refreshing at most once per window.

    PyJWT's own ``get_signing_key_from_jwt`` calls ``get_signing_keys(
    refresh=True)`` on **any** miss, and ``kid`` comes from the *unverified*
    header — so an attacker picking random kids forces one outbound HTTPS
    fetch per request, on the path that runs before every other credential
    check. Enough concurrent requests exhaust the threadpool and stall the
    whole application.

    Refusing an unknown kid outright fixes that and creates a worse problem:
    the identity provider publishes only its current and previous keys, and
    rotates on a schedule (Cloudflare Access: every six weeks). At each
    rotation the new kid is unknown until the key-set cache expires. Where this
    path is the only usable credential, that is a total outage for the length
    of that cache.

    One rate-limited refresh closes both: the attacker gets at most one fetch
    per window, and a rotation resolves within one window.

    Args:
        client: The JWKS client for the issuer.
        kid: The key id from the token's unverified header.

    Returns:
        The matching key, or ``None`` when the kid is unknown even after an
        allowed refresh.
    """
    global _last_forced_refresh
    if kid is None:
        return None
    match = next((k for k in client.get_jwk_set().keys if k.key_id == kid), None)
    if match is not None:
        return match
    with _refresh_lock:
        now = time.monotonic()
        if now - _last_forced_refresh < _REFRESH_MIN_INTERVAL_SECONDS:
            return None
        _last_forced_refresh = now
    log.info("search.access_jwt_refreshing_keys", kid=kid)
    return next(
        (k for k in client.get_jwk_set(refresh=True).keys if k.key_id == kid), None
    )


def verify_access_email(
    token: str | None,
    *,
    team_domain: str,
    audience: str,
) -> str | None:
    """Verify a Cloudflare Access assertion and return the caller's email.

    Returns ``None`` — never raises — in every case where the request must
    fall through to the cookie and bearer paths:

    * *token* is absent or empty;
    * the signature, issuer, audience or expiry does not check out;
    * the assertion is valid but carries no ``email`` claim, which is the
      service-token (machine) case.

    Args:
        token: The raw ``Cf-Access-Jwt-Assertion`` header value, or ``None``.
        team_domain: The Access team domain the token must be issued by.
        audience: The application's AUD tag; a token minted for a *different*
            application must not authenticate this one.

    Returns:
        The verified email address, or ``None``.
    """
    if not token:
        return None
    try:
        client = _jwks_client(team_domain)
        kid = jwt.get_unverified_header(token).get("kid")
        signing_key = _key_for_kid(client, kid)
        if signing_key is None:
            log.warning("search.access_jwt_unknown_kid")
            return None
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{team_domain}",
            options={"require": ["exp", "iat", "aud", "iss"]},
        )
    except (jwt.PyJWTError, ValueError, AttributeError, TypeError) as exc:
        # These mean "this is not a valid assertion" and the caller falls
        # through to the cookie and bearer paths, ending in 401.
        #
        # ValueError is here for a specific, reachable reason: PyJWT's
        # fetch_data catches only URLError and TimeoutError, so a key endpoint
        # answering 200 with a non-JSON body — a captive portal or a
        # TLS-terminating interstitial — lets json.JSONDecodeError (a
        # ValueError) escape. A 5xx does NOT: PyJWT catches HTTPError, which
        # subclasses URLError, and converts it. That is untrusted external data, not a bug in our code, and
        # because this branch runs BEFORE the cookie and bearer paths it would
        # otherwise 500 every request in the application, locking out
        # administrators along with everyone else. Credential checks return a
        # value; they do not raise.
        #
        # exc_info is deliberately absent: this logs once per rejected token,
        # so a stack trace here is an unauthenticated log amplifier.
        log.warning("search.access_jwt_rejected", error=type(exc).__name__)
        return None

    email = claims.get("email")
    if not email:
        # A valid machine assertion: signed, in-date, for this application,
        # but identifying a service token rather than a person.
        log.debug(
            "search.access_jwt_machine_caller",
            common_name=claims.get("common_name"),
        )
        return None
    return str(email)


def access_config() -> tuple[str, str] | None:
    """Return ``(team_domain, audience)`` when Access verification is enabled.

    Read straight from the environment rather than through
    :func:`common.config.current_settings`, for two reasons. These values are
    deliberately env-only — ``PUT /api/settings`` must not be able to repoint
    who the application trusts — so there is nothing in the config table to
    merge. And building the full ``Settings`` on every request would couple
    authentication to every unrelated required variable: a missing
    ``PAPERLESS_TOKEN`` would stop people logging in.

    Returns:
        The pair when **both** variables are set and non-empty, else ``None``,
        which disables the branch and leaves cookie and bearer auth unchanged.
    """
    team = os.environ.get("SEARCH_ACCESS_TEAM_DOMAIN", "").strip()
    aud = os.environ.get("SEARCH_ACCESS_AUD", "").strip()
    if not team or not aud:
        return None
    return team, aud
