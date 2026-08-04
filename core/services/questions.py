"""The question bank: which question comes next, and what is still open.

Choosing and bookkeeping only. Drawing the message and sending it belong to
whichever front end is speaking — see `bot/delivery.py` — which is why nothing
here imports `telegram` or a word of the copy participants read.
"""
import random
from datetime import datetime, timedelta

from core import clock
from core.errors import CohortMissing
from core.logs import get_logger
from core.models import Answer, FinalAnswer, FinalQuestion, Question
from core.services.slots import questions_per_slot, saved_slots

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


# --- What is still open ----------------------------------------------------

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


# --- Answer options --------------------------------------------------------

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


# --- The day's quota -------------------------------------------------------

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


# --- Closing block ---------------------------------------------------------

def closing_questions():
    """The closing questions still in use, in the order they are asked."""
    return [
        question.text for question in FinalQuestion.select()
        .where(FinalQuestion.retired == False)  # noqa: E712
        .order_by(FinalQuestion.order)
    ]


def has_received_closing_block(user):
    return FinalAnswer.select().where(FinalAnswer.user == user).exists()


def pending_final_answer(user):
    return (
        FinalAnswer.select()
        .where((FinalAnswer.user == user) & FinalAnswer.answered_at.is_null(True))
        .first()
    )
