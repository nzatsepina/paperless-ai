"""Identity resolution for the verified reverse-proxy credential path.

Extracted from :mod:`search.deps`, which had grown past CODE_GUIDELINES §3.1's
500-line ceiling. The split is by responsibility, not size: everything here
answers "which person is this, and may they act", while `deps` keeps the
FastAPI dependency wiring that consumes the answer.

Allowed deps: sqlite3, structlog, fastapi.Request, appdb, search.sessions.
Forbidden: search.deps (the dependency runs the other way).
"""

from __future__ import annotations

import sqlite3

import structlog
from fastapi import Request

from appdb import users as user_store
from appdb.users import AmbiguousEmailError
from search.sessions import CurrentUser

log = structlog.get_logger(__name__)


#: Methods that can change state, and therefore need CSRF protection.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_cross_site(request: Request) -> bool:
    """Return whether *request* was initiated by a different site.

    The cookie path's CSRF defence is ``SameSite=Strict`` on the application's
    own cookie (the spec's §4.4, as `search.cookies` records). The Access path is **not** authenticated
    by that cookie, so that defence does not apply to it, and the proxy's own
    cookie policy is outside this repository's control. Without this check a
    plain cross-site ``<form method=post>`` — a simple request, so no preflight
    stops it — could reach a destructive endpoint with the visitor's proxy
    credentials attached.

    Two signals, either sufficient. ``Sec-Fetch-Site`` is the browser's own
    statement and is not spoofable from page script; ``Origin`` is the older
    signal and is sent on cross-site form posts. A request carrying neither is
    treated as same-site: non-browser clients (curl, scripts) send neither, and
    they are not the CSRF threat — CSRF needs a browser holding credentials.

    **Deployment coupling, stated because it is invisible otherwise.** The
    scheme comes from ``request.url.scheme``, which is only ``https`` when
    uvicorn's ``proxy_headers`` trusts the peer — i.e. when
    ``SEARCH_FORWARDED_ALLOW_IPS`` includes the proxy. Pin it wrongly and the
    scheme stays ``http`` while browsers send an ``https`` origin, so **every**
    state-changing request is refused, application-wide, with a log line that
    says "cross-site" and gives no hint of the real cause.

    Args:
        request: The incoming request.

    Returns:
        ``True`` when the request demonstrably came from another site.
    """
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in ("same-origin", "same-site", "none"):
        return True
    origin = request.headers.get("origin")
    if origin:
        # Compare scheme AND authority against THIS request's own scheme.
        # An earlier attempt built both schemes and accepted either, which is
        # no check at all: http://host matched https://host, exactly the case
        # the comment claimed to reject. uvicorn runs with proxy_headers=True,
        # so request.url.scheme is derived from X-Forwarded-Proto and reflects
        # what the client actually spoke to the edge.
        host = request.headers.get("host", "")
        return origin != f"{request.url.scheme}://{host}"
    return False


def access_user(app_db: sqlite3.Connection, email: str) -> CurrentUser | None:
    """Resolve the account holding a verified *email*, or ``None``.

    **Match only — this never creates an account.** Six rounds of review on the
    provisioning variant produced, in order: an ambiguous address read as
    absence and provisioned on every request; a nested race ladder; a username
    derivation with three separate contract breaches; two guards in the account
    routes to stop an admin creating the state that broke it; a refusal needed
    to stop provisioning defeating first-run admin bootstrap; and deletion
    silently not being a revocation, because the next request re-created the
    row. Every one of those is downstream of creating accounts here. The
    verification, the CSRF check, the not-active check and the tried-first
    ordering never produced a finding.

    Zero-touch onboarding is not offered, and the cost of doing without it is
    one row an administrator creates once per person. In exchange, the set of people
    who can authenticate is bounded by accounts someone deliberately made,
    rather than by a proxy-side policy this repository cannot read — and
    deleting an account becomes a real revocation.

    Returns ``None`` — so the caller falls through to the cookie and bearer
    paths, ending in 401 — when the address is blank, holds no account, is
    ambiguous, or belongs to an account that is not active. A miss is logged so
    an admin can see who is asking and add them.

    Args:
        app_db: An open ``app.db`` connection.
        email: The verified address from the assertion.

    Returns:
        The resolved user projected for the route layer, or ``None``.
    """
    address = email.strip().lower()
    try:
        # get_by_email applies the same fold and its own blank guard; the local
        # normalisation exists only so the log lines below read consistently.
        row = user_store.get_by_email(app_db, address)
    except AmbiguousEmailError:
        # Two accounts hold this address. Refuse: an identity that resolves to
        # more than one row is not an identity.
        log.warning("search.access_ambiguous_email", email=address)
        return None
    if row is None:
        # The signal an admin needs to onboard someone. Not an error.
        log.info("search.access_no_account", email=address)
        return None
    if row.status != "active":
        log.warning("search.access_user_not_active", email=address)
        return None
    return CurrentUser(
        id=row.id,
        username=row.username,
        role=row.role,
        display_name=row.display_name,
    )
