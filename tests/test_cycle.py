"""Cycle-day and pause arithmetic — a pause must not cost the user days."""

from core.settings import PAUSE_DURATION_DAYS
from core.enums import Status
from core.services.cycle import (
    pause_user, reached_final_day, resume_user, users_with_expired_pause,
)
from tests.factories import DURATION_DAYS


def test_cycle_day_counts_from_start(make_user):
    assert make_user(started_days_ago=0).cycle_day == 1
    assert make_user(telegram_id=2, started_days_ago=10).cycle_day == 11


def test_cycle_day_is_one_when_never_started(make_user):
    user = make_user(status=Status.ONBOARDING, date_started=None)

    assert user.cycle_day == 1
    assert user.cycle_end_date is None
    assert user.is_cycle_complete is False


def test_pause_holds_the_cycle_day(make_user, frozen_clock):
    user = make_user(started_days_ago=10)
    assert user.cycle_day == 11

    pause_user(user)
    frozen_clock(days=2)

    # Two days passed, both excused, so the cycle day hasn't moved.
    assert user.cycle_day == 11
    assert user.is_paused is True
    assert user.pause_days_left == 1


def test_pause_expires_on_its_own(make_user, frozen_clock):
    user = make_user(started_days_ago=10)
    pause_user(user)
    frozen_clock(days=5)

    # Capped: only PAUSE_DURATION_DAYS are ever excused, so the 2 days beyond
    # the pause window count normally.
    assert user.current_pause_days == PAUSE_DURATION_DAYS
    assert user.is_paused is False
    assert user.cycle_day == 11 + (5 - PAUSE_DURATION_DAYS)


def test_resume_banks_paused_days_and_pushes_the_end_date(make_user, frozen_clock):
    user = make_user(started_days_ago=10)
    end_before = user.cycle_end_date

    pause_user(user)
    frozen_clock(days=3)
    resume_user(user)

    assert user.status == Status.ACTIVE
    assert user.paused_at is None
    assert user.paused_days == 3
    assert (user.cycle_end_date - end_before).days == 3


def test_resume_is_idempotent(make_user, frozen_clock):
    user = make_user(started_days_ago=10)
    pause_user(user)
    frozen_clock(days=2)

    resume_user(user)
    day_after_first = user.cycle_day
    resume_user(user)

    assert user.paused_days == 2
    assert user.cycle_day == day_after_first


def test_early_resume_only_banks_days_actually_used(make_user, frozen_clock):
    user = make_user(started_days_ago=10)
    pause_user(user)
    frozen_clock(hours=5)
    resume_user(user)

    # Resumed the same day, so nothing was consumed.
    assert user.paused_days == 0
    assert user.cycle_day == 11


def test_expired_pause_sweeper_finds_only_overdue_users(make_user, frozen_clock):
    fresh = make_user(telegram_id=1, started_days_ago=5)
    stale = make_user(telegram_id=2, started_days_ago=5)

    pause_user(stale)
    frozen_clock(days=PAUSE_DURATION_DAYS)
    pause_user(fresh)

    overdue = [u.telegram_id for u in users_with_expired_pause()]

    assert overdue == [2]


def test_cycle_completes_the_day_after_the_last(make_user):
    on_final_day = make_user(telegram_id=1, started_days_ago=DURATION_DAYS - 1)
    past_it = make_user(telegram_id=2, started_days_ago=DURATION_DAYS)

    assert on_final_day.cycle_day == DURATION_DAYS
    assert on_final_day.is_cycle_complete is False
    assert reached_final_day(on_final_day) is True

    assert past_it.is_cycle_complete is True


def test_pause_delays_completion(make_user, frozen_clock):
    user = make_user(started_days_ago=DURATION_DAYS - 2)
    pause_user(user)
    frozen_clock(days=PAUSE_DURATION_DAYS)
    resume_user(user)

    # Would have finished by now without the pause.
    assert user.is_cycle_complete is False
    assert reached_final_day(user) is False

    frozen_clock(days=PAUSE_DURATION_DAYS)

    assert reached_final_day(user) is True


def test_cycle_length_follows_the_cohort(make_user, cohort):
    cohort.duration_days = 7
    cohort.save()

    user = make_user(started_days_ago=7)

    assert user.cycle_length == 7
    assert user.is_cycle_complete is True
