"""Nothing in the panel is reachable without the password.

The panel holds participants' names, intentions and free-text reflections, and
it can delete as well as read — so the guard covering *every* route matters
more than any single page working.
"""
import pytest
from flask import url_for

from admin.app import create_app


def _every_protected_route():
    """Every route the panel exposes, as (method, url) pairs.

    Read off the URL map rather than listed by hand, so a route added later is
    covered by the guard test below without anyone remembering to add it.
    `login` is the way in and `logout` deliberately works for anyone, so both
    are checked separately.
    """
    app = create_app()
    routes = []

    with app.test_request_context():
        for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
            if rule.endpoint in {"static", "login", "logout"}:
                continue

            # `logs_download` takes a filename; everything else takes an id.
            values = {
                name: "bot.log" if name == "name" else 1
                for name in rule.arguments
            }

            method = "GET" if "GET" in rule.methods else "POST"
            routes.append((method, url_for(rule.endpoint, **values)))

    return routes


PROTECTED_ROUTES = _every_protected_route()


@pytest.mark.parametrize(
    "method,path",
    PROTECTED_ROUTES,
    ids=[f"{method} {path}" for method, path in PROTECTED_ROUTES],
)
def test_anonymous_request_is_sent_to_the_login_page(anon, method, path):
    response = anon.open(path, method=method)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_the_panel_exposes_the_routes_we_think_it_does():
    """A canary on the loop above: if the URL map were empty, every guard test
    would vacuously pass."""
    assert len(PROTECTED_ROUTES) >= 20


def test_login_page_renders(anon):
    response = anon.get("/login")

    assert response.status_code == 200
    assert "Я хочу бот" in response.get_data(as_text=True)


def test_correct_password_authenticates(anon, password):
    response = anon.post("/login", data={"password": password})

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert anon.get("/").status_code == 200


def test_wrong_password_is_refused(anon):
    response = anon.post("/login", data={"password": "not it"})

    assert response.status_code == 200
    assert "Wrong password." in response.get_data(as_text=True)

    # And it really did not authenticate.
    assert anon.get("/").status_code == 302


def test_login_returns_you_to_where_you_were_headed(anon, password):
    landing = anon.get("/users")
    assert "next=" in landing.headers["Location"]

    response = anon.post("/login?next=/users", data={"password": password})

    assert response.headers["Location"] == "/users"


@pytest.mark.parametrize(
    "target",
    ["https://example.invalid/phish", "//example.invalid", "http://example.invalid"],
)
def test_login_will_not_bounce_you_off_site(anon, password, target):
    """`next` is read straight out of the URL, so a crafted link could
    otherwise send the admin elsewhere the moment they typed the password. A
    leading `//` is protocol-relative and leaves the site too."""
    response = anon.post(f"/login?next={target}", data={"password": password})

    assert response.headers["Location"] == "/"


def test_logout_ends_the_session(client):
    assert client.get("/").status_code == 200

    response = client.get("/logout")

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert client.get("/").status_code == 302


# --- the signing key -------------------------------------------------------

def test_the_signing_key_is_stable_across_restarts(monkeypatch, log_dir):
    monkeypatch.setenv("ADMIN_SECRET_KEY", "a-stable-key")

    assert create_app().secret_key == create_app().secret_key == "a-stable-key"


def test_without_a_key_every_build_invents_a_new_one(monkeypatch, log_dir):
    """Which is exactly why `admin_panel.py` refuses to start that way — it
    means every restart signs sessions differently and logs the admin out."""
    monkeypatch.delenv("ADMIN_SECRET_KEY", raising=False)

    assert create_app().secret_key != create_app().secret_key


def test_the_panel_refuses_to_start_without_a_signing_key(monkeypatch):
    import admin_panel

    monkeypatch.setenv("ADMIN_PANEL_PASSWORD", "something")
    monkeypatch.delenv("ADMIN_SECRET_KEY", raising=False)
    # Neither belongs in a test process: one attaches handlers to the root
    # logger for good, the other would open the real goalbot.db.
    monkeypatch.setattr(admin_panel, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(admin_panel, "initialize_database", lambda: None)

    with pytest.raises(SystemExit) as refused:
        admin_panel.main()

    assert "ADMIN_SECRET_KEY" in str(refused.value)
    assert "token_hex" in str(refused.value), "say how to make one"


def test_the_panel_refuses_to_start_without_a_password(monkeypatch):
    import admin_panel

    monkeypatch.delenv("ADMIN_PANEL_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_SECRET_KEY", "a-stable-key")
    monkeypatch.setattr(admin_panel, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(admin_panel, "initialize_database", lambda: None)

    with pytest.raises(SystemExit) as refused:
        admin_panel.main()

    assert "ADMIN_PANEL_PASSWORD" in str(refused.value)


def test_login_says_so_when_no_password_is_configured(anon, monkeypatch):
    """`admin_panel.py` refuses to start without one, but the route is what
    actually gates access — so it must not fall open if the variable is ever
    unset underneath a running process."""
    monkeypatch.delenv("ADMIN_PANEL_PASSWORD")

    response = anon.get("/login")

    assert response.status_code == 200
    assert "ADMIN_PANEL_PASSWORD is not set." in response.get_data(as_text=True)


def test_no_password_configured_cannot_be_bypassed_with_a_blank_one(anon, monkeypatch):
    monkeypatch.delenv("ADMIN_PANEL_PASSWORD")

    anon.post("/login", data={"password": ""})

    assert anon.get("/").status_code == 302
