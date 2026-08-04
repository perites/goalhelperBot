"""Sending questions, the day-30 handoff, and the closing block."""
from core.enums import Status
from core.models import Answer, FinalAnswer, FinalQuestion, User
from bot.closing import complete_cycle, send_closing_block, send_closing_summary
from bot.delivery import send_question
from core.services.questions import (
    close_open_answers, has_received_closing_block, pending_final_answer,
)
from tests.factories import DURATION_DAYS
from tests.factories import final_questions


async def test_send_question_creates_a_pending_row(questions, make_user, bot):
    user = make_user()

    answer = await send_question(bot, user)

    assert answer.answered_at is None
    assert answer.skipped is False
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == user.telegram_id


async def test_question_message_shows_day_and_intention(questions, make_user, bot):
    user = make_user(started_days_ago=4)

    await send_question(bot, user)
    text = bot.texts[0]

    assert "5" in text
    assert user.intention in text
    assert "{" not in text


async def test_sending_closes_the_previous_question(questions, make_user, bot, frozen_clock):
    user = make_user()

    first = await send_question(bot, user)
    frozen_clock(hours=4)
    await send_question(bot, user)

    assert Answer.get_by_id(first.id).skipped is True
    # At most one question is ever open.
    assert Answer.select().where(
        (Answer.user == user) & Answer.answered_at.is_null(True) & (Answer.skipped == False)
    ).count() == 1


async def test_choice_question_offers_its_options(questions, make_user, bot):
    user = make_user()
    emotion = next(q for q in questions if q.option_list)

    # Walk the rotation to the emotion question.
    while True:
        answer = await send_question(bot, user)
        if answer.question.id == emotion.id:
            break

    markup = bot.sent[-1]["markup"]
    labels = [b.text for row in markup.inline_keyboard for b in row]

    # A grouped option shows its label; a plain one shows itself.
    first = emotion.option_list[0]
    assert (first[0] if isinstance(first, list) else first) in labels


async def test_closing_block_is_one_message_with_all_questions(questions, make_user, bot):
    user = make_user(started_days_ago=DURATION_DAYS - 1)

    await send_closing_block(bot, user)

    assert len(bot.sent) == 1
    text = bot.texts[0]
    for question in final_questions:
        assert question in text


async def test_closing_block_has_no_buttons(questions, make_user, bot):
    user = make_user()

    await send_closing_block(bot, user)

    # It waits indefinitely, so there's nothing to skip with.
    assert bot.sent[0]["markup"] is None


async def test_closing_block_is_not_an_answer_row(questions, make_user, bot):
    user = make_user()

    await send_closing_block(bot, user)

    assert Answer.select().where(Answer.user == user).count() == 0
    assert FinalAnswer.select().where(FinalAnswer.user == user).count() == 1


async def test_complete_cycle_finishes_and_sends(questions, make_user, bot):
    user = make_user(started_days_ago=DURATION_DAYS - 1)

    await complete_cycle(bot, user)

    assert User.get_by_id(user.telegram_id).status == Status.FINISHED
    assert has_received_closing_block(user) is True
    assert pending_final_answer(user) is not None


async def test_complete_cycle_will_not_send_twice(questions, make_user, bot):
    user = make_user(started_days_ago=DURATION_DAYS - 1)

    await complete_cycle(bot, user)
    await complete_cycle(bot, user)

    assert FinalAnswer.select().where(FinalAnswer.user == user).count() == 1
    assert len(bot.sent) == 1


async def test_closing_block_survives_close_open_questions(questions, make_user, bot):
    user = make_user(started_days_ago=DURATION_DAYS - 1)
    await complete_cycle(bot, user)

    # Separate tables, so daily housekeeping can't touch the open block.
    close_open_answers(user)

    assert pending_final_answer(user) is not None


async def test_closing_summary_sends_stats_and_invite(questions, make_user, bot):
    user = make_user(started_days_ago=DURATION_DAYS - 1)

    await send_closing_summary(bot, user)

    assert len(bot.sent) == 3
    assert "статистика" in bot.texts[1].lower()
    assert "@kryskaks" in bot.texts[2]
    assert all("{" not in text for text in bot.texts)


async def test_finished_user_stops_receiving_daily_questions(questions, make_user, bot):
    from bot.scheduler import users_due_at

    user = make_user(telegram_id=1, slots=(9,), started_days_ago=DURATION_DAYS - 1)
    await complete_cycle(bot, user)

    assert users_due_at(9) == []


async def test_closing_questions_come_from_the_database(questions, make_user, bot):
    FinalQuestion.delete().execute()
    FinalQuestion.create(text="Єдине питання?", order=10)

    user = make_user()
    await send_closing_block(bot, user)

    assert "Єдине питання?" in bot.texts[0]
    assert final_questions[0] not in bot.texts[0]
