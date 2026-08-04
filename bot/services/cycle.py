"""A participant's personal 30 days: pausing, and reaching the end.

Splitting this from cohort.py lets it depend on the questions service without
a cycle, which is what the function-level imports used to work around.
"""
from bot import clock
from bot.enums import Status
from bot.logs import get_logger
from bot.models import User
from bot.services.cohort import active_participants
from bot.services.questions import (
    close_open_answers,
    has_received_closing_block,
    send_closing_block,
)
from bot.services.stats import build_stats_text
from bot.texts import cycle_final_invite_message, cycle_final_summary_intro

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


async def complete_cycle(bot, user):
    """Last day done: send the closing block, then mark finished.

    The send comes first because FINISHED is exactly what takes someone out of
    `users_due_for_completion`. Flipping the status before a send that then
    failed would retire them silently — no closing questions, no summary, no
    invitation, and nothing left that would ever try again. Failing here
    leaves them ACTIVE, so tomorrow's sweep has another go.

    Nothing reaches them in the gap: `is_cycle_complete` already keeps the
    daily questions away, so the status flip is for the sweep's benefit rather
    than the participant's.

    An empty closing bank is not a failure — `send_closing_block` says so in
    the log and returns None, and the participant is still finished.
    """
    if has_received_closing_block(user):
        return None

    final_answer = await send_closing_block(bot, user)

    finish_user(user)
    logger.info("user=%s reached day %s and finished", user.telegram_id, user.cycle_day)

    return final_answer


async def send_closing_summary(bot, user):
    """Called once the closing block is answered: summary, then thanks and
    the invitation to book a session (ТЗ §15–16)."""
    await bot.send_message(
        chat_id=user.telegram_id,
        text=cycle_final_summary_intro.format(total=user.cycle_length),
    )

    await bot.send_message(chat_id=user.telegram_id, text=build_stats_text(user))
    await bot.send_message(chat_id=user.telegram_id, text=cycle_final_invite_message)
