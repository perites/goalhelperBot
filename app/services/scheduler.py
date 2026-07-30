"""Hourly scheduler.

Every hour it sends questions to users whose chosen slot matches the current
hour. At SWEEP_HOUR it additionally normalises expired pauses and completes
cycles for users who went quiet on day 30.

Missed hours are never replayed: if the bot was down, that slot is simply
skipped and the next tick carries on as normal.
"""
from datetime import timedelta

from telegram.ext import ContextTypes

from app import clock
from app.config import SWEEP_HOUR, TICK_INTERVAL_HOURS
from app.enums import Status
from app.logs import get_logger
from app.models import User, UserTime
from app.services.cohort import cohort_is_complete, current_cohort, end_cohort
from app.services.cycle import (
    complete_cycle,
    resume_user,
    users_due_for_completion,
    users_with_expired_pause,
)
from app.services.questions import deliver_question, sent_in_slot_today
from app.services.slots import slot_id

logger = get_logger(__name__)

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


def slot_already_started(user, slot):
    """The scheduler only ever *starts* a slot's run — the rest of it is driven
    by answers. This is also the restart guard: a tick firing twice can't
    restart a run that's already in flight."""
    return sent_in_slot_today(user, slot) > 0


def slot_at_hour(user, hour):
    """The slot this user has in this hour, taken from their own UserTime row
    rather than from the tick — so a time carrying minutes is identified as
    itself ("09:30") even though it's delivered at the top of the hour."""
    matching = sorted(row.time for row in user.times if row.time.hour == hour)

    return slot_id(matching[0]) if matching else None


async def send_due_questions(bot, now):
    due = users_due_at(now.hour)
    sent = 0
    skipped = 0
    failed = 0

    logger.debug("Hour %02d: %s user(s) due", now.hour, len(due))

    for user in due:
        slot = slot_at_hour(user, now.hour)
        if slot is None:
            continue

        if slot_already_started(user, slot):
            skipped += 1
            logger.debug("user=%s already started the %s run today", user.telegram_id, slot)
            continue

        if await deliver_question(bot, user, reason="scheduled", slot=slot) is None:
            failed += 1
            continue

        sent += 1

    if sent or failed:
        logger.info(
            "Hour %02d done: sent=%s skipped=%s failed=%s", now.hour, sent, skipped, failed
        )

    return sent


async def run_sweep(bot):
    """Daily housekeeping: expire pauses, close out cycles, end the cohort."""
    logger.info("Daily sweep starting")

    resumed = 0
    for user in list(users_with_expired_pause()):
        resume_user(user)
        resumed += 1
        logger.info("Pause expired, user=%s resumed", user.telegram_id)

    # Users who never answered on their last day, so the answer-triggered
    # handoff never fired. They get the closing block here instead.
    completed = 0
    for user in users_due_for_completion():
        try:
            await complete_cycle(bot, user)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to complete cycle for user=%s", user.telegram_id, exc_info=True)
            continue

        completed += 1
        logger.info("Cycle completed for user=%s", user.telegram_id)

    cohort = current_cohort()
    if cohort is not None and cohort_is_complete(cohort):
        end_cohort(cohort)
        logger.info("Cohort id=%s ended: no participants still running", cohort.id)

    logger.info("Daily sweep done: resumed=%s completed=%s", resumed, completed)


async def hourly_tick(context: ContextTypes.DEFAULT_TYPE):
    now = clock.now_kyiv()

    if now.hour == SWEEP_HOUR:
        await run_sweep(context.bot)

    await send_due_questions(context.bot, now)


def schedule(application):
    """Run on the hour, every hour, in Kyiv time."""
    now = clock.now_kyiv()
    next_hour = (now + TICK_INTERVAL).replace(minute=0, second=0, microsecond=0)
    delay = (next_hour - now).total_seconds()

    application.job_queue.run_repeating(
        hourly_tick,
        interval=TICK_INTERVAL,
        first=delay,
        name="hourly_tick",
    )

    logger.info(
        "Scheduler armed: first tick at %s (in %.0f min), then every %s h",
        next_hour.strftime("%H:%M"), delay / 60, TICK_INTERVAL_HOURS,
    )
