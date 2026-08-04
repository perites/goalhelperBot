"""Once resolved, a question message is rewritten to carry its answer."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core import clock
from bot.handlers.answers import (
    handle_answer_text, handle_option_button, handle_skip_button,
)
from core.models import Answer
from bot.closing import send_closing_block
from bot.delivery import send_question, show_resolved_answer
from bot.views import render_question
from bot.texts import question_skipped_suffix
from tests.factories import DURATION_DAYS


def make_update(user, text=None, callback_data=None):
    """Minimal stand-in for a telegram Update."""
    message = SimpleNamespace(text=text, reply_text=AsyncMock())

    query = None
    if callback_data is not None:
        query = SimpleNamespace(
            data=callback_data,
            message=message,
            answer=AsyncMock(),
            edit_message_reply_markup=AsyncMock(),
            edit_message_text=AsyncMock(),
        )

    return SimpleNamespace(
        message=message if callback_data is None else None,
        callback_query=query,
        effective_user=SimpleNamespace(id=user.telegram_id),
    )


def context_for(bot):
    return SimpleNamespace(bot=bot, user_data={}, args=[])


async def test_sending_records_the_message_id(questions, make_user, bot):
    user = make_user()

    answer = await send_question(bot, user)

    assert answer.message_id == bot.sent[0]["message_id"]
    assert Answer.get_by_id(answer.id).message_id is not None


async def test_typed_answer_is_appended_to_the_question(questions, make_user, bot):
    user = make_user()
    answer = await send_question(bot, user)

    update = make_update(user, text="мій маленький крок")
    await handle_answer_text(update, context_for(bot))

    edit = bot.edit_for(answer.message_id)

    assert edit is not None
    assert answer.question.text in edit["text"]
    assert "мій маленький крок" in edit["text"]
    # The question stays above the answer.
    assert edit["text"].index(answer.question.text) < edit["text"].index("мій маленький крок")


async def test_editing_clears_the_buttons(questions, make_user, bot):
    user = make_user()
    answer = await send_question(bot, user)

    await handle_answer_text(make_update(user, text="відповідь"), context_for(bot))

    assert bot.edit_for(answer.message_id)["markup"] is None


async def test_skipping_marks_the_message(questions, make_user, bot):
    user = make_user()
    answer = await send_question(bot, user)

    update = make_update(user, callback_data=f"skip:{answer.id}")
    await handle_skip_button(update, context_for(bot))

    edit = bot.edit_for(answer.message_id)

    assert question_skipped_suffix.strip() in edit["text"]
    assert answer.question.text in edit["text"]


async def test_chosen_option_is_appended(questions, make_user, bot):
    user = make_user()
    emotion = next(q for q in questions if q.option_list)

    while True:
        answer = await send_question(bot, user)
        if answer.question.id == emotion.id:
            break

    # First choice inside the first group.
    update = make_update(user, callback_data=f"option:{answer.id}:0:0")
    await handle_option_button(update, context_for(bot))

    edit = bot.edit_for(answer.message_id)

    assert emotion.option_list[0][1] in edit["text"]


async def test_answer_kept_from_a_later_day_shows_the_original_day(
        questions, make_user, bot, frozen_clock
):
    user = make_user(started_days_ago=4)
    answer = await send_question(bot, user)
    assert answer.cycle_day == 5

    # They reply three days later; the message must still say day 5.
    frozen_clock(days=3)
    await handle_answer_text(make_update(user, text="пізня відповідь"), context_for(bot))

    edit = bot.edit_for(answer.message_id)

    assert "День 5" in edit["text"]
    assert "День 8" not in edit["text"]


async def test_render_survives_rows_without_a_stored_day(questions, make_user, bot):
    user = make_user(started_days_ago=2)
    answer = Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(), cycle_day=None,
    )

    # Falls back to the live cycle day rather than crashing.
    assert "День 3" in render_question(answer)


async def test_nothing_breaks_when_message_id_is_missing(questions, make_user, bot):
    user = make_user()
    answer = Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(), answer="x",
    )

    await show_resolved_answer(bot, answer)

    assert bot.edits == []


async def test_closing_block_answer_is_appended(questions, make_user, bot):
    user = make_user(started_days_ago=DURATION_DAYS - 1)
    closing = await send_closing_block(bot, user)

    await handle_answer_text(make_update(user, text="підсумок мого шляху"), context_for(bot))

    edit = bot.edit_for(closing.message_id)

    assert edit is not None
    assert "підсумок мого шляху" in edit["text"]
    # The five questions are still visible above the answer.
    assert closing.message_text in edit["text"]


async def test_answered_row_is_not_edited_twice(questions, make_user, bot):
    user = make_user()
    answer = await send_question(bot, user)

    await handle_answer_text(make_update(user, text="перша"), context_for(bot))
    edits_to_original = len([e for e in bot.edits if e["message_id"] == answer.message_id])

    # A later message resolves whatever is open next, never this row again.
    await handle_answer_text(make_update(user, text="друга"), context_for(bot))

    assert len([e for e in bot.edits if e["message_id"] == answer.message_id]) == edits_to_original
    assert Answer.get_by_id(answer.id).answer == "перша"
