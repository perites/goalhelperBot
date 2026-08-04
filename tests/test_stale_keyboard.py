"""Regressions from the first live run.

A Telegram reply keyboard lives in the client, so it survives an abandoned
onboarding or a rebuilt database — and taps arrive for users whose row is
half-filled. Separately, re-tapping "Почати" used to be swallowed.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import ReplyKeyboardRemove

from core.enums import Status
from bot.handlers.menu import (
    handle_edit_times, handle_finish, handle_finish_confirm, handle_my_info,
    handle_pause, handle_stats,
)
from bot.handlers.onboarding import onboarding_conv_handler
from core.models import User
from bot.texts import main_menu_buttons, menu_not_participant_message


def text_update(telegram_id, text="📝 Моя інформація"):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())

    return SimpleNamespace(
        message=message,
        callback_query=None,
        effective_user=SimpleNamespace(id=telegram_id),
    )


def callback_update(telegram_id, data):
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data=data,
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )

    return SimpleNamespace(
        message=None,
        callback_query=query,
        effective_user=SimpleNamespace(id=telegram_id),
    )


def context_for(bot):
    return SimpleNamespace(bot=bot, user_data={}, args=[])


def half_onboarded(cohort):
    """The row /start creates before onboarding fills anything in."""
    return User.create(
        telegram_id=99, username="half", status=Status.ONBOARDING, cohort=cohort,
    )


async def test_my_info_does_not_crash_on_a_half_filled_row(cohort, bot):
    """This is the exact TypeError seen in production."""
    half_onboarded(cohort)
    update = text_update(99)

    await handle_my_info(update, context_for(bot))

    args, kwargs = update.message.reply_text.call_args
    assert args[0] == menu_not_participant_message
    assert isinstance(kwargs["reply_markup"], ReplyKeyboardRemove)


async def test_every_menu_action_is_guarded(cohort, bot):
    for handler in (handle_my_info, handle_stats, handle_edit_times, handle_pause, handle_finish):
        User.delete().execute()
        half_onboarded(cohort)
        update = text_update(99)

        await handler(update, context_for(bot))

        assert update.message.reply_text.call_args[0][0] == menu_not_participant_message


async def test_finishing_cannot_lock_out_a_non_participant(cohort, bot):
    """STOPPED is terminal — a stale keyboard must not be able to set it."""
    half_onboarded(cohort)

    await handle_finish_confirm(callback_update(99, "finish:yes"), context_for(bot))

    assert User.get_by_id(99).status == Status.ONBOARDING


async def test_completed_participant_is_unaffected(make_user, bot):
    user = make_user(telegram_id=99)
    update = text_update(99)

    await handle_my_info(update, context_for(bot))

    assert user.intention in update.message.reply_text.call_args[0][0]


def test_onboarding_allows_reentry():
    """Without this, a second tap on "Почати" is silently dropped because
    entry points aren't consulted mid-conversation."""
    assert onboarding_conv_handler.allow_reentry is True


def _real_update(text):
    """filters.COMMAND inspects message.entities, so this needs the real thing."""
    from datetime import datetime

    from telegram import Chat, Message, Update

    message = Message(
        message_id=1,
        date=datetime.now(),
        chat=Chat(id=1, type=Chat.PRIVATE),
        text=text,
    )

    return Update(update_id=1, message=message)


def test_free_text_states_ignore_menu_buttons():
    """Otherwise a stray menu tap gets saved as somebody's name."""
    from bot.handlers.onboarding import FREE_TEXT, INTENTION, NAME

    for state in (NAME, INTENTION):
        assert onboarding_conv_handler.states[state][0].filters is FREE_TEXT

    for label in main_menu_buttons:
        assert not FREE_TEXT.check_update(_real_update(label))

    # A genuine answer still gets through.
    assert FREE_TEXT.check_update(_real_update("Оксана"))
