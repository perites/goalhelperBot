"""Question bank: rotation and delivery.

Pure service layer — no Telegram handlers live here, so nothing in this module
needs to know about updates or callbacks.
"""
import random
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from bot import clock
from bot.config import (
    BACK_ACTION,
    OPTIONS_PER_ROW,
    SHORT_OPTION_LENGTH,
)
from bot.errors import CohortMissing
from bot.logs import get_logger
from bot.models import Answer, FinalAnswer, FinalQuestion, Question
from bot.services.slots import questions_per_slot, saved_slots
from bot.texts import (
    final_questions_block,
    question_answer_button,
    question_back_button,
    question_free_text_button,
    question_answered_suffix,
    question_message_template,
    question_skip_button,
    question_skipped_suffix,
)

logger = get_logger(__name__)


# --- Daily rotation --------------------------------------------------------

def rotation_questions():
    """The daily bank: follow-ups are reachable only through their parent, and
    retired questions are kept for their history but never sent again."""
    return Question.select().where(
        Question.parent.is_null(True)
        & (Question.retired == False)  # noqa: E712 - peewee needs the comparison
    )


def category_order_for(user):
    """The category rhythm this user's cohort runs on."""
    if user.cohort is None:
        raise CohortMissing(user, "the category order")

    return user.cohort.categories


def category_at(order, index):
    """Wraps, so an index left over from a longer order list is still valid."""
    return order[index % len(order)]


def last_rotation_answer(user):
    """Their most recent daily question. Follow-ups are excluded — they don't
    advance the category cycle."""
    return (
        Answer.select()
        .where((Answer.user == user) & Answer.parent.is_null(True))
        .order_by(Answer.sent_at.desc(), Answer.id.desc())
        .first()
    )


def next_category_index(user, order):
    """Where this user is in the category cycle."""
    last = last_rotation_answer(user)

    if last is None or last.category_index is None:
        return 0

    return (last.category_index + 1) % len(order)


def pick_from_category(user, category, rng=None):
    """A question of this type, favouring the ones this user has seen least
    recently and choosing at random between equals.

    Never-sent questions sort first, so early on this is simply "something
    new". Once the category has been exhausted it recycles the oldest, which
    means the pool never runs dry and there's no round counter to keep.
    """
    candidates = list(rotation_questions().where(Question.type == category))
    if not candidates:
        return None

    # Folded in Python rather than with MAX(): SQLite returns an aggregate
    # over a datetime column as text, which wouldn't compare against the
    # datetime.min sentinel below.
    last_seen = {}
    for row in Answer.select(Answer.question, Answer.sent_at).where(
            (Answer.user == user) & Answer.parent.is_null(True)
    ):
        seen = last_seen.get(row.question_id)
        if seen is None or row.sent_at > seen:
            last_seen[row.question_id] = row.sent_at

    def seen_at(question):
        # Never sent sorts before everything, so unseen questions come first.
        return last_seen.get(question.id) or datetime.min

    oldest = min(seen_at(question) for question in candidates)
    least_recent = [question for question in candidates if seen_at(question) == oldest]

    return (rng or random).choice(least_recent)


def next_question_for(user, rng=None):
    """The next daily question: take the next category in the cycle and pick
    from it. Categories with nothing in them are skipped rather than stalling,
    so an order list can name a category before its questions exist."""
    order = category_order_for(user)
    if not order:
        # A cohort whose category_order is empty or parses to nothing. Every
        # step below divides by its length, so this is checked once here
        # rather than defended against in each of them.
        logger.warning(
            "Cohort id=%s has no usable category order; nothing to send to user=%s",
            user.cohort_id, user.telegram_id,
        )
        return None, None

    start = next_category_index(user, order)

    for offset in range(len(order)):
        index = (start + offset) % len(order)
        category = category_at(order, index)
        question = pick_from_category(user, category, rng=rng)

        if question is not None:
            return question, index

        logger.debug("No questions for category %s; skipping", category.name)

    return None, None


def pending_answer(user):
    """The one question still awaiting a reply, if any."""
    return Answer.open_for(user).order_by(Answer.sent_at).first()


def close_open_answers(user):
    """Mark anything still unanswered as skipped, so a user has at most one
    open question at a time."""
    return (
        Answer.update(skipped=True)
        .where(Answer.id.in_(Answer.open_for(user).select(Answer.id)))
        .execute()
    )


def is_group(option):
    """A nested list is a group: [label, option, option, ...]."""
    return isinstance(option, (list, tuple))


def group_options(option):
    """The choices inside a group, or an empty list if it only has a label."""
    return list(option[1:]) if is_group(option) else []


def option_at(options, path):
    """Resolve a callback path — (index,) or (group, index) — to the option
    text it names. Returns None for anything out of range or the wrong shape,
    so a stale button can't index into the wrong thing."""
    if not options:
        return None

    first, *rest = path

    if first >= len(options):
        return None

    entry = options[first]

    if not rest:
        return None if is_group(entry) else entry

    inner = group_options(entry)
    index = rest[0]

    return inner[index] if index < len(inner) else None


def _option_rows(buttons):
    """Short labels share a row so a 1–5 scale reads horizontally; anything
    longer gets a row to itself."""
    rows = []
    row_is_short = False

    for button in buttons:
        short = len(button.text) <= SHORT_OPTION_LENGTH
        can_share = short and row_is_short and rows and len(rows[-1]) < OPTIONS_PER_ROW

        if can_share:
            rows[-1].append(button)
        else:
            rows.append([button])
            row_is_short = short

    return rows


def build_question_keyboard(question, answer, group=None):
    """Top level when `group` is None, otherwise that group's choices.

    Which level is showing lives entirely in the callback data, so opening a
    group is just a keyboard swap on the same message — nothing to store and
    nothing to lose on a restart.
    """
    options = question.option_list

    if not options:
        keyboard = [[InlineKeyboardButton(question_answer_button, callback_data=f"answer:{answer.id}")]]
        keyboard.append([InlineKeyboardButton(question_skip_button, callback_data=f"skip:{answer.id}")])

        return InlineKeyboardMarkup(keyboard)

    if group is None:
        buttons = []
        for index, entry in enumerate(options):
            if is_group(entry):
                # A group with a label but no choices would open an empty
                # screen, so it simply isn't offered.
                if group_options(entry):
                    buttons.append(
                        InlineKeyboardButton(entry[0], callback_data=f"group:{answer.id}:{index}")
                    )
            else:
                buttons.append(
                    InlineKeyboardButton(entry, callback_data=f"option:{answer.id}:{index}")
                )

        keyboard = _option_rows(buttons)

        # Carries the same callback as [Відповісти] on an open question: it
        # prompts and leaves the row unresolved, so the ordinary text handler
        # picks the reply up. Top level only — Повернутись is one tap away.
        if question.allows_free_text:
            keyboard.append([
                InlineKeyboardButton(
                    question_free_text_button, callback_data=f"answer:{answer.id}"
                )
            ])
    else:
        keyboard = _option_rows([
            InlineKeyboardButton(choice, callback_data=f"option:{answer.id}:{group}:{index}")
            for index, choice in enumerate(group_options(options[group]))
        ])
        keyboard.append([
            InlineKeyboardButton(
                question_back_button, callback_data=f"group:{answer.id}:{BACK_ACTION}"
            )
        ])

    keyboard.append([InlineKeyboardButton(question_skip_button, callback_data=f"skip:{answer.id}")])

    return InlineKeyboardMarkup(keyboard)


def render_question(answer):
    """The question message as it was originally sent. Uses the stored
    cycle_day so a reply arriving the next day doesn't redraw a wrong number."""
    # A follow-up arrives mid-exchange, so it skips the day/intention header
    # that has just been shown above it.
    if answer.parent_id is not None:
        return answer.question.text

    user = answer.user

    return question_message_template.format(
        day=answer.cycle_day if answer.cycle_day is not None else user.cycle_day,
        total=user.cycle_length,
        intention=user.intention,
        question=answer.question.text,
    )


async def _send_for_row(bot, row, chat_id, text, reply_markup=None):
    """Send the message a just-created row stands for, and undo the row if it
    doesn't arrive.

    The row has to exist before the send: the keyboard's callback data is built
    from its id. But a row is also the only thing that says a question is
    waiting for an answer — so one left behind by a failed send is worse than
    no row at all. It would make the slot look already started, and the next
    thing the participant typed about anything else would be filed as the
    answer to a question they never saw.

    Telegram refuses sends for ordinary reasons — the participant blocked the
    bot, deleted their account, or we're being rate limited — so this is a
    normal path, not a corruption case. The caller sees the original error.
    """
    try:
        message = await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup,
        )
    except Exception:
        row.delete_instance()
        raise

    if message is not None:
        row.message_id = message.message_id
        row.save()

    return message


async def send_question(bot, user, slot=None, rng=None):
    """Close out the previous question, then send the next one."""
    close_open_answers(user)

    question, category_index = next_question_for(user, rng=rng)
    if question is None:
        return None

    answer = Answer.create(
        user=user,
        question=question,
        sent_at=clock.now_kyiv(),
        cycle_day=user.cycle_day,
        slot=slot,
        category_index=category_index,
    )

    await _send_for_row(
        bot, answer,
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

    logger.debug(
        "Question sent: user=%s answer=%s question=%s day=%s",
        user.telegram_id, answer.id, question.id, answer.cycle_day,
    )

    return answer


async def deliver_question(bot, user, reason, slot=None):
    """Send the next question and log the outcome. Returns the Answer, or None
    if nothing went out.

    Never raises — one unreachable user (blocked the bot, deleted account)
    must not break whatever loop the caller is in. `reason` says what
    triggered it, so the log distinguishes scheduled sends from manual ones.
    """
    try:
        answer = await send_question(bot, user, slot=slot)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to send question to user=%s (%s)", user.telegram_id, reason, exc_info=True
        )
        return None

    if answer is None:
        logger.warning(
            "Question bank is empty; nothing sent to user=%s (%s)", user.telegram_id, reason
        )
        return None

    logger.info(
        "Sent question to user=%s day=%s question=%s slot=%s (%s)",
        user.telegram_id, answer.cycle_day, answer.question_id, slot or "-", reason,
    )

    return answer


def sent_in_slot_today(user, slot):
    """How many questions have gone out for this slot today.

    Follow-ups don't count: a question and its follow-up are one reflective
    unit, so a quota of three means three topics rather than three messages.
    """
    if slot is None:
        return 0

    day_start = clock.now_kyiv().replace(hour=0, minute=0, second=0, microsecond=0)

    return (
        Answer.select()
        .where(
            (Answer.user == user)
            & (Answer.slot == slot)
            & Answer.parent.is_null(True)
            & (Answer.sent_at >= day_start)
            & (Answer.sent_at < day_start + timedelta(days=1))
        )
        .count()
    )


def next_follow_up(parent_answer):
    """The next unasked follow-up for this particular answer.

    Keyed on the answer, not the question, so the same question asked again on
    a later day gets its follow-up again.
    """
    already_asked = Answer.select(Answer.question).where(Answer.parent == parent_answer)

    return (
        Question.select()
        .where(
            (Question.parent == parent_answer.question_id)
            & Question.id.not_in(already_asked)
        )
        .order_by(Question.order)
        .first()
    )


async def send_follow_up(bot, user, parent_answer):
    """Send the next follow-up to an answer, if that question has one."""
    question = next_follow_up(parent_answer)
    if question is None:
        return None

    answer = Answer.create(
        user=user,
        question=question,
        sent_at=clock.now_kyiv(),
        cycle_day=parent_answer.cycle_day,
        # Carried for the record; the quota above ignores follow-ups anyway.
        slot=parent_answer.slot,
        parent=parent_answer,
    )

    await _send_for_row(
        bot, answer,
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

    logger.info(
        "Sent follow-up to user=%s question=%s (after answer=%s)",
        user.telegram_id, question.id, parent_answer.id,
    )

    return answer


def daily_total_for(user):
    """How many questions a day this user's cohort asks for."""
    if user.cohort is None:
        raise CohortMissing(user, "the daily question total")

    return user.cohort.questions_per_day


def slot_quota(user, slot):
    """How many questions this slot owes today, which depends on the cohort's
    daily total and how many other slots the user picked."""
    spread = questions_per_slot(saved_slots(user), total=daily_total_for(user))

    return spread.get(slot, 0)


async def send_next_in_slot(bot, user, slot):
    """Continue a slot's run, if the day's quota leaves room. Returns None
    when the run is finished, which is the caller's cue to acknowledge the
    answer instead."""
    if slot is None:
        return None

    already = sent_in_slot_today(user, slot)
    quota = slot_quota(user, slot)

    if already >= quota:
        logger.debug(
            "Slot %s finished for user=%s (%s of %s)",
            slot, user.telegram_id, already, quota,
        )
        return None

    return await deliver_question(bot, user, reason="chain", slot=slot)


async def show_resolved_answer(bot, answer):
    """Rewrite the original question message so the answer sits beneath it,
    which also clears the buttons."""
    if answer.message_id is None:
        return

    body = render_question(answer)
    body += (
        question_skipped_suffix if answer.skipped
        else question_answered_suffix.format(answer=answer.answer)
    )

    # Tidying the chat history is the least important thing happening here. The
    # answer is already saved, and a follow-up or the closing block may still
    # be due — so a message that can't be rewritten (deleted, chat cleared,
    # text unchanged) must not take those down with it. INFO, not WARNING:
    # this is an ordinary thing for a participant to cause, and WARNING would
    # put it on Ксенія's phone.
    try:
        await bot.edit_message_text(
            chat_id=answer.user.telegram_id,
            message_id=answer.message_id,
            text=body,
        )
    except TelegramError:
        logger.info(
            "Could not rewrite the question message for answer=%s; the answer "
            "itself is saved", answer.id, exc_info=True,
        )


# --- Closing block ---------------------------------------------------------

def has_received_closing_block(user):
    return FinalAnswer.select().where(FinalAnswer.user == user).exists()


def pending_final_answer(user):
    return (
        FinalAnswer.select()
        .where((FinalAnswer.user == user) & FinalAnswer.answered_at.is_null(True))
        .first()
    )


async def send_closing_block(bot, user):
    """The closing questions as one message. No buttons — it stays open
    indefinitely until the user replies."""
    close_open_answers(user)

    questions = [
        q.text for q in FinalQuestion.select()
        .where(FinalQuestion.retired == False)  # noqa: E712
        .order_by(FinalQuestion.order)
    ]
    if not questions:
        logger.warning("Closing block requested but no closing questions exist")
        return None

    body = final_questions_block(user.cycle_length, questions)
    final_answer = FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), message_text=body,
    )

    # The row is what `has_received_closing_block` reads, and the daily sweep
    # uses that to decide who still needs one — so a row surviving a failed
    # send would retire the participant without ever asking them anything.
    await _send_for_row(bot, final_answer, chat_id=user.telegram_id, text=body)

    logger.info("Closing block sent to user=%s (%s questions)", user.telegram_id, len(questions))

    return final_answer


async def show_resolved_final_answer(bot, final_answer):
    """Same treatment for the closing block. Its text is stored rather than
    re-rendered because the question list could be edited in between."""
    if final_answer.message_id is None or final_answer.message_text is None:
        return

    # Cosmetic, and the summary that follows is not — see show_resolved_answer.
    try:
        await bot.edit_message_text(
            chat_id=final_answer.user.telegram_id,
            message_id=final_answer.message_id,
            text=final_answer.message_text + question_answered_suffix.format(
                answer=final_answer.answer
            ),
        )
    except TelegramError:
        logger.info(
            "Could not rewrite the closing block for user=%s; the answer itself "
            "is saved", final_answer.user_id, exc_info=True,
        )
