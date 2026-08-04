"""Question rotation, wrap-around, and open-question bookkeeping."""
from core import clock
from core.settings import QUESTION_ORDER_STEP
from core.models import Answer, FinalQuestion, Question
from core.services.questions import (
    close_open_answers, next_question_for, pick_from_category,
)
from tests.factories import CATEGORY_ORDER, FINAL_QUESTIONS


def test_the_bank_leaves_gaps_in_the_order(questions):
    """Sparse, so a question can be slotted between two others without
    renumbering — which is what the panel's `_next_order` assumes."""
    orders = [question.order for question in questions]

    assert orders == sorted(orders)
    assert orders[0] == QUESTION_ORDER_STEP
    assert orders[1] - orders[0] == QUESTION_ORDER_STEP


def test_closing_questions_are_not_in_the_daily_bank(questions):
    assert FinalQuestion.select().count() == len(FINAL_QUESTIONS)
    # The daily bank is its own table, so no filtering is needed.
    assert all(isinstance(question, Question) for question in questions)


def test_cold_start_uses_the_first_category(questions, make_user):
    user = make_user()

    question, index = next_question_for(user)

    assert index == 0
    assert question.type == CATEGORY_ORDER[0]


def test_categories_advance_in_order_then_wrap(questions, make_user, frozen_clock):
    user = make_user()
    seen = []

    for _ in range(len(CATEGORY_ORDER) + 2):
        question, index = next_question_for(user)
        seen.append(question.type)
        Answer.create(
            user=user, question=question, sent_at=clock.now_kyiv(), category_index=index,
        )
        frozen_clock(hours=1)

    assert seen[:len(CATEGORY_ORDER)] == list(CATEGORY_ORDER)
    # Past the end it starts again rather than stopping.
    assert seen[len(CATEGORY_ORDER):] == list(CATEGORY_ORDER[:2])


def test_each_user_has_their_own_position(questions, make_user):
    first = make_user(telegram_id=1)
    second = make_user(telegram_id=2)

    question, index = next_question_for(first)
    Answer.create(
        user=first, question=question, sent_at=clock.now_kyiv(), category_index=index,
    )

    assert next_question_for(first)[1] == 1
    assert next_question_for(second)[1] == 0


def test_unseen_questions_come_before_repeats(questions, make_user, frozen_clock):
    """Within a category, everything is shown once before anything repeats."""
    user = make_user()
    category = CATEGORY_ORDER[0]
    in_category = [q for q in questions if q.type == category]

    picked = []
    for _ in range(len(in_category)):
        question = pick_from_category(user, category)
        picked.append(question.id)
        Answer.create(user=user, question=question, sent_at=clock.now_kyiv())
        frozen_clock(hours=1)

    assert sorted(picked) == sorted(q.id for q in in_category)

    # The pool is exhausted; it recycles rather than returning nothing.
    assert pick_from_category(user, category) is not None


def test_empty_category_is_skipped(questions, make_user):
    """An order list may name a category before its questions are written."""
    user = make_user()
    first = CATEGORY_ORDER[0]

    # Follow-ups go before the questions they hang off — the database now
    # refuses to leave one pointing at a row that no longer exists.
    doomed = Question.select(Question.id).where(Question.type == first)
    Question.delete().where(Question.parent.in_(doomed)).execute()
    Question.delete().where(Question.type == first).execute()

    question, index = next_question_for(user)

    assert question is not None
    assert index != 0


def test_no_questions_at_all_returns_nothing(make_user):
    user = make_user()

    assert next_question_for(user) == (None, None)


def test_close_open_questions_marks_only_unresolved(questions, make_user):
    user = make_user()
    now = clock.now_kyiv()

    unanswered = Answer.create(user=user, question=questions[0], sent_at=now)
    answered = Answer.create(
        user=user, question=questions[1], sent_at=now, answered_at=now, answer="hi"
    )

    close_open_answers(user)

    assert Answer.get_by_id(unanswered.id).skipped is True
    assert Answer.get_by_id(answered.id).skipped is False
    assert Answer.get_by_id(answered.id).answer == "hi"


def test_close_open_questions_leaves_other_users_alone(questions, make_user):
    mine = make_user(telegram_id=1)
    theirs = make_user(telegram_id=2)
    now = clock.now_kyiv()

    other = Answer.create(user=theirs, question=questions[0], sent_at=now)
    close_open_answers(mine)

    assert Answer.get_by_id(other.id).skipped is False
