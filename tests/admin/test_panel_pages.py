"""Every page renders — on an empty database and on a populated one.

The empty case is the one that catches most things: a fresh install has no
cohort, no questions and no users, and several views reach for all three.
"""
import pytest

from core import clock
from core.enums import Status
from core.models import Answer, FinalAnswer, User

# Pages that take no id, so they can be listed once and used for both states.
PAGES = [
    "/",
    "/questions",
    "/questions?view=final",
    "/questions/new",
    "/cohorts",
    "/cohorts/new",
    "/users",
    "/logs",
    "/logs/tail",
    "/export/users.csv",
    "/export/answers.csv",
]


@pytest.fixture
def populated(cohort, questions, make_user):
    """A cohort, the sample question bank, and one participant with history —
    an answer, a skip, and a completed closing block."""
    user = make_user(telegram_id=501, slots=(9,))

    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="радість", cycle_day=1,
        slot="09:00", category_index=0, message_id=11,
    )
    Answer.create(
        user=user, question=questions[1], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), skipped=True, cycle_day=1,
        slot="09:00", category_index=1, message_id=12,
    )
    FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), answered_at=clock.now_kyiv(),
        answer="Було добре", message_text="1. Що ти краще зрозуміла?",
        message_id=13,
    )

    return user


@pytest.mark.parametrize("path", PAGES)
def test_page_renders_on_an_empty_database(client, path):
    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", PAGES)
def test_page_renders_with_data(client, populated, path):
    assert client.get(path).status_code == 200


def test_dashboard_reports_the_cohort_and_the_day(client, populated):
    body = client.get("/").get_data(as_text=True)

    assert "Пілот" in body
    assert "ACTIVE" in body


def test_questions_page_lists_the_bank(client, questions):
    body = client.get("/questions").get_data(as_text=True)

    assert questions[0].text in body


def test_questions_page_shows_follow_ups_under_their_parent(client, questions):
    parent = next(question for question in questions if question.follow_ups)
    follow_up = list(parent.follow_ups)[0]

    body = client.get("/questions").get_data(as_text=True)

    assert follow_up.text in body


def test_final_view_lists_the_closing_questions(client, questions):
    from core.models import FinalQuestion

    body = client.get("/questions?view=final").get_data(as_text=True)

    assert FinalQuestion.select().first().text in body


def test_question_form_renders_for_an_existing_question(client, questions):
    response = client.get(f"/questions/{questions[0].id}")

    assert response.status_code == 200
    assert questions[0].text in response.get_data(as_text=True)


def test_cohort_form_renders_for_an_existing_cohort(client, cohort):
    response = client.get(f"/cohorts/{cohort.id}")

    assert response.status_code == 200
    assert cohort.name in response.get_data(as_text=True)


def test_user_detail_renders_for_a_participant(client, populated):
    response = client.get(f"/users/{populated.telegram_id}")

    assert response.status_code == 200
    assert "радість" in response.get_data(as_text=True)


# --- missing rows ----------------------------------------------------------

@pytest.mark.parametrize("path", ["/questions/999", "/cohorts/999", "/users/999"])
def test_unknown_id_is_a_404(client, path):
    assert client.get(path).status_code == 404


def test_a_missing_page_still_looks_like_the_panel(client):
    body = client.get("/questions/999").get_data(as_text=True)

    assert "Сторінки немає." in body
    assert "Я хочу бот" in body  # the shared layout, not a bare Werkzeug page


def test_an_unexpected_error_is_shown_and_logged(app, password, caplog):
    """There used to be no handler at all: an exception in a route gave a bare
    Werkzeug 500 and left no trace in the log the panel itself serves."""

    @app.route("/deliberately-broken")
    def broken():
        raise RuntimeError("something gave way")

    # TESTING re-raises so failures surface in the test; turn it off to let the
    # handler actually run, which is what happens in production.
    app.config["TESTING"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    client = app.test_client()
    client.post("/login", data={"password": password})

    response = client.get("/deliberately-broken")

    assert response.status_code == 500
    assert "Щось пішло не так" in response.get_data(as_text=True)
    assert "Unhandled error in the admin panel" in caplog.text


# --- users with no cohort --------------------------------------------------

@pytest.fixture
def waitlisted():
    """Exactly what `/start` creates when enrollment is closed or full:
    `put_on_waitlist` sets `cohort = None` deliberately."""
    return User.create(
        telegram_id=777, status=Status.WAITLIST, cohort=None,
    )


def test_user_list_renders_with_a_waitlisted_user(client, waitlisted):
    response = client.get("/users")

    assert response.status_code == 200
    assert "WAITLIST" in response.get_data(as_text=True)


def test_detail_page_of_a_waitlisted_user_renders(client, waitlisted):
    """`cycle_length` is read from the cohort and raises without one, which is
    the normal state for WAITLIST, DECLINED and ONBOARDING — and the users list
    links every one of them here."""
    response = client.get(f"/users/{waitlisted.telegram_id}")

    assert response.status_code == 200
    assert "WAITLIST" in response.get_data(as_text=True)


def test_detail_page_of_a_user_still_onboarding_renders(client):
    User.create(telegram_id=778, status=Status.ONBOARDING, cohort=None)

    assert client.get("/users/778").status_code == 200
