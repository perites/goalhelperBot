"""Cohort enrollment: the joining window, capacity, and the waitlist."""
from datetime import timedelta

from app import clock
from app.config import DEFAULT_ENROLLMENT_WINDOW_DAYS, DEFAULT_MAX_PEOPLE
from app.enums import CohortStatus, EnrollmentState, Status
from app.logs import get_logger
from app.models import Cohort, User

logger = get_logger(__name__)

# Statuses that occupy one of the cohort's seats. A user still in ONBOARDING
# has not taken a seat yet, so the cap is checked again when they confirm.
SEAT_STATUSES = (Status.ACTIVE, Status.PAUSED, Status.FINISHED, Status.STOPPED)


def seed_default_cohort():
    """Create a cohort if none exists, so the bot works out of the box."""
    if Cohort.select().exists():
        return Cohort.select().first()

    today = clock.today_kyiv()

    cohort = Cohort.create(
        name="Пілот",
        is_active=True,
        enrollment_opens=today,
        enrollment_closes=today + timedelta(days=DEFAULT_ENROLLMENT_WINDOW_DAYS),
        max_people=DEFAULT_MAX_PEOPLE,
        status=CohortStatus.ENROLLING,
    )

    logger.warning(
        "No cohort existed; created a default one open %s..%s with %s seats. "
        "Set real dates before the pilot starts.",
        cohort.enrollment_opens, cohort.enrollment_closes, cohort.max_people,
    )

    return cohort


def current_cohort():
    """The one cohort taking new participants. Explicit rather than inferred,
    so adding a cohort for a future run can't quietly divert enrolments."""
    return Cohort.select().where(Cohort.is_active == True).first()  # noqa: E712


def activate_cohort(cohort):
    """Make this the active one. Only ever one, so the rest are stood down in
    the same transaction — a moment with two active cohorts would send people
    into whichever the query happened to return first."""
    with Cohort._meta.database.atomic():
        Cohort.update(is_active=False).where(Cohort.id != cohort.id).execute()
        cohort.is_active = True
        cohort.save()

    logger.info("Cohort id=%s (%s) is now active", cohort.id, cohort.name)

    return cohort


def seats_taken(cohort):
    return User.select().where(
        (User.cohort == cohort) & (User.status.in_(SEAT_STATUSES))
    ).count()


def seats_left(cohort):
    return max(cohort.max_people - seats_taken(cohort), 0)


def enrollment_state(cohort=None):
    """Which of the ТЗ's enrollment situations we're in. FULL and CLOSED are
    separate because the spec gives each its own message."""
    cohort = cohort or current_cohort()

    if cohort is None or cohort.status == CohortStatus.ENDED:
        return EnrollmentState.NO_COHORT

    today = clock.today_kyiv()

    if today < cohort.enrollment_opens:
        return EnrollmentState.NOT_OPEN_YET

    if today > cohort.enrollment_closes:
        return EnrollmentState.CLOSED

    if seats_left(cohort) <= 0:
        return EnrollmentState.FULL

    return EnrollmentState.OPEN


def can_join(cohort=None):
    return enrollment_state(cohort) == EnrollmentState.OPEN


def join_cohort(user, cohort=None):
    """Claim a seat. Returns False if the cohort filled up meanwhile."""
    cohort = cohort or current_cohort()

    if cohort is None or seats_left(cohort) <= 0:
        logger.warning("user=%s could not claim a seat: cohort full or missing", user.telegram_id)
        return False

    user.cohort = cohort
    user.save()

    logger.info(
        "user=%s joined cohort=%s (%s seat(s) left)",
        user.telegram_id, cohort.id, seats_left(cohort),
    )

    return True


def put_on_waitlist(user):
    user.status = Status.WAITLIST
    user.cohort = None
    user.save()

    logger.info("user=%s put on the waitlist", user.telegram_id)


def cohort_is_complete(cohort):
    """True once no participant is still working through their cycle."""
    return not User.select().where(
        (User.cohort == cohort)
        & (User.status.in_((Status.ACTIVE, Status.PAUSED)))
    ).exists()


def end_cohort(cohort):
    """Ending a cohort also stands it down: a finished run shouldn't stay the
    one new participants are enrolled into."""
    cohort.status = CohortStatus.ENDED
    cohort.is_active = False
    cohort.save()
