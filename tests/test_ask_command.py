"""`/ask <telegram_id>` is for admins only.

It acts on somebody else — closing whatever they had open and consuming a
rotation slot — and its replies say whether an id belongs to a participant and
what state they are in. Membership of a private coaching cohort is not a
stranger's to find out.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.handlers.answers import handle_ask_command
from core.models import Answer
from bot.delivery import send_question

ADMIN_ID = 42
STRANGER_ID = 999


def command_update(telegram_id):
    message = SimpleNamespace(reply_text=AsyncMock())

    return SimpleNamespace(
        message=message,
        callback_query=None,
        effective_user=SimpleNamespace(id=telegram_id),
    )


def context_for(bot, *args):
    return SimpleNamespace(bot=bot, user_data={}, args=list(args))


async def test_an_admin_can_send_a_question(monkeypatch, questions, make_user, bot):
    monkeypatch.setenv("ADMIN_CHAT_IDS", str(ADMIN_ID))
    target = make_user(telegram_id=7)
    update = command_update(ADMIN_ID)

    await handle_ask_command(update, context_for(bot, "7"))

    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == target.telegram_id
    update.message.reply_text.assert_awaited()


async def test_a_stranger_gets_nothing(monkeypatch, questions, make_user, bot):
    monkeypatch.setenv("ADMIN_CHAT_IDS", str(ADMIN_ID))
    make_user(telegram_id=7)
    update = command_update(STRANGER_ID)

    await handle_ask_command(update, context_for(bot, "7"))

    assert bot.sent == []
    assert Answer.select().count() == 0
    # Silence rather than a refusal: there is nothing to gain by confirming
    # the command exists.
    update.message.reply_text.assert_not_awaited()


async def test_a_stranger_cannot_probe_who_is_a_participant(
    monkeypatch, questions, make_user, bot,
):
    """The replies distinguish "no such user" from "not ACTIVE" from a
    successful send, which is enough to enumerate the cohort."""
    monkeypatch.setenv("ADMIN_CHAT_IDS", str(ADMIN_ID))
    update = command_update(STRANGER_ID)

    await handle_ask_command(update, context_for(bot, "12345"))

    update.message.reply_text.assert_not_awaited()


async def test_a_stranger_cannot_disturb_a_pending_question(
    monkeypatch, questions, make_user, bot,
):
    """A send closes out whatever the target had open — so this used to be a
    way to mark a stranger's real question skipped."""
    monkeypatch.setenv("ADMIN_CHAT_IDS", str(ADMIN_ID))
    target = make_user(telegram_id=7)
    pending = await send_question(bot, target)

    await handle_ask_command(command_update(STRANGER_ID), context_for(bot, "7"))

    assert Answer.get_by_id(pending.id).skipped is False


async def test_nobody_is_an_admin_when_the_variable_is_unset(
    monkeypatch, questions, make_user, bot,
):
    """Fail closed. An empty ADMIN_CHAT_IDS is a misconfiguration, and the
    wrong way to read it is "everyone"."""
    monkeypatch.delenv("ADMIN_CHAT_IDS", raising=False)
    make_user(telegram_id=7)

    await handle_ask_command(command_update(ADMIN_ID), context_for(bot, "7"))

    assert bot.sent == []


async def test_one_of_several_admins_is_enough(monkeypatch, questions, make_user, bot):
    monkeypatch.setenv("ADMIN_CHAT_IDS", "11, 42 ,13")
    make_user(telegram_id=7)

    await handle_ask_command(command_update(ADMIN_ID), context_for(bot, "7"))

    assert len(bot.sent) == 1
