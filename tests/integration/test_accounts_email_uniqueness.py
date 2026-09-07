"""An email address must identify at most one account.

`users.email` carries no `UNIQUE` constraint, and the reverse-proxy credential
path resolves people BY email — so two rows sharing an address make that
address ambiguous, which fails closed and locks that person out. These pin the
two handlers that can create the state.
"""

from __future__ import annotations

import pytest

from tests.integration.accounts_helpers import (
    build_account_client,
    login,
    make_settings,
    open_app_db,
    seed_admin,
    seed_store,
    seed_user,
)
from store.reader import StoreReader


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path)
    seed_store(settings)
    app_db = open_app_db(tmp_path)
    store_reader = StoreReader(settings)
    client = build_account_client(settings, app_db, store_reader)
    seed_admin(app_db, username="admin", password="admin-password")
    assert login(client, username="admin", password="admin-password").status_code == 200
    try:
        yield client, app_db
    finally:
        store_reader.close()
        app_db.close()


def test_creating_a_user_with_a_taken_address_is_refused(env):
    client, app_db = env
    seed_user(app_db, username="bob", password="bob-password", role="member")
    app_db.execute(
        "UPDATE users SET email = ? WHERE username = ?", ("bob@example.com", "bob")
    )
    app_db.commit()
    r = client.post(
        "/api/users",
        json={
            "username": "bob2",
            "password": "another-password",
            "role": "member",
            "email": "BOB@example.com",
        },
    )
    assert r.status_code == 409, r.text
    assert "already in use" in r.json()["detail"]


def test_moving_an_address_onto_another_account_is_refused(env):
    client, app_db = env
    bob = seed_user(app_db, username="bob", password="bob-password", role="member")
    carol = seed_user(
        app_db, username="carol", password="carol-password", role="member"
    )
    app_db.execute(
        "UPDATE users SET email = ? WHERE id = ?", ("bob@example.com", bob.id)
    )
    app_db.commit()
    r = client.patch(f"/api/users/{carol.id}", json={"email": "bob@example.com"})
    assert r.status_code == 409, r.text


def test_keeping_your_own_address_is_allowed(env):
    """The guard must not refuse an account its own address."""
    client, app_db = env
    bob = seed_user(app_db, username="bob", password="bob-password", role="member")
    app_db.execute(
        "UPDATE users SET email = ? WHERE id = ?", ("bob@example.com", bob.id)
    )
    app_db.commit()
    r = client.patch(
        f"/api/users/{bob.id}", json={"email": "bob@example.com", "display_name": "Bob"}
    )
    assert r.status_code == 200, r.text
