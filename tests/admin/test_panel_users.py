"""The participant list, one participant's page, and the status actions.

These four buttons are the only way Ксенія changes somebody's state by hand,
and two of them are one-way — so what each does is worth stating.
"""
import pytest

from core import clock
from core.enums import Status
from core.models import Answer, User


def test_the_list_shows_every_participant(client, cohort, make_user):
    first = make_user(telegram_id=801)
    second = make_user(telegram_id=802, status=Status.FINISHED)

    body = client.get("/users").get_data(as_text=True)

    assert first.name in body
    assert second.name in body
    assert "ACTIVE" in body
    assert "FINISHED" in body


def test_the_list_reports_answered_and_skipped_counts(client, cohort, questions, make_user):
    user = make_user(telegram_id=803)
    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="радість", cycle_day=1,
    )
    Answer.create(
        user=user, question=questions[1], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), skipped=True, cycle_day=1,
    )

    response = client.get("/users")

    assert response.status_code == 200


def test_a_participants_answers_appear_on_their_page(client, cohort, questions, make_user):
    user = make_user(telegram_id=804)
    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="натхнення", cycle_day=4,
    )

    body = client.get(f"/users/{user.telegram_id}").get_data(as_text=True)

    assert "натхнення" in body
    assert questions[0].text in body


def test_an_unanswered_question_shows_as_waiting(client, cohort, questions, make_user):
    user = make_user(telegram_id=805)
    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(), cycle_day=2,
    )

    body = client.get(f"/users/{user.telegram_id}").get_data(as_text=True)

    assert "чекає" in body


# --- status actions --------------------------------------------------------

@pytest.mark.parametrize(
    "action,expected",
    [
        ("pause", Status.PAUSED),
        ("finish", Status.FINISHED),
        ("stop", Status.STOPPED),
    ],
)
def test_status_action(client, cohort, make_user, action, expected):
    user = make_user(telegram_id=806)

    response = client.post(f"/users/{user.telegram_id}/action", data={"action": action})

    assert response.status_code == 302
    assert response.headers["Location"] == f"/users/{user.telegram_id}"
    assert User.get_by_id(user.telegram_id).status == expected


def test_pausing_records_when_the_pause_started(client, cohort, make_user):
    user = make_user(telegram_id=807)

    client.post(f"/users/{user.telegram_id}/action", data={"action": "pause"})

    assert User.get_by_id(user.telegram_id).paused_at is not None


def test_resuming_banks_the_paused_days(client, cohort, make_user, frozen_clock):
    user = make_user(telegram_id=808, started_days_ago=5)
    client.post(f"/users/{user.telegram_id}/action", data={"action": "pause"})

    frozen_clock(days=2)
    client.post(f"/users/{user.telegram_id}/action", data={"action": "resume"})

    user = User.get_by_id(user.telegram_id)
    assert user.status == Status.ACTIVE
    assert user.paused_at is None
    assert user.paused_days == 2


def test_pausing_closes_anything_left_open(client, cohort, questions, make_user):
    """A pause should not leave a question hanging against the paused days."""
    user = make_user(telegram_id=809)
    answer = Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(), cycle_day=1,
    )

    client.post(f"/users/{user.telegram_id}/action", data={"action": "pause"})

    assert Answer.get_by_id(answer.id).skipped is True


def test_an_unknown_action_is_refused(client, cohort, make_user):
    user = make_user(telegram_id=810)

    response = client.post(
        f"/users/{user.telegram_id}/action", data={"action": "delete-everything"},
    )

    assert response.status_code == 400
    assert User.get_by_id(user.telegram_id).status == Status.ACTIVE


def test_an_action_on_an_unknown_user_is_a_404(client):
    assert client.post("/users/999/action", data={"action": "pause"}).status_code == 404
