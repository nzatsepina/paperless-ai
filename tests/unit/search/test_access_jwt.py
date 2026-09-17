"""Tests for search.access_jwt — the Cloudflare Access assertion verifier.

These exercise the **real** ``jwt.decode`` call with the real options. That
matters more than it looks: the ``audience`` argument is the only thing
stopping a token minted for a *different* Access application from
authenticating here, and a test that stubs the verifier out cannot tell
whether that argument is present.

No JWKS server is needed. A locally generated RSA key is served by
monkeypatching PyJWT's HTTP boundary (see ``_patch_fetch``) — so PyJWT's own
caching and refresh logic runs and the signature, issuer, audience and expiry
checks all execute against tokens this module mints. Patching higher up was
tried and was wrong: ``get_jwk_set`` makes the fetch unreachable, and
``fetch_data`` is what populates the cache.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from search.access_jwt import access_config, verify_access_email

TEAM = "example.cloudflareaccess.com"
ISSUER = f"https://{TEAM}"
AUD = "aud-for-this-application"
OTHER_AUD = "aud-for-a-different-application"
OTHER_TEAM = "another-tenant.cloudflareaccess.com"


def _fake_html_response():
    """A context manager yielding an HTML error page, as a 5xx proxy would."""

    class _R:
        def __enter__(self):
            return io.StringIO("<html><body>502 Bad Gateway</body></html>")

        def __exit__(self, *exc):
            return False

    return _R()


def _fake_response(payload: dict):
    """A context manager returning *payload* as JSON, like urlopen does."""

    class _R:
        def __enter__(self):
            return io.StringIO(json.dumps(payload))

        def __exit__(self, *exc):
            return False

    return _R()


def _patch_fetch(monkeypatch, responder) -> None:
    """Point PyJWT's JWKS fetch at *responder*, whichever boundary it uses.

    ``responder(target)`` returns the fake response. Up to PyJWT 2.13
    ``PyJWKClient.fetch_data`` calls ``urllib.request.urlopen``; 2.14 builds an
    opener with a no-redirect handler and calls ``opener.open``. The declared
    pin (``PyJWT[crypto]~=2.13``) admits both, so both are patched — patching
    one lets the other version reach the real network, where every verification
    returns ``None`` and the failure looks like a broken verifier rather than a
    stale fixture.
    """

    class _Opener:
        """Stands in for what ``build_opener`` returns; ``open`` is all the
        client calls, and the handlers are its business, not the fixture's."""

        def open(self, target, **_k):  # noqa: A003 - mirrors urllib's own name
            return responder(target)

    monkeypatch.setattr(
        "jwt.jwks_client.urllib.request.urlopen",
        lambda *a, **_k: responder(a[0] if a else ""),
    )
    monkeypatch.setattr(
        "jwt.jwks_client.urllib.request.build_opener", lambda *_a, **_k: _Opener()
    )


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    """One RSA key for the module — generation is the slow part."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KID = "test-key-1"


@pytest.fixture(autouse=True)
def fetches(monkeypatch, key):
    """Serve a JWK set built from *key*, and count the network fetches.

    Serves the set through :func:`_patch_fetch`, so PyJWT's own caching and
    refresh logic runs. Returns the call list, so a test can assert how many
    fetches an implementation actually costs.
    """
    numbers = key.public_key().public_numbers()

    def _b64(n: int) -> str:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk_set_dict = {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64(numbers.n),
                "e": _b64(numbers.e),
            }
        ]
    }
    # Patch the network boundary itself. Patching get_jwk_set would make the
    # fetch unreachable and any "no fetch" assertion vacuous; patching
    # fetch_data would stop the key-set cache being populated, so every call
    # would look like a fetch. Both were tried and both were wrong.
    # Record the URL, do not discard it. A fixture that accepts any URL lets
    # the key-set path be hardcoded to one tenant with the whole suite green —
    # a silent, total authentication outage reached by an ordinary refactor.
    fetches: list[str] = []

    def _serve(target):
        fetches.append(getattr(target, "full_url", target))
        return _fake_response(jwk_set_dict)

    _patch_fetch(monkeypatch, _serve)

    import search.access_jwt as mod

    mod._jwks_client.cache_clear()  # a client cached by another test holds keys
    return fetches


def _token(key, **overrides) -> str:
    """Mint a signed assertion, with *overrides* applied to the claims."""
    kid_override = overrides.pop("headers_kid", KID)
    now = dt.datetime.now(tz=dt.timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": AUD,
        "iat": now,
        "exp": now + dt.timedelta(minutes=5),
        "email": "viewer@example.com",
        "type": "app",
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid_override})


def _verify(token) -> str | None:
    return verify_access_email(token, team_domain=TEAM, audience=AUD)


def test_valid_assertion_yields_the_email(key):
    assert _verify(_token(key)) == "viewer@example.com"


def test_token_for_another_application_is_refused(key):
    """The audience check is the whole point — prove it is enforced."""
    assert _verify(_token(key, aud=OTHER_AUD)) is None


def test_token_from_another_issuer_is_refused(key):
    assert _verify(_token(key, iss="https://evil.cloudflareaccess.com")) is None


def test_expired_token_is_refused(key):
    past = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(hours=1)
    assert _verify(_token(key, exp=past)) is None


def test_token_missing_a_required_claim_is_refused(key):
    """`require` forces exp/iat/aud/iss; drop one and it must not pass."""
    now = dt.datetime.now(tz=dt.timezone.utc)
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUD, "iat": now, "email": "viewer@example.com"},
        key,
        algorithm="RS256",
        headers={"kid": KID},
    )
    assert _verify(token) is None


def test_unsigned_token_is_refused(key):
    """`alg: none` must never authenticate."""
    now = dt.datetime.now(tz=dt.timezone.utc)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUD,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
            "email": "viewer@example.com",
        },
        key=None,
        algorithm="none",
        headers={"kid": KID},
    )
    assert _verify(token) is None


def test_token_signed_by_a_different_key_is_refused():
    """A valid-looking token signed by someone else's key must not pass."""
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _verify(_token(attacker)) is None


def test_machine_assertion_yields_no_email(key):
    """A service-token assertion is valid but identifies no person."""
    token = _token(key, email=None, common_name="abc123.access")
    assert _verify(token) is None


def test_garbage_and_absent_tokens_are_refused(key):
    assert _verify(None) is None
    assert _verify("") is None
    assert _verify("not-a-jwt") is None


def test_access_config_needs_both_variables(monkeypatch):
    monkeypatch.delenv("SEARCH_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("SEARCH_ACCESS_AUD", raising=False)
    assert access_config() is None
    monkeypatch.setenv("SEARCH_ACCESS_TEAM_DOMAIN", TEAM)
    assert access_config() is None, "one variable alone must not enable it"
    monkeypatch.setenv("SEARCH_ACCESS_AUD", "   ")
    assert access_config() is None, "whitespace must not count as configured"
    monkeypatch.setenv("SEARCH_ACCESS_AUD", AUD)
    assert access_config() == (TEAM, AUD)


def test_unknown_kid_costs_at_most_one_refetch(key, fetches, monkeypatch):
    """An attacker-chosen kid must not buy a network fetch per request.

    PyJWT's ``get_signing_key_from_jwt`` refreshes on any miss, and the kid
    comes from the *unverified* header — so random kids would cost one HTTPS
    round trip each, on the path before every credential check.

    Counting happens at ``urlopen``, the real network boundary. Patching
    ``get_jwk_set`` would make the fetch unreachable and the assertion
    vacuous; patching ``fetch_data`` would stop the key-set cache being
    populated and make every call look like a fetch. Both were tried.
    """
    import search.access_jwt as mod

    monkeypatch.setattr(mod, "_last_forced_refresh", 0.0)
    token = _token(key, headers_kid="a-kid-nobody-has-seen")
    assert _verify(token) is None
    after_first = len(fetches)
    for _ in range(5):
        assert _verify(token) is None
    assert len(fetches) == after_first, (
        f"repeated unknown kids must not refetch, went {after_first} -> {len(fetches)}"
    )
    assert after_first <= 2, f"one refresh at most, got {after_first}"


def test_a_rotated_in_kid_resolves_after_the_window(key, fetches, monkeypatch):
    """The rate limit must not become an outage at key rotation.

    The issuer publishes only its current and previous keys and rotates on a
    schedule, so at each rotation the new kid is unknown to the cache.
    Refusing outright would be a total outage wherever this path is the only
    usable credential, until the key-set cache expired. One allowed refresh per window resolves
    it instead.
    """
    import search.access_jwt as mod

    monkeypatch.setattr(mod, "_last_forced_refresh", 0.0)
    unknown = _token(key, headers_kid="rotated-in")
    assert _verify(unknown) is None  # consumes this window's refresh

    # A second unknown kid inside the window is refused without a fetch...
    before = len(fetches)
    assert _verify(_token(key, headers_kid="another")) is None
    assert len(fetches) == before

    # ...and once the window has passed, a refresh is allowed again.
    monkeypatch.setattr(mod, "_last_forced_refresh", 0.0)
    assert _verify(_token(key, headers_kid="third")) is None
    assert len(fetches) > before, "a rotation must be able to refresh"


def test_a_malformed_key_set_does_not_raise(key, monkeypatch):
    """The round-3 critical: an HTML error page must not 500 the app.

    PyJWT's fetch_data catches only URLError and TimeoutError, so json.load
    on an error page escapes as ValueError. Unhandled, and because this path
    runs before the cookie and bearer paths, that is a 500 on every request in
    the application, administrators included, with no way back in.
    """
    _patch_fetch(monkeypatch, lambda _target: _fake_html_response())
    import search.access_jwt as mod

    mod._jwks_client.cache_clear()
    try:
        assert _verify(_token(key)) is None
    finally:
        mod._jwks_client.cache_clear()


def test_the_audience_parameter_is_what_is_compared(key):
    """Pins the parameter, not just its presence.

    Hard-coding the aud inside jwt.decode would pass every other test here;
    this one fails unless the argument is threaded through.
    """
    token = _token(key, aud=OTHER_AUD)
    assert (
        verify_access_email(token, team_domain=TEAM, audience=OTHER_AUD)
        == "viewer@example.com"
    )


def test_only_rs256_is_accepted(key, monkeypatch):
    """Widening `algorithms` is the single most dangerous edit in this file.

    Admitting an HMAC algorithm alongside RS256 is the classic algorithm
    confusion setup: an attacker signs a token with the *public* key as the
    HMAC secret. PyJWT 2.13 happens to refuse that specific move, so this
    pins the argument itself rather than relying on the library's manners.
    """
    import search.access_jwt as mod

    seen: dict[str, object] = {}
    real_decode = mod.jwt.decode

    def _spy(token, k, **kw):
        seen.update(kw)
        return real_decode(token, k, **kw)

    monkeypatch.setattr(mod.jwt, "decode", _spy)
    assert _verify(_token(key)) == "viewer@example.com"
    assert seen["algorithms"] == ["RS256"], (
        f"only RS256 may be accepted, got {seen['algorithms']}"
    )


def test_the_issuer_is_derived_from_the_configured_team(key, monkeypatch):
    """The issuer passed to ``jwt.decode`` is built from the configured team.

    This spies on the argument, which proves the value is *right* but not that
    it *follows the parameter* — it only ever passes ``TEAM``, so a hardcoded
    issuer equal to ``f"https://{TEAM}"`` keeps it green. The mutation is
    killed by ``test_the_team_parameter_is_what_the_issuer_follows`` below;
    the pair is what pins the behaviour, neither test alone.
    """
    import search.access_jwt as mod

    seen: dict[str, object] = {}
    real_decode = mod.jwt.decode

    def _spy(token, k, **kw):
        seen.update(kw)
        return real_decode(token, k, **kw)

    monkeypatch.setattr(mod.jwt, "decode", _spy)
    assert _verify(_token(key)) == "viewer@example.com"
    assert seen["issuer"] == f"https://{TEAM}", (
        "the issuer must come from the configured team, not a constant"
    )


def test_the_key_set_url_is_built_from_the_configured_team(key, fetches):
    """The JWKS URL must follow the team argument, not a pinned tenant.

    Cloudflare publishes the key set at ``/cdn-cgi/access/certs`` under the
    team domain, so both halves matter: hardcode the host and a second
    deployment silently verifies against the wrong tenant's keys; change the
    path and nothing verifies at all. Both are total auth outages that no
    other test sees, because every other test passes the same team.
    """
    assert _verify(_token(key)) == "viewer@example.com"
    assert fetches, "the key set should have been fetched"
    assert fetches[0] == f"https://{TEAM}/cdn-cgi/access/certs", (
        "the key-set URL must be derived from team_domain, not a constant"
    )

    import search.access_jwt as mod

    mod._jwks_client.cache_clear()
    fetches.clear()
    assert (
        verify_access_email(
            _token(key, iss=f"https://{OTHER_TEAM}"),
            team_domain=OTHER_TEAM,
            audience=AUD,
        )
        == "viewer@example.com"
    )
    assert fetches[0] == f"https://{OTHER_TEAM}/cdn-cgi/access/certs", (
        "a second team must be fetched from its own key set"
    )


def test_the_team_parameter_is_what_the_issuer_follows(key):
    """A hardcoded issuer would refuse a second tenant's own valid token.

    Mints a token issued by a DIFFERENT team and verifies it under that team.
    It can only pass if the issuer is derived from the argument, so pinning a
    constant in its place turns this red — which the spy test above cannot do.
    Mirrors ``test_the_audience_parameter_is_what_is_compared``.
    """
    token = _token(key, iss=f"https://{OTHER_TEAM}")
    assert (
        verify_access_email(token, team_domain=OTHER_TEAM, audience=AUD)
        == "viewer@example.com"
    )


def test_a_token_with_no_kid_is_refused_without_spending_a_refresh(
    key, fetches, monkeypatch
):
    """A header with no kid must be refused *cheaply*.

    Deleting the guard leaves the return value unchanged — the kid simply
    matches nothing — so the refusal alone does not pin it. What it costs is
    the rate-limited refresh: without the guard a stream of kid-less tokens
    burns the one-per-minute allowance, and a genuine key rotation arriving in
    that window is refused. So the assertion that matters is the fetch count.
    """
    import search.access_jwt as mod

    monkeypatch.setattr(mod, "_last_forced_refresh", 0.0)
    assert _verify(_token(key)) == "viewer@example.com"  # warm the key-set cache
    before = len(fetches)
    now = dt.datetime.now(tz=dt.timezone.utc)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUD,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
            "email": "viewer@example.com",
        },
        key,
        algorithm="RS256",
    )
    assert "kid" not in jwt.get_unverified_header(token)
    assert _verify(token) is None
    assert len(fetches) == before, "a kid-less token must not spend a refresh"


def test_the_per_kid_key_cache_stays_disabled(monkeypatch):
    """PyJWT's per-kid LRU has no time expiry.

    Enabling it means a signing key rotated out — including one rotated out
    *because it was compromised* — stays trusted for the process lifetime.
    The module docstring says so; nothing was checking it.
    """
    import search.access_jwt as mod

    captured: dict[str, object] = {}
    real_init = mod.PyJWKClient.__init__

    def _spy(self, uri, **kw):
        captured.update(kw)
        return real_init(self, uri, **kw)

    monkeypatch.setattr("jwt.PyJWKClient.__init__", _spy)
    mod._jwks_client.cache_clear()
    try:
        mod._jwks_client("example.cloudflareaccess.com")
    finally:
        mod._jwks_client.cache_clear()
    assert captured.get("cache_keys") is not True, (
        "cache_keys has no time expiry; a rotated-out key would stay trusted"
    )
    assert captured.get("lifespan") == mod._JWKS_CACHE_SECONDS
    assert captured.get("timeout") == mod._JWKS_TIMEOUT_SECONDS
