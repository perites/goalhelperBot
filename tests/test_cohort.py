"""Enrollment window, seat counting, and waitlisting."""
from datetime import timedelta

import pytest

from core import clock
from core.enums import CohortStatus, Status
from core.enums import EnrollmentState
from core.models import User
from core.services.cohort import (
    can_join, cohort_is_complete, current_cohort, end_cohort, enrollment_state,
    join_cohort, put_on_waitlist, seats_left, seats_taken,
)
from tests.factories import MAX_PEOPLE


def test_only_completed_onboardings_take_a_seat(cohort, make_user):
    make_user(telegram_id=1, status=Status.ONBOARDING)
    make_user(telegram_id=2, status=Status.WAITLIST)
    make_user(telegram_id=3, status=Status.DECLINED)

    assert seats_taken(cohort) == 0

    for index, status in enumerate(
            (Status.ACTIVE, Status.PAUSED, Status.FINISHED, Status.STOPPED), start=10
    ):
        make_user(telegram_id=index, status=status)

    assert seats_taken(cohort) == 4
    assert seats_left(cohort) == MAX_PEOPLE - 4


@pytest.mark.parametrize(
    "opens_offset, closes_offset, expected",
    [
        (0, 14, EnrollmentState.OPEN),
        (5, 19, EnrollmentState.NOT_OPEN_YET),
        (-20, -1, EnrollmentState.CLOSED),
    ],
)
def test_enrollment_window(cohort, opens_offset, closes_offset, expected):
    today = clock.today_kyiv()
    cohort.enrollment_opens = today + timedelta(days=opens_offset)
    cohort.enrollment_closes = today + timedelta(days=closes_offset)
    cohort.save()

    assert enrollment_state(cohort) == expected


def test_enrollment_closes_on_the_boundary_day(cohort):
    cohort.enrollment_closes = clock.today_kyiv()
    cohort.save()

    # The closing day itself is still open.
    assert enrollment_state(cohort) == EnrollmentState.OPEN


def test_full_cohort_reports_full(cohort, make_user):
    for index in range(MAX_PEOPLE):
        make_user(telegram_id=index + 1, status=Status.ACTIVE)

    assert seats_left(cohort) == 0
    assert enrollment_state(cohort) == EnrollmentState.FULL
    assert can_join(cohort) is False


def test_ended_cohort_reports_no_cohort(cohort):
    end_cohort(cohort)

    assert cohort.status == CohortStatus.ENDED
    assert current_cohort() is None
    assert enrollment_state() == EnrollmentState.NO_COHORT


def test_join_refused_when_full(cohort, make_user):
    for index in range(MAX_PEOPLE):
        make_user(telegram_id=index + 1, status=Status.ACTIVE)

    latecomer = make_user(telegram_id=99, status=Status.ONBOARDING, cohort=None)

    assert join_cohort(latecomer, cohort) is False


def test_join_claims_a_seat(cohort, make_user):
    user = make_user(status=Status.ONBOARDING, cohort=None)

    assert join_cohort(user, cohort) is True
    assert User.get_by_id(user.telegram_id).cohort.id == cohort.id


def test_waitlisting_clears_the_cohort(cohort, make_user):
    user = make_user(status=Status.ONBOARDING)
    put_on_waitlist(user)

    stored = User.get_by_id(user.telegram_id)

    assert stored.status == Status.WAITLIST
    assert stored.cohort is None
    assert seats_taken(cohort) == 0


def test_cohort_completes_only_when_nobody_is_running(cohort, make_user):
    active = make_user(telegram_id=1, status=Status.ACTIVE)
    make_user(telegram_id=2, status=Status.FINISHED)

    assert cohort_is_complete(cohort) is False

    active.status = Status.FINISHED
    active.save()

    assert cohort_is_complete(cohort) is True


def test_paused_user_keeps_the_cohort_running(cohort, make_user):
    make_user(telegram_id=1, status=Status.PAUSED)
    make_user(telegram_id=2, status=Status.FINISHED)

    assert cohort_is_complete(cohort) is False
