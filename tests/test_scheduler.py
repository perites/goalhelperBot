"""Hourly tick: who is due, the restart guard, and the daily sweep."""
from bot.settings import SWEEP_HOUR
from core.settings import PAUSE_DURATION_DAYS
from core.enums import Status
from core.models import Answer, FinalAnswer, User
from core.services.cycle import pause_user, users_due_for_completion
from core.services.questions import has_received_closing_block
from bot.scheduler import (
    hourly_tick, run_sweep, send_due_questions, slot_already_started, users_due_at,
)
from tests.factories import DURATION_DAYS


class FakeContext:
    def __init__(self, bot):
        self.bot = bot


def test_only_matching_hour_is_due(make_user):
    make_user(telegram_id=1, slots=(9,))
    make_user(telegram_id=2, slots=(19,))

    assert [u.telegram_id for u in users_due_at(9)] == [1]
    assert [u.telegram_id for u in users_due_at(19)] == [2]


def test_multiple_slots_make_a_user_due_more_than_once(make_user):
    make_user(telegram_id=1, slots=(9, 13, 19))

    for hour in (9, 13, 19):
        assert [u.telegram_id for u in users_due_at(hour)] == [1]


def test_paused_and_inactive_users_are_skipped(make_user):
    make_user(telegram_id=1, slots=(9,))
    paused = make_user(telegram_id=2, slots=(9,))
    pause_user(paused)
    make_user(telegram_id=3, status=Status.FINISHED, slots=(9,))
    make_user(telegram_id=4, status=Status.STOPPED, slots=(9,))
    make_user(telegram_id=5, status=Status.ONBOARDING, slots=(9,))

    assert [u.telegram_id for u in users_due_at(9)] == [1]


def test_user_past_their_cycle_is_not_due(make_user):
    make_user(telegram_id=1, slots=(9,), started_days_ago=DURATION_DAYS)

    assert users_due_at(9) == []


async def test_restart_within_the_hour_does_not_resend(questions, make_user, bot, frozen_clock):
    make_user(telegram_id=1, slots=(9,))

    sent = await send_due_questions(bot, frozen_clock.now())
    assert sent == 1

    # Simulate a restart later in the same hour.
    resent = await send_due_questions(bot, frozen_clock(minutes=25))
    assert resent == 0
    assert len(bot.sent) == 1


async def test_next_hour_sends_again(questions, make_user, bot, frozen_clock):
    user = make_user(telegram_id=1, slots=(9, 13))

    await send_due_questions(bot, frozen_clock.now())
    frozen_clock(hours=4)  # now 13:30
    await send_due_questions(bot, frozen_clock.now())

    assert len(bot.sent) == 2
    assert slot_already_started(user, "13:00") is True


async def test_missed_hour_is_not_replayed(questions, make_user, bot, frozen_clock):
    make_user(telegram_id=1, slots=(9,))

    # The bot was down at 09:00 and only wakes at 11:00.
    frozen_clock(hours=2)
    sent = await send_due_questions(bot, frozen_clock.now())

    assert sent == 0
    assert bot.sent == []


async def test_sweep_resumes_expired_pauses(make_user, bot, frozen_clock):
    user = make_user(telegram_id=1)
    pause_user(user)
    frozen_clock(days=PAUSE_DURATION_DAYS)

    await run_sweep(bot)

    assert User.get_by_id(1).status == Status.ACTIVE
    assert User.get_by_id(1).paused_days == PAUSE_DURATION_DAYS


async def test_sweep_leaves_fresh_pauses_alone(make_user, bot, frozen_clock):
    user = make_user(telegram_id=1)
    pause_user(user)
    frozen_clock(days=1)

    await run_sweep(bot)

    assert User.get_by_id(1).status == Status.PAUSED


async def test_sweep_completes_silent_users(questions, make_user, bot):
    make_user(telegram_id=1, started_days_ago=DURATION_DAYS)

    assert [u.telegram_id for u in users_due_for_completion()] == [1]

    await run_sweep(bot)

    assert User.get_by_id(1).status == Status.FINISHED
    assert has_received_closing_block(User.get_by_id(1)) is True


async def test_sweep_is_idempotent(questions, make_user, bot):
    make_user(telegram_id=1, started_days_ago=DURATION_DAYS)

    await run_sweep(bot)
    sent_after_first = len(bot.sent)
    await run_sweep(bot)

    assert users_due_for_completion() == []
    assert len(bot.sent) == sent_after_first
    assert FinalAnswer.select().where(FinalAnswer.user == 1).count() == 1


async def test_sweep_only_runs_at_sweep_hour(make_user, bot, frozen_clock):
    user = make_user(telegram_id=1)
    pause_user(user)
    frozen_clock(days=PAUSE_DURATION_DAYS)

    # 09:30 is not the sweep hour, so the expired pause survives.
    await hourly_tick(FakeContext(bot))
    assert User.get_by_id(1).status == Status.PAUSED

    frozen_clock.set(frozen_clock.now().replace(hour=SWEEP_HOUR))
    await hourly_tick(FakeContext(bot))
    assert User.get_by_id(1).status == Status.ACTIVE


async def test_tick_sends_questions_for_the_current_hour(questions, make_user, bot, frozen_clock):
    make_user(telegram_id=1, slots=(9,))

    await hourly_tick(FakeContext(bot))

    assert len(bot.sent) == 1
    assert Answer.select().where(Answer.user == 1).count() == 1


async def test_one_unreachable_user_does_not_block_the_rest(questions, make_user, bot, frozen_clock):
    """Someone who blocked the bot must not cost everyone else their question."""
    for telegram_id in (1, 2, 3):
        make_user(telegram_id=telegram_id, slots=(9,))

    original = bot.send_message

    async def fail_for_user_two(chat_id, *args, **kwargs):
        if chat_id == 2:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        return await original(chat_id, *args, **kwargs)

    bot.send_message = fail_for_user_two

    sent = await send_due_questions(bot, frozen_clock.now())

    assert sent == 2
    assert sorted(m["chat_id"] for m in bot.sent) == [1, 3]
