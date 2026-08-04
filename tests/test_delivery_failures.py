"""What survives when Telegram refuses a send or an edit.

Both are ordinary events, not corruption: participants block the bot, delete
their account, clear a chat, or we get rate limited. The rule these pin down is
that a row exists only if the message it stands for actually arrived — and that
tidying up the chat history never takes a functional step down with it.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, Forbidden

from core import clock
from core.enums import Status
from bot.handlers.answers import handle_answer_text
from core.models import Answer, FinalAnswer, User
from bot.closing import complete_cycle, send_closing_block
from bot.delivery import (
    deliver_question, send_follow_up, send_question, show_resolved_answer,
)
from core.services.cycle import users_due_for_completion
from core.services.questions import has_received_closing_block, pending_answer
from bot.scheduler import slot_already_started
from tests.factories import DURATION_DAYS


class RefusingBot:
    """Telegram declines everything — blocked bot, deleted account, 429."""

    async def send_message(self, **kwargs):
        raise Forbidden("bot was blocked by the user")

    async def edit_message_text(self, **kwargs):
        raise Forbidden("bot was blocked by the user")


class UneditableBot:
    """Sends fine, but no message can be rewritten afterwards — what happens
    once the participant deletes it or clears the chat."""

    def __init__(self):
        self.sent = []
        self._next_id = 500

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self._next_id += 1
        self.sent.append({"chat_id": chat_id, "text": text})

        return SimpleNamespace(message_id=self._next_id)

    async def edit_message_text(self, **kwargs):
        raise BadRequest("Message to edit not found")


def text_update(telegram_id, text):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())

    return SimpleNamespace(
        message=message,
        callback_query=None,
        effective_user=SimpleNamespace(id=telegram_id),
    )


# --- a question that never arrived -----------------------------------------

async def test_a_failed_send_leaves_no_question_pending(questions, make_user):
    user = make_user(slots=(9,))

    sent = await deliver_question(RefusingBot(), user, reason="scheduled", slot="09:00")

    assert sent is None
    assert Answer.select().count() == 0


async def test_a_failed_send_does_not_capture_the_next_thing_they_type(questions, make_user):
    """The worst of it: a row left behind is what `pending_answer` returns, so
    the participant's next message about anything at all would be filed as the
    answer to a question they never saw."""
    user = make_user()

    await deliver_question(RefusingBot(), user, reason="scheduled", slot="09:00")

    assert pending_answer(user) is None


async def test_a_failed_send_does_not_burn_the_slot_for_the_day(questions, make_user):
    """`slot_already_started` is what stops a tick restarting a run in flight.
    A phantom row would make it say yes and the slot would go silent."""
    user = make_user(slots=(9,))

    await deliver_question(RefusingBot(), user, reason="scheduled", slot="09:00")

    assert slot_already_started(user, "09:00") is False


async def test_send_question_re_raises_so_the_caller_can_count_it(questions, make_user):
    user = make_user()

    with pytest.raises(Forbidden):
        await send_question(RefusingBot(), user)


async def test_a_successful_send_still_records_its_message(questions, make_user, bot):
    """The undo must not cost the normal path anything."""
    user = make_user()

    answer = await send_question(bot, user)

    assert answer.message_id == bot.sent[0]["message_id"]
    assert Answer.get_by_id(answer.id).message_id == answer.message_id


async def test_a_failed_follow_up_leaves_no_row(questions, make_user):
    user = make_user()
    parent_question = next(question for question in questions if question.follow_ups)
    parent = Answer.create(
        user=user, question=parent_question, sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="сум", cycle_day=1,
    )

    with pytest.raises(Forbidden):
        await send_follow_up(RefusingBot(), user, parent)

    assert Answer.select().count() == 1  # the parent, and nothing else


# --- a closing block that never arrived ------------------------------------

async def test_a_failed_closing_block_leaves_no_row(questions, make_user):
    user = make_user(started_days_ago=DURATION_DAYS)

    with pytest.raises(Forbidden):
        await send_closing_block(RefusingBot(), user)

    assert FinalAnswer.select().count() == 0
    assert has_received_closing_block(user) is False


async def test_a_failed_closing_block_leaves_the_participant_active(questions, make_user):
    """FINISHED is exactly what takes someone out of the sweep's reach, so it
    must not be set until the block has actually gone out."""
    user = make_user(started_days_ago=DURATION_DAYS)

    with pytest.raises(Forbidden):
        await complete_cycle(RefusingBot(), user)

    assert User.get_by_id(user.telegram_id).status == Status.ACTIVE


async def test_the_sweep_picks_them_up_again(questions, make_user):
    user = make_user(started_days_ago=DURATION_DAYS)

    with pytest.raises(Forbidden):
        await complete_cycle(RefusingBot(), user)

    assert [due.telegram_id for due in users_due_for_completion()] == [user.telegram_id]


async def test_and_the_next_attempt_finishes_them_properly(questions, make_user, bot):
    """End to end: a bad day, then a good one."""
    user = make_user(started_days_ago=DURATION_DAYS)

    with pytest.raises(Forbidden):
        await complete_cycle(RefusingBot(), user)

    await complete_cycle(bot, user)

    assert User.get_by_id(user.telegram_id).status == Status.FINISHED
    assert has_received_closing_block(user) is True
    assert len(bot.sent) == 1


async def test_an_empty_closing_bank_still_finishes_them(questions, make_user, bot):
    """Nothing to send is not a failed send: the participant is done either
    way, and the log says why it was quiet."""
    from core.models import FinalQuestion

    FinalQuestion.delete().execute()
    user = make_user(started_days_ago=DURATION_DAYS)

    assert await complete_cycle(bot, user) is None
    assert User.get_by_id(user.telegram_id).status == Status.FINISHED


# --- a message that cannot be rewritten ------------------------------------

async def test_a_failed_edit_is_swallowed(questions, make_user):
    user = make_user()
    answer = Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="радість", cycle_day=1, message_id=99,
    )

    await show_resolved_answer(UneditableBot(), answer)  # must not raise


async def test_a_failed_edit_does_not_stop_the_follow_up(questions, make_user):
    """Rewriting the question message is the least important thing happening
    after an answer. It used to be able to cancel everything after it."""
    bot = UneditableBot()
    user = make_user(telegram_id=5)
    parent = next(question for question in questions if question.follow_ups)
    answer = Answer.create(
        user=user, question=parent, sent_at=clock.now_kyiv(), cycle_day=1, message_id=99,
    )

    await handle_answer_text(
        text_update(5, "мій запис"), SimpleNamespace(bot=bot, user_data={}),
    )

    assert Answer.get_by_id(answer.id).answer == "мій запис"
    assert len(bot.sent) == 1
    assert list(parent.follow_ups)[0].text in bot.sent[0]["text"]


async def test_a_failed_edit_does_not_stop_the_closing_summary(questions, make_user):
    """The summary, the statistics and the invitation to book a session all sit
    behind this edit — and that invitation is the point of the cycle."""
    bot = UneditableBot()
    user = make_user(telegram_id=6, started_days_ago=DURATION_DAYS, status=Status.FINISHED)
    FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), message_id=99, message_text="1. Що змінилось?",
    )

    await handle_answer_text(
        text_update(6, "стало спокійніше"), SimpleNamespace(bot=bot, user_data={}),
    )

    assert FinalAnswer.get().answer == "стало спокійніше"
    assert len(bot.sent) == 3
    assert "@kryskaks" in bot.sent[2]["text"]
