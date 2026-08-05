"""What a cohort's status decides.

PLANNED and ENDED close enrollment outright; only RUNNING leaves the question
to the dates and the seat count. The admin promotes PLANNED -> RUNNING by
hand, and the daily sweep is the only thing that sets ENDED.
"""
from datetime import timedelta

import pytest

from core import clock, migrations
from core.enums import CohortStatus, EnrollmentState
from core.models import Cohort
from core.services.cohort import can_join, end_cohort, enrollment_state

from tests.factories import build_cohort


@pytest.fixture
def open_window():
    """A cohort whose dates and seats say yes, so only the status is in play."""
    today = clock.today_kyiv()

    return build_cohort(
        enrollment_opens=today - timedelta(days=1),
        enrollment_closes=today + timedelta(days=7),
    )


# --- what each status decides ----------------------------------------------

def test_planned_closes_enrollment_even_with_the_window_open(open_window):
    open_window.status = CohortStatus.PLANNED
    open_window.save()

    assert enrollment_state(open_window) == EnrollmentState.NOT_OPEN_YET
    assert can_join(open_window) is False


def test_running_lets_the_dates_decide(open_window):
    open_window.status = CohortStatus.RUNNING
    open_window.save()

    assert enrollment_state(open_window) == EnrollmentState.OPEN
    assert can_join(open_window) is True


def test_ended_closes_enrollment(open_window):
    end_cohort(open_window)

    assert enrollment_state(open_window) == EnrollmentState.NO_COHORT
    assert can_join(open_window) is False


# --- promoting ahead of the opening day ------------------------------------

def test_promoting_early_does_not_open_enrollment(frozen_clock):
    """The case that motivated this: RUNNING can be set in advance, and the
    cohort still turns people away until its opening day."""
    today = clock.today_kyiv()
    cohort = build_cohort(
        status=CohortStatus.RUNNING,
        enrollment_opens=today + timedelta(days=3),
        enrollment_closes=today + timedelta(days=17),
    )

    assert enrollment_state(cohort) == EnrollmentState.NOT_OPEN_YET
    assert can_join(cohort) is False


def test_it_opens_by_itself_on_the_day(frozen_clock):
    """And nothing has to be pressed when the day comes."""
    today = clock.today_kyiv()
    cohort = build_cohort(
        status=CohortStatus.RUNNING,
        enrollment_opens=today + timedelta(days=3),
        enrollment_closes=today + timedelta(days=17),
    )

    frozen_clock(days=3)

    assert enrollment_state(cohort) == EnrollmentState.OPEN
    assert can_join(cohort) is True


def test_a_planned_cohort_does_not_open_on_the_day(frozen_clock):
    """Whereas one still PLANNED stays shut, because the launch is a decision
    and not a date."""
    today = clock.today_kyiv()
    cohort = build_cohort(
        status=CohortStatus.PLANNED,
        enrollment_opens=today + timedelta(days=3),
        enrollment_closes=today + timedelta(days=17),
    )

    frozen_clock(days=3)

    assert can_join(cohort) is False


# --- the enum itself --------------------------------------------------------

def test_enrolling_is_gone_and_its_value_is_not_reused():
    """1 stays a hole: databases store these numbers, and giving it to another
    member would silently reinterpret every row that still holds it."""
    assert not hasattr(CohortStatus, "ENROLLING")

    with pytest.raises(ValueError):
        CohortStatus(1)

    assert [int(s) for s in CohortStatus] == [0, 2, 3]


def test_stored_enrolling_rows_become_running(db):
    """The migration for databases written before ENROLLING was retired.
    Folding them into PLANNED instead would have closed enrollment on a cohort
    that was taking people right up to the deploy."""
    cohort = build_cohort(status=CohortStatus.PLANNED)
    Cohort.update(status=1).where(Cohort.id == cohort.id).execute()

    db.pragma("user_version", 0)
    migrations.apply_migrations(db)

    assert Cohort.get_by_id(cohort.id).status == CohortStatus.RUNNING


def test_the_migration_leaves_other_statuses_alone(db):
    planned = build_cohort(name="A", status=CohortStatus.PLANNED)
    ended = build_cohort(name="B", status=CohortStatus.ENDED)

    db.pragma("user_version", 0)
    migrations.apply_migrations(db)

    assert Cohort.get_by_id(planned.id).status == CohortStatus.PLANNED
    assert Cohort.get_by_id(ended.id).status == CohortStatus.ENDED
