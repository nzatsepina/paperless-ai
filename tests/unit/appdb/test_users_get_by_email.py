"""Tests for appdb.users.get_by_email — the identity anchor of the Access path.

Three behaviours carry weight here and none had a test: the fold must be
Python-side and must NOT over-merge distinct mailboxes; a blank or NULL stored
address must never match; and an ambiguous address must fail closed rather
than resolve to whichever row the query planner returned first.
"""

from __future__ import annotations

import pytest

from appdb.connection import connect
from appdb.passwords import hash_password
from appdb.schema import ensure_schema
from appdb.users import create as create_user
from appdb.users import AmbiguousEmailError, get_by_email


@pytest.fixture
def conn(tmp_path):
    c = connect(str(tmp_path / "app.db"))
    ensure_schema(c)
    yield c
    c.close()


def _seed(conn, username, email, role="member"):
    return create_user(
        conn,
        username=username,
        password_hash=hash_password("irrelevant"),
        role=role,
        email=email,
    )


def test_matches_case_insensitively(conn):
    user = _seed(conn, "her", "Her.Name@Example.COM")
    assert get_by_email(conn, "her.name@example.com").id == user.id


def test_matches_non_ascii_case(conn):
    """SQLite's lower() is ASCII-only; the fold must happen in Python."""
    user = _seed(conn, "mueller", "MÜLLER@example.com")
    assert get_by_email(conn, "müller@example.com").id == user.id


def test_does_not_merge_distinct_mailboxes(conn):
    """casefold would map straße to strasse and ſam to sam. lower does not.

    Merging them on a credential path resolves one person's assertion onto
    another person's row.
    """
    _seed(conn, "strasse", "strasse@example.com")
    sharp = _seed(conn, "sharp", "straße@example.com")
    assert get_by_email(conn, "straße@example.com").id == sharp.id
    _seed(conn, "sam", "sam@example.com")
    assert get_by_email(conn, "ſam@example.com") is None


def test_blank_and_missing_addresses_never_match(conn):
    _seed(conn, "noemail", None)
    _seed(conn, "blank", "")
    assert get_by_email(conn, "") is None
    assert get_by_email(conn, "   ") is None
    assert get_by_email(conn, "anything@example.com") is None


def test_an_ambiguous_address_raises(conn):
    """Two rows sharing an address must RAISE, not return None.

    users.email carries no UNIQUE constraint, so this state is reachable.
    Returning an arbitrary row would make identity depend on the query plan;
    returning None would be worse still — it is indistinguishable from "no
    such address", and a caller that provisions on absence would then
    provision on ambiguity, adding an account per request.
    """
    _seed(conn, "first", "shared@example.com")
    conn.execute(
        "INSERT INTO users (username, password_hash, role, status, "
        "created_at, updated_at, email) VALUES "
        "('second', 'x', 'admin', 'active', '2026-01-01', '2026-01-01', "
        "'shared@example.com')"
    )
    conn.commit()
    with pytest.raises(AmbiguousEmailError):
        get_by_email(conn, "shared@example.com")


def test_a_null_email_row_is_not_matched_by_the_string_none(conn):
    """Pins the WHERE filter, which nothing else reaches.

    The Python-side comparison coerces a NULL column with str(), so a row
    with no address folds to the literal "none". Drop the SQL filter and the
    address "none" resolves to that row — which on a fresh deployment is the
    admin. The blank-input tests cannot catch this: they short-circuit before
    the query runs.
    """
    admin = create_user(
        conn,
        username="admin",
        password_hash=hash_password("irrelevant"),
        role="admin",
    )
    assert admin.email is None
    assert get_by_email(conn, "none") is None
    assert get_by_email(conn, "None") is None
