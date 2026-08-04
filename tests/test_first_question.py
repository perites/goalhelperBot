"""The onboarding 'Так, почати' button sends a real first question,
through the same path the scheduler and /ask use."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram.ext import ConversationHandler

from core import clock
from core.enums import Status
from bot.handlers.onboarding import handle_ready
from core.models import Answer, Question
from bot.delivery import deliver_question
from bot.texts import onboarding_menu_ready_message
from tests.factories import CATEGORY_ORDER


def ready_update(user):
    message = SimpleNamespace(reply_text=AsyncMock())
    query = SimpleNamespace(
        data="ready:yes",
        message=message,
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )

    return SimpleNamespace(
        message=None,
        callback_query=query,
        effective_user=SimpleNamespace(id=user.telegram_id),
    )


def context_for(bot):
    return SimpleNamespace(bot=bot, user_data={}, args=[])


async def test_ready_button_sends_the_first_question(questions, make_user, bot):
    user = make_user()
    update = ready_update(user)

    result = await handle_ready(update, context_for(bot))

    assert result == ConversationHandler.END
    assert Answer.select().where(Answer.user == user).count() == 1
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == user.telegram_id


async def test_menu_arrives_before_the_question(questions, make_user, bot):
    user = make_user()
    update = ready_update(user)

    await handle_ready(update, context_for(bot))

    # The reply keyboard rides on its own message, sent via reply_text; the
    # question goes through the bot, so it lands after.
    update.callback_query.message.reply_text.assert_awaited_once()
    args, kwargs = update.callback_query.message.reply_text.call_args

    assert args[0] == onboarding_menu_ready_message
    assert kwargs["reply_markup"] is not None


async def test_first_question_starts_the_category_cycle(questions, make_user, bot):
    user = make_user()

    await handle_ready(ready_update(user), context_for(bot))

    answer = Answer.select().where(Answer.user == user).first()

    assert answer.category_index == 0
    assert answer.question.type == CATEGORY_ORDER[0]
    assert answer.cycle_day == 1


async def test_ready_button_survives_a_send_failure(questions, make_user, bot):
    """Onboarding must still finish even if the question can't be delivered."""
    user = make_user()

    async def refuse(*args, **kwargs):
        raise RuntimeError("Forbidden: bot was blocked by the user")

    bot.send_message = refuse

    result = await handle_ready(ready_update(user), context_for(bot))

    assert result == ConversationHandler.END


async def test_deliver_question_swallows_failures(questions, make_user, bot):
    user = make_user()

    async def refuse(*args, **kwargs):
        raise RuntimeError("network down")

    bot.send_message = refuse

    assert await deliver_question(bot, user, reason="test") is None


async def test_deliver_question_reports_an_empty_bank(make_user, bot):
    user = make_user()
    Question.delete().execute()

    assert await deliver_question(bot, user, reason="test") is None
    assert bot.sent == []


async def test_scheduler_and_onboarding_share_one_path(questions, make_user, bot):
    """Both routes produce an identically shaped pending Answer."""
    from bot.scheduler import send_due_questions

    onboarded = make_user(telegram_id=1)
    await handle_ready(ready_update(onboarded), context_for(bot))

    scheduled = make_user(telegram_id=2, slots=(9,), status=Status.ACTIVE)
    await send_due_questions(bot, clock.now_kyiv())

    first = Answer.select().where(Answer.user == onboarded).first()
    second = Answer.select().where(Answer.user == scheduled).first()

    for row in (first, second):
        assert row.answered_at is None
        assert row.skipped is False
        assert row.message_id is not None
        assert row.cycle_day == 1
