"""Deletion rules: what may be removed for good, and what must be retired.

The panel greys out its buttons using the same functions, but these tests go
straight at the service — a forged POST reaches this layer and nothing else
stands between it and the row.
"""
import peewee
import pytest

from core import clock
from core.enums import CohortStatus, Status
from core.models import Answer, Cohort, FinalAnswer, FinalQuestion, Question, User, db
from core.services.deletion import (
    DeletionBlocked,
    cohort_blocker,
    delete_cohort,
    delete_final_question,
    delete_question,
    final_question_blocker,
    question_blocker,
)
from tests.factories import (
    CATEGORY_ORDER_CSV, DURATION_DAYS, MAX_PEOPLE, QUESTIONS_PER_DAY,
)


def make_question(text="Нове питання", parent=None, order=9000):
    return Question.create(text=text, type=0, order=order, parent=parent)


# --- daily questions -------------------------------------------------------

def test_unused_question_is_deletable():
    question = make_question()

    assert question_blocker(question) is None

    delete_question(question)

    assert Question.get_or_none(Question.id == question.id) is None


def test_question_with_an_answer_is_kept(make_user):
    question = make_question()
    user = make_user()
    Answer.create(
        user=user, question=question,
        sent_at=clock.now_kyiv(), answered_at=clock.now_kyiv(), answer="так",
    )

    assert "відповідей: 1" in question_blocker(question)

    with pytest.raises(DeletionBlocked):
        delete_question(question)

    assert Question.get_or_none(Question.id == question.id) is not None


def test_question_awaiting_a_reply_is_kept(make_user):
    """Sent but unanswered still counts — the row is sitting in someone's chat."""
    question = make_question()
    Answer.create(user=make_user(), question=question, sent_at=clock.now_kyiv())

    assert "очікує на відповідь: 1" in question_blocker(question)

    with pytest.raises(DeletionBlocked):
        delete_question(question)


def test_skipped_question_is_kept(make_user):
    """A skip is a recorded reaction, not an absence of one."""
    question = make_question()
    Answer.create(
        user=make_user(), question=question, sent_at=clock.now_kyiv(), skipped=True,
    )

    assert question_blocker(question) is not None

    with pytest.raises(DeletionBlocked):
        delete_question(question)


def test_question_with_follow_ups_is_kept():
    """Nothing cascades, so a deleted parent would orphan its children."""
    parent = make_question(order=9000)
    make_question(text="Уточнення", parent=parent, order=9001)

    assert "уточнення (1)" in question_blocker(parent)

    with pytest.raises(DeletionBlocked):
        delete_question(parent)


def test_follow_up_can_be_deleted_then_its_parent():
    parent = make_question(order=9000)
    follow_up = make_question(text="Уточнення", parent=parent, order=9001)

    delete_question(follow_up)
    delete_question(parent)

    assert Question.select().count() == 0


def test_deleting_a_question_leaves_other_answers_alone(make_user):
    """The guard must not be so broad that an unrelated question is protected."""
    kept, doomed = make_question(order=9000), make_question(text="Зайве", order=9001)
    Answer.create(user=make_user(), question=kept, sent_at=clock.now_kyiv())

    delete_question(doomed)

    assert Question.get_or_none(Question.id == kept.id) is not None
    assert Answer.select().count() == 1


# --- closing questions -----------------------------------------------------

def test_unused_final_question_is_deletable():
    question = FinalQuestion.create(text="Що змінилось?", order=10)

    assert final_question_blocker(question) is None

    delete_final_question(question)

    assert FinalQuestion.select().count() == 0


def test_final_question_already_sent_is_kept(make_user):
    """FinalAnswer has no foreign key to individual questions — the stored
    text of the block is what says which ones went out."""
    sent = FinalQuestion.create(text="Що змінилось?", order=10)
    later = FinalQuestion.create(text="Додане пізніше", order=20)

    FinalAnswer.create(
        user=make_user(), sent_at=clock.now_kyiv(),
        message_text="Підсумок:\n1. Що змінилось?",
    )

    assert final_question_blocker(sent) is not None
    # A question added after the block went out was never in it.
    assert final_question_blocker(later) is None

    with pytest.raises(DeletionBlocked):
        delete_final_question(sent)

    delete_final_question(later)


def test_final_question_is_kept_when_the_sent_text_is_unknown(make_user):
    """Shouldn't arise, but an unreadable record must not read as 'unused'."""
    question = FinalQuestion.create(text="Що змінилось?", order=10)
    FinalAnswer.create(user=make_user(), sent_at=clock.now_kyiv(), message_text=None)

    assert final_question_blocker(question) is not None

    with pytest.raises(DeletionBlocked):
        delete_final_question(question)


# --- cohorts ---------------------------------------------------------------

def make_cohort(name="Друга", is_active=False):
    today = clock.today_kyiv()

    # Cohort declares no defaults, so every setting has to be stated.
    return Cohort.create(
        name=name, is_active=is_active,
        enrollment_opens=today, enrollment_closes=today,
        duration_days=DURATION_DAYS, max_people=MAX_PEOPLE,
        questions_per_day=QUESTIONS_PER_DAY, category_order=CATEGORY_ORDER_CSV,
        status=CohortStatus.PLANNED,
    )


def test_empty_inactive_cohort_is_deletable():
    cohort = make_cohort()

    assert cohort_blocker(cohort) is None

    delete_cohort(cohort)

    assert Cohort.get_or_none(Cohort.id == cohort.id) is None


def test_cohort_with_participants_is_kept(make_user):
    cohort = make_cohort()
    make_user(telegram_id=77, cohort=cohort)

    assert "учасників: 1" in cohort_blocker(cohort)

    with pytest.raises(DeletionBlocked):
        delete_cohort(cohort)

    assert Cohort.get_or_none(Cohort.id == cohort.id) is not None


def test_cohort_with_only_an_onboarding_user_is_still_kept(make_user):
    """No seat taken yet, but the row still points at the cohort."""
    cohort = make_cohort()
    make_user(telegram_id=78, cohort=cohort, status=Status.ONBOARDING)

    assert cohort_blocker(cohort) is not None


def test_active_cohort_is_kept(cohort):
    """Deleting the one new participants join would leave onboarding nowhere
    to put them, even with no one in it yet."""
    assert cohort.is_active
    assert User.select().where(User.cohort == cohort).count() == 0
    assert "активна" in cohort_blocker(cohort)

    with pytest.raises(DeletionBlocked):
        delete_cohort(cohort)


def test_cohort_becomes_deletable_once_another_is_activated(cohort):
    from core.services.cohort import activate_cohort

    replacement = make_cohort(name="Наступна")
    activate_cohort(replacement)

    cohort = Cohort.get_by_id(cohort.id)

    assert cohort_blocker(cohort) is None

    delete_cohort(cohort)

    assert Cohort.select().count() == 1


# --- the constraint underneath ---------------------------------------------

def test_foreign_keys_are_enforced():
    """Everything above depends on this being on — SQLite ignores foreign keys
    by default, and the pragma is per connection."""
    assert db.execute_sql("PRAGMA foreign_keys").fetchone()[0] == 1


def test_declared_as_restrict():
    for table in ("answer", "usertime", "finalanswer", "question", "user"):
        sql = db.execute_sql(
            "SELECT sql FROM sqlite_master WHERE name = ?", (table,)
        ).fetchone()[0]

        assert "REFERENCES" not in sql or "ON DELETE RESTRICT" in sql, table


@pytest.mark.parametrize("model, kwargs", [
    (Answer, {"question": True}),
    (Answer, {"user": True}),
])
def test_database_refuses_the_delete_even_without_the_service(make_user, model, kwargs):
    """The service rules are the friendly guard; this is the one that holds
    when a row is deleted straight through sqlite-web."""
    question = make_question()
    user = make_user()
    Answer.create(user=user, question=question, sent_at=clock.now_kyiv())

    target = question if kwargs.get("question") else user

    with pytest.raises(peewee.IntegrityError):
        target.delete_instance()


def test_database_refuses_to_orphan_a_follow_up():
    parent = make_question(order=9000)
    make_question(text="Уточнення", parent=parent, order=9001)

    with pytest.raises(peewee.IntegrityError):
        parent.delete_instance()


def test_database_refuses_to_drop_a_cohort_with_participants(make_user, cohort):
    make_user(telegram_id=91, cohort=cohort)

    with pytest.raises(peewee.IntegrityError):
        cohort.delete_instance()


def test_blocked_delete_leaves_the_transaction_usable():
    """The guard raises inside db.atomic(); the session must survive it."""
    question = make_question(order=9000)
    Answer.create(
        user=User.create(
            telegram_id=99, name="N", consent=True,
            status=Status.ACTIVE, date_started=clock.now_kyiv(),
        ),
        question=question, sent_at=clock.now_kyiv(),
    )

    with pytest.raises(DeletionBlocked):
        delete_question(question)

    # Still able to read and write afterwards.
    assert Question.select().count() == 1
    make_question(text="Ще одне", order=9001)
    assert Question.select().count() == 2
