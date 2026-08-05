"""The panel refuses state-changing requests without a token.

The rest of the suite posts tokens automatically, which is convenient and would
also hide the guard failing open. These build their own client that does not,
so the guard is what is under test.

The attack this closes: the panel listens on localhost and the session cookie
is in the same browser as everything else, so any page open while the tunnel is
up could post to it — activating a cohort, retiring a question, or ending
somebody's participation, with nothing to show for it afterwards.
"""
import pytest
from flask import url_for
from flask.testing import FlaskClient

from admin import csrf
from admin.app import create_app
from core.enums import Status
from core.models import Cohort, User


def _unsafe_routes():
    """Every route that can change something, from the URL map rather than a
    list somebody has to remember to update."""
    app = create_app()
    routes = []

    with app.test_request_context():
        for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
            methods = rule.methods & csrf.UNSAFE_METHODS
            if not methods or rule.endpoint == "static":
                continue

            values = {
                name: "bot.log" if name == "name" else 1
                for name in rule.arguments
            }
            routes.append(url_for(rule.endpoint, **values))

    return sorted(set(routes))


UNSAFE_ROUTES = _unsafe_routes()


@pytest.fixture
def untrusting(app):
    """A client that fills nothing in — unlike the shared one."""
    app.test_client_class = FlaskClient
    client = app.test_client()
    client.get("/login")

    return client


@pytest.fixture
def signed_in(untrusting, password):
    """Signed in, but still not filling the token in afterwards."""
    with untrusting.session_transaction() as stored:
        token = stored[csrf.FIELD]

    untrusting.post("/login", data={"password": password, csrf.FIELD: token})

    return untrusting


@pytest.mark.parametrize("path", UNSAFE_ROUTES, ids=UNSAFE_ROUTES)
def test_every_state_changing_route_demands_a_token(signed_in, path):
    assert signed_in.post(path, data={}).status_code == 400


def test_the_route_list_is_not_empty():
    """A canary: if the URL map stopped yielding anything, the sweep above
    would pass by testing nothing."""
    assert len(UNSAFE_ROUTES) >= 10


def test_a_wrong_token_is_refused(signed_in):
    response = signed_in.post(
        "/cohorts/1/activate", data={csrf.FIELD: "not-the-right-one"},
    )

    assert response.status_code == 400


def test_a_refused_request_changes_nothing(signed_in, cohort):
    """The point of all of it."""
    Cohort.create(
        name="Друга", is_active=False, enrollment_opens="2026-01-01",
        enrollment_closes="2026-01-14", duration_days=30, max_people=10,
        questions_per_day=3, category_order="0", status=0,
    )
    second = Cohort.select().order_by(Cohort.id.desc()).first()

    signed_in.post(f"/cohorts/{second.id}/activate", data={})

    assert Cohort.get_by_id(second.id).is_active is False
    assert Cohort.get_by_id(cohort.id).is_active is True


def test_a_refused_request_cannot_end_somebody_s_participation(signed_in, cohort, make_user):
    user = make_user(telegram_id=1234)

    signed_in.post(f"/users/{user.telegram_id}/action", data={"action": "stop"})

    assert User.get_by_id(user.telegram_id).status == Status.ACTIVE


def test_reads_need_no_token(signed_in):
    for path in ("/", "/users", "/questions", "/cohorts", "/logs"):
        assert signed_in.get(path).status_code == 200


def test_the_refusal_looks_like_the_panel(signed_in):
    body = signed_in.post("/cohorts/1/activate", data={}).get_data(as_text=True)

    assert "Форма застаріла" in body
    assert "Я хочу бот" in body


# --- the token itself ------------------------------------------------------

def test_forms_carry_a_token(client, questions):
    body = client.get("/questions").get_data(as_text=True)

    assert 'name="csrf_token"' in body


def test_the_login_form_carries_one_too(untrusting):
    assert 'name="csrf_token"' in untrusting.get("/login").get_data(as_text=True)


def test_the_token_is_stable_within_a_session(untrusting):
    with untrusting.session_transaction() as stored:
        first = stored[csrf.FIELD]

    untrusting.get("/login")

    with untrusting.session_transaction() as stored:
        assert stored[csrf.FIELD] == first


def test_two_sessions_get_different_tokens(app):
    app.test_client_class = FlaskClient

    tokens = []
    for _ in range(2):
        client = app.test_client()
        client.get("/login")
        with client.session_transaction() as stored:
            tokens.append(stored[csrf.FIELD])

    assert tokens[0] != tokens[1]
