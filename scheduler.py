"""Hourly scheduler.

Every hour it sends questions to users whose chosen slot matches the current
hour. At SWEEP_HOUR it additionally normalises expired pauses and completes
cycles for users who went quiet on day 30.

Missed hours are never replayed: if the bot was down, that slot is simply
skipped and the next tick carries on as normal.
"""
from datetime import timedelta

from telegram.ext import ContextTypes

from askquestions import send_question
from clock import now_kyiv
from config import SWEEP_HOUR, TICK_INTERVAL_HOURS
from cohort import (
    complete_cycle,
    current_cohort,
    cohort_is_complete,
    end_cohort,
    resume_user,
    users_due_for_completion,
    users_with_expired_pause,
)
from database import User, UserTime, Answer, Status

TICK_INTERVAL = timedelta(hours=TICK_INTERVAL_HOURS)


def users_due_at(hour):
    """Active, unpaused users who picked a slot in this hour and haven't
    already finished their cycle."""
    rows = (
        UserTime.select(UserTime, User)
        .join(User)
        .where(User.status == Status.ACTIVE)
    )

    seen = {}
    for row in rows:
        if row.time.hour != hour:
            continue

        user = row.user
        if user.is_paused or user.is_cycle_complete:
            continue

        seen[user.telegram_id] = user

    return list(seen.values())


def already_sent_this_hour(user, now):
    """Guards against a restart inside the hour re-sending the same slot."""
    hour_start = now.replace(minute=0, second=0, microsecond=0)

    return (
        Answer.select()
        .where((Answer.user == user) & (Answer.sent_at >= hour_start))
        .exists()
    )


async def send_due_questions(bot, now):
    sent = 0

    for user in users_due_at(now.hour):
        if already_sent_this_hour(user, now):
            continue

        await send_question(bot, user)
        sent += 1

    return sent


async def run_sweep(bot):
    """Daily housekeeping: expire pauses, close out cycles, end the cohort."""
    for user in list(users_with_expired_pause()):
        resume_user(user)

    # Users who never answered on day 30, so the answer-triggered handoff
    # never fired. They get the closing block here instead.
    for user in users_due_for_completion():
        await complete_cycle(bot, user)

    cohort = current_cohort()
    if cohort is not None and cohort_is_complete(cohort):
        end_cohort(cohort)


async def hourly_tick(context: ContextTypes.DEFAULT_TYPE):
    now = now_kyiv()

    if now.hour == SWEEP_HOUR:
        await run_sweep(context.bot)

    await send_due_questions(context.bot, now)


def schedule(application):
    """Run on the hour, every hour, in Kyiv time."""
    now = now_kyiv()
    next_hour = (now + TICK_INTERVAL).replace(minute=0, second=0, microsecond=0)

    application.job_queue.run_repeating(
        hourly_tick,
        interval=TICK_INTERVAL,
        first=(next_hour - now).total_seconds(),
        name="hourly_tick",
    )
