"""Cohort enrollment, pausing, and end-of-cycle completion.

The completion helpers here are deliberately not wired to any handler yet —
they'll be driven by the scheduler.
"""
from datetime import timedelta
from enum import IntEnum

from clock import now_kyiv, today_kyiv
from config import (
    DEFAULT_MAX_PEOPLE,
    DEFAULT_ENROLLMENT_WINDOW_DAYS,
    PAUSE_DURATION_DAYS,
)
from database import User, Cohort, Status, CohortStatus
from messages_texts import (
    cycle_final_summary_intro,
    cycle_final_invite_message,
)

# Statuses that occupy one of the cohort's seats. A user still in ONBOARDING
# has not taken a seat yet, so the cap is checked again when they confirm.
SEAT_STATUSES = (Status.ACTIVE, Status.PAUSED, Status.FINISHED, Status.STOPPED)


class EnrollmentState(IntEnum):
    OPEN = 0
    NOT_OPEN_YET = 1
    FULL = 2
    CLOSED = 3
    NO_COHORT = 4


def seed_default_cohort():
    """Create a cohort if none exists, so the bot works out of the box."""
    if Cohort.select().exists():
        return Cohort.select().first()

    today = today_kyiv()

    return Cohort.create(
        enrollment_opens=today,
        enrollment_closes=today + timedelta(days=DEFAULT_ENROLLMENT_WINDOW_DAYS),
        max_people=DEFAULT_MAX_PEOPLE,
        status=CohortStatus.ENROLLING,
    )


def current_cohort():
    return (
        Cohort.select()
        .where(Cohort.status != CohortStatus.ENDED)
        .order_by(Cohort.enrollment_opens.desc())
        .first()
    )


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

    today = today_kyiv()

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
        return False

    user.cohort = cohort
    user.save()

    return True


def put_on_waitlist(user):
    user.status = Status.WAITLIST
    user.cohort = None
    user.save()


# --- Pausing -------------------------------------------------------------

def pause_user(user):
    user.status = Status.PAUSED
    user.paused_at = now_kyiv()
    user.save()


def resume_user(user):
    """Bank the days spent paused, then put the user back into the cycle.
    Safe to call on an expired pause — current_pause_days is already capped."""
    if user.paused_at is not None:
        user.paused_days += user.current_pause_days
        user.paused_at = None

    user.status = Status.ACTIVE
    user.save()


def users_with_expired_pause():
    """Paused users whose 3 days are up. For the scheduler to normalise."""
    cutoff = now_kyiv() - timedelta(days=PAUSE_DURATION_DAYS)

    return User.select().where(
        (User.status == Status.PAUSED)
        & User.paused_at.is_null(False)
        & (User.paused_at <= cutoff)
    )


# --- End of cycle --------------------------------------------------------

def users_due_for_completion():
    """Active users past their personal day 30 who never answered on day 30,
    so the answer-triggered path didn't fire. Paused users are excluded
    because their finish line moves with the pause."""
    from askquestions import has_received_closing_block

    candidates = User.select().where(User.status == Status.ACTIVE)

    return [
        user for user in candidates
        if user.is_cycle_complete and not has_received_closing_block(user)
    ]


def mark_finished(user):
    user.status = Status.FINISHED
    user.save()


def reached_final_day(user):
    return user.date_started is not None and user.cycle_day >= user.cycle_length


async def complete_cycle(bot, user):
    """Day 30 done: mark finished and send the closing block.

    Status flips to FINISHED straight away so the scheduler stops sending
    daily questions while we wait for the closing answer.
    """
    from askquestions import has_received_closing_block, send_closing_block

    if has_received_closing_block(user):
        return None

    mark_finished(user)

    return await send_closing_block(bot, user)


async def send_closing_summary(bot, user):
    """Called once the closing block is answered: summary, then thanks and
    the invitation to book a session (ТЗ §15–16)."""
    from stats import build_stats_text

    await bot.send_message(
        chat_id=user.telegram_id,
        text=cycle_final_summary_intro.format(total=user.cycle_length),
    )
    await bot.send_message(chat_id=user.telegram_id, text=build_stats_text(user))
    await bot.send_message(chat_id=user.telegram_id, text=cycle_final_invite_message)


def cohort_is_complete(cohort):
    """True once no participant is still working through their cycle."""
    return not User.select().where(
        (User.cohort == cohort)
        & (User.status.in_((Status.ACTIVE, Status.PAUSED)))
    ).exists()


def end_cohort(cohort):
    cohort.status = CohortStatus.ENDED
    cohort.save()
