"""A participant outside a cohort.

Cycle length, the daily total, and the category rhythm live on the cohort, so
there are no answers for someone without one. Nothing substitutes a default —
it raises, and every query that drives the cycle filters such a user out long
before that can happen.
"""
import pytest

from core import clock
from core.enums import Status
from core.errors import CohortMissing
from core.models import Answer, User
from core.services.cohort import active_participants
from core.services.cycle import users_due_for_completion
from core.services.questions import (
    category_order_for, daily_total_for, next_question_for,
)
from bot.scheduler import send_due_questions, users_due_at


@pytest.fixture
def stray(make_user):
    """An ACTIVE user with no cohort — the state that should never exist."""
    user = make_user(telegram_id=500, slots=(9,))
    user.cohort = None
    user.save()

    return User.get_by_id(user.telegram_id)


# --- it raises rather than guessing ----------------------------------------

def test_cycle_length_raises(stray):
    with pytest.raises(CohortMissing):
        stray.cycle_length


def test_category_order_raises(stray):
    with pytest.raises(CohortMissing):
        category_order_for(stray)


def test_daily_total_raises(stray):
    with pytest.raises(CohortMissing):
        daily_total_for(stray)


def test_the_error_names_the_user_and_what_was_needed(stray):
    with pytest.raises(CohortMissing) as raised:
        daily_total_for(stray)

    assert "500" in str(raised.value)
    assert "daily question total" in str(raised.value)


# --- and is unreachable through the normal path ----------------------------

def test_a_user_without_a_cohort_is_not_an_active_participant(stray, make_user):
    proper = make_user(telegram_id=1)

    ids = [user.telegram_id for user in active_participants()]

    assert proper.telegram_id in ids
    assert stray.telegram_id not in ids


def test_the_scheduler_never_picks_them_up(stray):
    """They hold a 09:00 slot and are ACTIVE, and are still not due."""
    assert stray.status == Status.ACTIVE
    assert [row.time.hour for row in stray.times] == [9]
    assert users_due_at(9) == []


def test_completion_sweep_skips_them(stray):
    assert stray not in users_due_for_completion()


# --- a cohort with no usable rhythm ----------------------------------------

def test_empty_category_order_sends_nothing_rather_than_dividing_by_zero(
        cohort, questions, make_user):
    """Nothing falls back to a default order any more, so the length can be
    zero — and every step of the rotation divides by it."""
    cohort.category_order = "не число"
    cohort.save()

    user = make_user()
    assert user.cohort.categories == []

    # Before any answer, and after one — the second is the path that used to
    # reach `% len(order)`.
    assert next_question_for(user) == (None, None)

    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(), category_index=0,
    )

    assert next_question_for(User.get_by_id(user.telegram_id)) == (None, None)


async def test_one_stray_does_not_stop_the_hour(stray, make_user, questions, bot, monkeypatch):
    """Belt and braces: even if one slips past the filter, the rest still get
    their questions."""
    healthy = make_user(telegram_id=1, slots=(9,))

    monkeypatch.setattr(
        "bot.scheduler.users_due_at", lambda hour: [stray, healthy],
    )

    sent = await send_due_questions(bot, clock.now_kyiv())

    assert sent == 1
    assert bot.sent and bot.sent[0]["chat_id"] == healthy.telegram_id
