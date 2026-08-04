"""A participant's personal 30 days: pausing, and reaching the end.

State transitions only. Sending the closing block and the summary that follows
it is the bot's — see `bot/closing.py`.
"""
from core import clock
from core.enums import Status
from core.logs import get_logger
from core.models import User
from core.services.cohort import active_participants
from core.services.questions import close_open_answers, has_received_closing_block

logger = get_logger(__name__)


# --- Pausing ---------------------------------------------------------------

def pause_user(user):
    # A pause shouldn't leave a question hanging open against the paused days.
    close_open_answers(user)

    user.status = Status.PAUSED
    user.paused_at = clock.now_kyiv()
    user.save()

    logger.info("user=%s paused on day %s", user.telegram_id, user.cycle_day)


def resume_user(user):
    """Bank the days spent paused, then put the user back into the cycle.
    Safe to call on an expired pause — current_pause_days is already capped."""
    if user.paused_at is not None:
        user.paused_days += user.current_pause_days
        user.paused_at = None

    user.status = Status.ACTIVE
    user.save()

    logger.info(
        "user=%s resumed on day %s (%s day(s) banked)",
        user.telegram_id, user.cycle_day, user.paused_days,
    )


def users_with_expired_pause():
    """Paused users whose pause is up, for the scheduler to normalise.

    Filtered through `is_paused` rather than a SQL datetime comparison so this
    can't disagree with the property: that one counts calendar days, and a
    cutoff of `now - 3 days` would hold a user in PAUSED for up to a day after
    their pause had already stopped counting.
    """
    candidates = User.select().where(
        (User.status == Status.PAUSED) & User.paused_at.is_null(False)
    )

    return [user for user in candidates if not user.is_paused]


# --- End of cycle ----------------------------------------------------------

def reached_final_day(user):
    return user.date_started is not None and user.cycle_day >= user.cycle_length


def finish_user(user):
    user.status = Status.FINISHED
    user.save()


def users_due_for_completion():
    """Active users past their personal last day who never answered on it, so
    the answer-triggered handoff didn't fire. Paused users are excluded
    because their finish line moves with the pause."""
    candidates = active_participants()

    return [
        user for user in candidates
        if user.is_cycle_complete and not has_received_closing_block(user)
    ]
