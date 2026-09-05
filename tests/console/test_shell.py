"""Getting into the console, and being kept out of it.

The console is the one place in Tessera where data becomes reachable from something
other than a private process. The engine's token protects every route, but a browser
navigating to a URL cannot set a header — so the console trades the token for a cookie,
and a cookie is presented automatically, which is both the point and the risk.

These tests are about that trade and the two defences around it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tessera.api.app import create_app
from tessera.api.console import CONSOLE_COOKIE

TOKEN = "a-known-engine-token"


@pytest.fixture
def guarded(engine: Engine) -> Iterator[TestClient]:
    """A console behind a real token, addressed the way a browser addresses it.

    `base_url` matters: the default `testserver` is not a local host, so every request
    would be refused by the rebinding guard before reaching anything worth testing.
    """
    app = create_app(engine=engine, token=TOKEN, configure_logs=False)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


class TestGettingIn:
    def test_a_browser_with_nothing_is_refused(self, guarded: TestClient) -> None:
        assert guarded.get("/console/rooms").status_code == 401

    def test_the_token_in_the_url_is_traded_for_a_cookie(self, guarded: TestClient) -> None:
        """One entry in history rather than one per page: the token appears in a URL
        once, is exchanged, and the browser is sent somewhere clean."""
        response = guarded.get(f"/console?token={TOKEN}", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == "/console/"
        assert response.cookies[CONSOLE_COOKIE] == TOKEN

    def test_the_cookie_then_opens_every_page(self, guarded: TestClient) -> None:
        guarded.get(f"/console?token={TOKEN}")

        assert guarded.get("/console/rooms").status_code == 200

    def test_the_cookie_cannot_be_read_by_a_script(self, guarded: TestClient) -> None:
        response = guarded.get(f"/console?token={TOKEN}", follow_redirects=False)

        header = response.headers["set-cookie"].lower()
        assert "httponly" in header

    def test_the_cookie_is_not_sent_across_sites(self, guarded: TestClient) -> None:
        """`SameSite=Strict` is what stops a page the user is visiting from posting to
        the console with the session attached."""
        response = guarded.get(f"/console?token={TOKEN}", follow_redirects=False)

        assert "samesite=strict" in response.headers["set-cookie"].lower()

    def test_the_exchange_does_not_leak_the_token_onward(self, guarded: TestClient) -> None:
        response = guarded.get(f"/console?token={TOKEN}", follow_redirects=False)

        assert response.headers["Referrer-Policy"] == "no-referrer"

    def test_a_wrong_token_gets_nowhere(self, guarded: TestClient) -> None:
        guarded.cookies.set(CONSOLE_COOKIE, "not-the-token")

        assert guarded.get("/console/rooms").status_code == 401

    def test_the_query_token_works_on_the_entry_path_and_nowhere_else(
        self, guarded: TestClient
    ) -> None:
        """The narrow part of the exchange, and the easiest thing to widen by accident.

        A token in a query string lands in browser history, server logs and proxy logs.
        Accepting it once, on the path whose only job is to trade it for a cookie, is a
        single entry. Accepting it everywhere would be one per page — the difference
        between a key handed over at the door and a key written on every wall.

        Written after the guard was mutated to accept it everywhere and **nothing
        failed**.

        The refusals are asserted *before* the exchange, because the exchange leaves a
        cookie on the client and every request after it would then be authentic for a
        reason that has nothing to do with the query string.
        """
        assert guarded.get(f"/console/rooms?token={TOKEN}").status_code == 401
        assert guarded.get(f"/api/v1/rooms?token={TOKEN}").status_code == 401

        assert guarded.get(f"/console?token={TOKEN}", follow_redirects=False).status_code == 303


class TestComingBackAfterARestart:
    """A token is issued per engine launch, so yesterday's cookie is not today's token.

    Found by running a browser against a restarted engine (4.8 ②d): the cookie was read
    before the query string, so the stale one shadowed the fresh token in the entry link and
    the console answered **401 to the only URL that could have fixed it**. The way out was to
    clear site data, which is not something an application can ask somebody to do.
    """

    def test_a_fresh_token_gets_in_past_a_stale_cookie(self, guarded: TestClient) -> None:
        guarded.cookies.set(CONSOLE_COOKIE, "the-token-from-a-previous-launch")

        response = guarded.get(f"/console?token={TOKEN}", follow_redirects=False)

        assert response.status_code == 303
        assert response.cookies[CONSOLE_COOKIE] == TOKEN

    def test_a_stale_cookie_alone_is_still_refused(self, guarded: TestClient) -> None:
        """The fix widens what gets *in* on one path, not what counts as authentic."""
        guarded.cookies.set(CONSOLE_COOKIE, "the-token-from-a-previous-launch")

        assert guarded.get("/console/rooms").status_code == 401

    def test_a_wrong_token_in_the_url_does_not_get_in_either(self, guarded: TestClient) -> None:
        assert guarded.get("/console?token=not-the-token").status_code == 401


class TestTheRebindingGuard:
    """`SameSite` cannot see the case where the attacker's own domain resolves to
    loopback — the browser considers that same-site, because it is. Only the `Host`
    header distinguishes it.

    **The guard covered `/console` alone until 4.8**, which measured what that was worth: with
    the session cookie set and `Host: evil.example`, `/console/rooms` answered 403 and
    `/api/v1/rooms` answered **200** — the same data on the same socket, one defence short,
    while #65 recorded the console as the only place data left a private process. It was not.

    Not a live hole, and the tests say which part is which: the cookie is host-only, so a
    browser rebound to another domain sends that domain's jar and arrives with no token at
    all. The token is what stops the attack. This is the second line, on both paths now.
    """

    def test_a_foreign_host_is_refused(self, guarded: TestClient) -> None:
        guarded.get(f"/console?token={TOKEN}")

        response = guarded.get("/console/rooms", headers={"Host": "evil.example"})

        assert response.status_code == 403

    def test_it_is_refused_before_the_token_is_even_considered(self, guarded: TestClient) -> None:
        """403 rather than 401: the request never reaches the token check, so a
        misconfigured host cannot be probed for whether a token was valid."""
        response = guarded.get("/console/rooms", headers={"Host": "evil.example"})

        assert response.status_code == 403

    def test_localhost_and_loopback_are_both_served(self, engine: Engine) -> None:
        for host in ("localhost", "127.0.0.1"):
            app = create_app(engine=engine, token=TOKEN, configure_logs=False)
            with TestClient(app, base_url=f"http://{host}") as client:
                client.get(f"/console?token={TOKEN}")
                assert client.get("/console/rooms").status_code == 200, host

    def test_a_port_on_the_host_header_is_ignored(self, guarded: TestClient) -> None:
        guarded.get(f"/console?token={TOKEN}")

        response = guarded.get("/console/rooms", headers={"Host": "127.0.0.1:54321"})

        assert response.status_code == 200

    def test_the_api_is_behind_the_same_guard(self, guarded: TestClient) -> None:
        """4.8 puts a browser page in front of `/api/v1` for the first time, and the console
        answering 403 where the API answered 200 was an asymmetry rather than a policy."""
        guarded.get(f"/console?token={TOKEN}")

        response = guarded.get("/api/v1/rooms", headers={"Host": "evil.example"})

        assert response.status_code == 403

    def test_a_legitimate_client_is_unaffected(self, guarded: TestClient) -> None:
        """The Swift client and `curl` both send the loopback name they dialled, so widening
        the guard costs nothing that exists. A deployment binding beyond loopback has to widen
        `ALLOWED_HOSTS`, which is Stage 7's to do."""
        guarded.get(f"/console?token={TOKEN}")

        assert guarded.get("/api/v1/rooms").status_code == 200

    def test_the_docs_are_behind_it_too(self, guarded: TestClient) -> None:
        """`/openapi.json` needs no token — the surface is public knowledge — but it is still
        served by this engine, and a guard with an exception is a guard with a way round it."""
        response = guarded.get("/openapi.json", headers={"Host": "evil.example"})

        assert response.status_code == 403


class TestTemplatesTravel:
    def test_the_templates_directory_is_found(self) -> None:
        """Unfrozen this is trivially true. It is asserted because the frozen case —
        where PyInstaller unpacks data under `sys._MEIPASS` rather than beside the
        source — is the one that breaks, and `packaging/smoke-test.sh` checks that half
        against a real `.dmg`."""
        from tessera.paths import templates_directory

        assert (templates_directory() / "base.html").exists()

    def test_the_migrations_resolver_still_agrees(self) -> None:
        """`engine.migrations_directory` was rewritten to call `paths` in 2.5. Migrations
        are how a project file is opened at all, so a mistake here is total."""
        from tessera.engine import migrations_directory

        assert (migrations_directory() / "env.py").exists()
