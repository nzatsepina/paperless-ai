"""Tests for the Cloudflare Access assertion branch in search.deps.

The branch is tried BEFORE the cookie and bearer paths, so these tests pin
the two properties that matter and are easy to regress:

* a **person** (an assertion carrying ``email``) is resolved from an existing
  account — this path never creates one,
  and outranks a stale session cookie — otherwise one browser could act as
  another person for the life of that cookie;
* a **machine** (a valid service-token assertion, which carries
  ``common_name`` and no ``email``) falls THROUGH to the bearer path with its
  scopes and ``api_key_id`` intact — swallowing it would silently discard the
  API-key scope model and the audit linkage.

The signature check itself is stubbed: verifying real RS256 would mean
standing up a JWKS server, which tests the library rather than this branch.
What is under test is the routing decision the branch makes given a verified
email, a machine caller, or a rejected token.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.schema import ensure_schema
from appdb.api_keys import create as create_key
from appdb.users import create as create_user
from appdb.users import delete as delete_user
from appdb.users import update as update_user
from search.api_keys import generate_raw_key, hash_key, key_display_prefix
from search.appstate import AppState, attach_app_state
from search.auth import SESSION_COOKIE_NAME
from search.deps import get_current_user, require_admin, require_api_scope
from search.sessions import CurrentUser, begin_session
from search.setup import SetupState

TEAM = "example.cloudflareaccess.com"
AUD = "aud-under-test"


def _db_path(conn: sqlite3.Connection) -> str:
    """Return the filesystem path of *conn*'s ``main`` database."""
    rows = conn.execute("PRAGMA database_list").fetchall()
    return next(row[2] for row in rows if row[1] == "main")


@pytest.fixture
def conn(tmp_path):
    """An open, migrated ``app.db`` on disk."""
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


@pytest.fixture
def client(conn):
    """A TestClient over one route that echoes the resolved caller."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
        return {"id": user.id, "username": user.username, "role": user.role}

    @app.post("/change")
    def change(user: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
        return {"id": user.id}

    attach_app_state(
        app.state, AppState(app_db_path=_db_path(conn), setup_state=SetupState())
    )
    return TestClient(app)


@pytest.fixture
def access_on(monkeypatch):
    """Enable the Access branch with a stubbed verifier.

    Every seeded account below uses a username the real validator permits
    (``^[A-Za-z0-9._-]+$`` — no ``@``) and carries its address in ``email``,
    because that is the only shape this application can actually produce. An
    earlier version of these tests seeded ``@``-containing usernames straight
    through ``appdb.users.create``, bypassing the validator, and so passed
    while the feature could not match a single real account.

    The verifier itself is covered against real signatures in
    ``test_access_jwt.py``; what is under test here is the routing decision
    ``resolve_caller`` makes given a verified email, a machine caller, or a
    rejection.
    """

    def _enable(email_for_token):
        monkeypatch.setenv("SEARCH_ACCESS_TEAM_DOMAIN", TEAM)
        monkeypatch.setenv("SEARCH_ACCESS_AUD", AUD)

        def _verify(token, *, team_domain, audience):
            # Assert, do not discard. A stub that accepts any team or audience
            # pins nothing about the wiring it stands in for: hardcode either
            # kwarg in resolve_caller, or swap the two, and every test here
            # would still pass while the deployment fetched its key set from
            # the wrong place and authenticated nobody.
            assert (team_domain, audience) == (TEAM, AUD), (
                f"resolve_caller must forward the configured pair, "
                f"got {team_domain!r}/{audience!r}"
            )
            return email_for_token(token)

        monkeypatch.setattr("search.access_jwt.verify_access_email", _verify)

    return _enable


def test_suspended_account_is_refused(conn, client, access_on):
    """A suspended account must not authenticate on this path either.

    Where no account has a usable password, suspension is the only revocation
    available. Both other credential paths fail closed on a suspended account;
    this one must too, or a suspended admin keeps their role for as long as
    they hold an Access token.
    """
    user = create_user(
        conn,
        username="gone",
        email="gone@example.com",
        password_hash=hash_password("irrelevant"),
        role="admin",
    )
    update_user(conn, user.id, status="suspended")
    access_on(lambda token: "gone@example.com")
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "tok"})
    assert r.status_code == 401, "a suspended admin must not authenticate"


def test_the_assertion_is_read_from_the_cloudflare_header(conn, client, access_on):
    """The assertion is read from ``Cf-Access-Jwt-Assertion``, not any header.

    Every other test here hands the stub a token-blind ``email_for_token``, so
    renaming the header in ``resolve_caller`` leaves them all green while the
    deployment authenticates nobody. This one makes the stub token-SENSITIVE
    and checks both directions: the real header authenticates, and the same
    token in a neighbouring header does not.
    """
    create_user(
        conn,
        username="viewer",
        email="viewer@example.com",
        password_hash=hash_password("irrelevant"),
        role="member",
    )
    access_on(lambda token: "viewer@example.com" if token == "the-real-token" else None)

    good = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "the-real-token"})
    assert good.status_code == 200, "the Cloudflare header must be the one read"
    assert good.json()["username"] == "viewer"

    wrong_header = client.get(
        "/whoami", headers={"X-Access-Jwt-Assertion": "the-real-token"}
    )
    assert wrong_header.status_code == 401, (
        "a token in any other header must not authenticate"
    )

    wrong_token = client.get(
        "/whoami", headers={"Cf-Access-Jwt-Assertion": "a-different-token"}
    )
    assert wrong_token.status_code == 401, "the header's value must be what is verified"


def test_existing_person_is_matched_not_duplicated(conn, client, access_on):
    """A verified email matching an existing account reuses that row."""
    existing = create_user(
        conn,
        username="viewer",
        email="viewer@example.com",
        password_hash=hash_password("irrelevant"),
        role="admin",
    )
    access_on(lambda token: "viewer@example.com")
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "tok"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == existing.id, "must not create a duplicate row"
    assert r.json()["role"] == "admin", "must not demote an existing admin"


def test_access_identity_outranks_a_stale_cookie(conn, client, access_on):
    """The branch is tried first, so a stale cookie cannot impersonate."""
    create_user(
        conn,
        username="viewer",
        email="viewer@example.com",
        password_hash=hash_password("irrelevant"),
        role="member",
    )
    other = create_user(
        conn,
        username="someone.else",
        email="someone.else@example.com",
        password_hash=hash_password("irrelevant"),
        role="member",
    )
    token = begin_session(conn, user_id=other.id, ttl_seconds=3600).token
    access_on(lambda t: "viewer@example.com")
    r = client.get(
        "/whoami",
        headers={"Cf-Access-Jwt-Assertion": "tok"},
        cookies={SESSION_COOKIE_NAME: token},
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "viewer"


def test_machine_caller_falls_through(conn, client, access_on):
    """A valid assertion with no email must not resolve or provision."""
    access_on(lambda token: None)  # service token: signed, but no email claim
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "machine-tok"})
    assert r.status_code == 401, "must fall through, not become an anonymous member"
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_machine_caller_still_reaches_its_api_key(conn, client, access_on):
    """The headline claim: a machine keeps its key, scopes and audit linkage.

    Swallowing the machine caller as an anonymous person would silently
    discard the API-key scope model, so assert the bearer path is reached and
    resolves the key's owner.
    """
    owner = create_user(
        conn,
        username="pipeline",
        email="pipeline@example.com",
        password_hash=hash_password("irrelevant"),
        role="member",
    )
    raw = generate_raw_key()
    create_key(
        conn,
        key_hash=hash_key(raw),
        key_prefix=key_display_prefix(raw),
        name="mcp",
        owner_user_id=owner.id,
        scopes="mcp",
    )
    access_on(lambda token: None)
    r = client.get(
        "/whoami",
        headers={
            "Cf-Access-Jwt-Assertion": "machine-tok",
            "Authorization": f"Bearer {raw}",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "pipeline"


def test_disabled_when_unconfigured(conn, client, monkeypatch):
    """With either variable unset the branch never runs."""
    monkeypatch.delenv("SEARCH_ACCESS_TEAM_DOMAIN", raising=False)
    monkeypatch.delenv("SEARCH_ACCESS_AUD", raising=False)
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "tok"})
    assert r.status_code == 401


def test_a_real_account_is_matched_by_email(conn, client, access_on):
    """The trap this branch was rebuilt for.

    ``validate_username`` forbids ``@`` and usernames cannot be changed, so a
    real account never has an address for a username. Matching on username
    missed every real row and provisioned a shadow member beside it — silently
    demoting an admin, because this path is tried first and returns at once.
    """
    owner = create_user(
        conn,
        username="alice.owner",  # validator-shaped: no @
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "tok"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == owner.id, "must match the real row, not shadow it"
    assert r.json()["role"] == "admin", "must not demote the owner"
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_cross_site_state_change_is_refused(conn, client, access_on):
    """CSRF: SameSite=Strict protects the cookie path, not this one.

    A cross-site form POST is a simple request, so no preflight stops it, and
    the proxy's cookie would travel if its policy allowed. The Origin check is
    what holds regardless of that policy.
    """
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.post(
        "/change",
        headers={
            "Cf-Access-Jwt-Assertion": "tok",
            "Origin": "https://evil.example",
        },
    )
    assert r.status_code == 403, "a cross-site state change must be refused"

    r = client.post(
        "/change",
        headers={
            "Cf-Access-Jwt-Assertion": "tok",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert r.status_code == 403, "Sec-Fetch-Site alone is enough to refuse"


def test_same_site_state_change_is_allowed(conn, client, access_on):
    """The check must not break the application's own requests."""
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.post(
        "/change",
        headers={
            "Cf-Access-Jwt-Assertion": "tok",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    assert r.status_code == 200, r.text


def test_cross_site_read_is_not_refused(conn, client, access_on):
    """Only state-changing methods are gated; a GET is not a CSRF risk here."""
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.get(
        "/whoami",
        headers={
            "Cf-Access-Jwt-Assertion": "tok",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert r.status_code == 200, r.text


def test_a_plaintext_origin_on_the_same_host_is_refused(conn, client, access_on):
    """http://host must not satisfy an https request.

    An earlier fix built both schemes and accepted either, which is no check
    at all, under a comment claiming it rejected the plaintext one.
    """
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.post(
        "https://testserver/change",
        headers={
            "Cf-Access-Jwt-Assertion": "tok",
            "Origin": "http://testserver",
        },
    )
    assert r.status_code == 403, "a plaintext origin must not match an https request"


def test_the_matching_origin_is_allowed(conn, client, access_on):
    """The allow path needs its own test, or inverting the comparison passes."""
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.post(
        "https://testserver/change",
        headers={
            "Cf-Access-Jwt-Assertion": "tok",
            "Origin": "https://testserver",
        },
    )
    assert r.status_code == 200, r.text


def _dupe(conn, email):
    """Insert a second row holding *email* — reachable without UNIQUE."""
    conn.execute(
        "INSERT INTO users (username, password_hash, role, status, "
        "created_at, updated_at, email) VALUES "
        "('shadow', 'x', 'member', 'active', '2026-01-01', '2026-01-01', ?)",
        (email,),
    )
    conn.commit()


def test_an_ambiguous_address_is_refused_and_provisions_nothing(
    conn, client, access_on
):
    """The round-5 critical: ambiguity must not read as absence.

    get_by_email once returned None for both "nobody" and "several", so
    access_user treated a duplicated address as a new person and provisioned —
    one fresh account per request, the person resolving to a different id each
    time, the ambiguity worsening with every call.
    """
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    create_user(
        conn,
        username="bob",
        password_hash=hash_password("irrelevant"),
        role="member",
        email="bob@example.com",
    )
    _dupe(conn, "bob@example.com")
    before = conn.execute("SELECT count(*) FROM users").fetchone()[0]
    access_on(lambda token: "bob@example.com")
    for _ in range(3):
        assert (
            client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "t"}).status_code
            == 401
        )
    after = conn.execute("SELECT count(*) FROM users").fetchone()[0]
    assert after == before, (
        f"provisioned into an ambiguous address: {before} -> {after}"
    )


def test_an_address_with_no_account_is_refused(conn, client, access_on):
    """Match-only: an unknown address does not become an account."""
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    before = conn.execute("SELECT count(*) FROM users").fetchone()[0]
    access_on(lambda token: "stranger@example.com")
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "t"})
    assert r.status_code == 401
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == before


def test_deleting_an_account_revokes_access(conn, client, access_on):
    """Deletion must be a revocation, not a pause.

    Under the provisioning variant the next request re-created the row, so
    DELETE /api/users/{id} destroyed the person's sessions and keys while
    leaving their access intact — and suspend-then-delete silently restored
    them as an active member.
    """
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    bob = create_user(
        conn,
        username="bob",
        password_hash=hash_password("irrelevant"),
        role="member",
        email="bob@example.com",
    )
    access_on(lambda token: "bob@example.com")
    assert (
        client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "t"}).status_code
        == 200
    )
    delete_user(conn, bob.id)
    r = client.get("/whoami", headers={"Cf-Access-Jwt-Assertion": "t"})
    assert r.status_code == 401, "a deleted account must not come back"
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_a_resolved_caller_is_role_bounded_not_scope_exempt(conn, access_on):
    """Pins the law's `scopes=None` constraint, which nothing covered.

    A surviving mutation setting scopes={"admin"} would 403 every Access
    caller off every api-scoped route, with the whole suite green.
    """
    app = FastAPI()

    @app.get("/data")
    def data(user: CurrentUser = Depends(require_api_scope)) -> dict[str, int]:
        return {"id": user.id}

    @app.get("/admin-only")
    def admin_only(user: CurrentUser = Depends(require_admin)) -> dict[str, int]:
        return {"id": user.id}

    attach_app_state(
        app.state, AppState(app_db_path=_db_path(conn), setup_state=SetupState())
    )
    create_user(
        conn,
        username="member",
        password_hash=hash_password("irrelevant"),
        role="member",
        email="member@example.com",
    )
    create_user(
        conn,
        username="boss",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="boss@example.com",
    )
    c = TestClient(app)
    h = {"Cf-Access-Jwt-Assertion": "t"}

    access_on(lambda token: "member@example.com")
    assert c.get("/data", headers=h).status_code == 200, (
        "role-bounded, not scope-exempt"
    )
    assert c.get("/admin-only", headers=h).status_code == 403, (
        "a member is not an admin"
    )

    # The ADMIN direction is where a non-None scope set actually bites. Any
    # scopes value makes _enforce apply the scope check, so an admin caller
    # would be 403'd off every admin surface -- user CRUD, settings, the index
    # routes -- which, where this path is the only usable credential, locks
    # every administrator out. Asserting only the member direction misses it:
    # a member is
    # refused on role grounds either way.
    access_on(lambda token: "boss@example.com")
    assert c.get("/data", headers=h).status_code == 200
    assert c.get("/admin-only", headers=h).status_code == 200, (
        "an admin must reach admin surfaces; any scope set locks them out"
    )


def test_a_plaintext_origin_is_allowed_on_a_plaintext_request(conn, client, access_on):
    """The scheme must be the REQUEST's, not a hardcoded https.

    Hardcoding https would refuse every state change on an http deployment —
    the failure the is_cross_site docstring's deployment-coupling paragraph
    warns about — while still passing the https tests.
    """
    create_user(
        conn,
        username="owner",
        password_hash=hash_password("irrelevant"),
        role="admin",
        email="owner@example.com",
    )
    access_on(lambda token: "owner@example.com")
    r = client.post(
        "http://testserver/change",
        headers={"Cf-Access-Jwt-Assertion": "tok", "Origin": "http://testserver"},
    )
    assert r.status_code == 200, r.text
