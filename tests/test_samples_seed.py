"""The demo seeder.

The only tests that depend on `samples/`, and they have to: a seeder is tested
through the data it seeds. Everything else in the suite uses
`tests/factories.py`, so the placeholder content can be replaced with Ксенія's
real bank without a single assertion moving.

What matters here is that re-running it never overwrites edits made through the
admin panel — the seeder is something you might run twice on a live database by
accident, and the only thing standing between that and a wiped question bank is
its own idempotence.
"""
from core.enums import CohortStatus
from core.models import Cohort, FinalQuestion, Question
from core.settings import QUESTION_ORDER_STEP
from samples.data import final_questions, sample_questions
from samples.seed import seed_default_cohort, seed_questions


def test_seeding_fills_both_banks():
    seed_questions()

    rotation = Question.select().where(Question.parent.is_null(True))

    assert rotation.count() == len(sample_questions)
    assert FinalQuestion.select().count() == len(final_questions)


def test_follow_ups_are_attached_rather_than_offered_on_their_own():
    seed_questions()

    for question in Question.select().where(Question.parent.is_null(False)):
        assert question.parent is not None


def test_seeding_twice_changes_nothing():
    seed_questions()
    before = Question.select().count()

    seed_questions()

    assert Question.select().count() == before


def test_seeding_leaves_gaps_in_the_order():
    seed_questions()

    orders = [
        question.order for question in
        Question.select().where(Question.parent.is_null(True)).order_by(Question.order)
    ]

    assert orders[0] == QUESTION_ORDER_STEP
    assert orders[1] - orders[0] == QUESTION_ORDER_STEP


def test_the_default_cohort_states_every_setting():
    """`Cohort` declares no defaults on purpose, so a seeded one that left a
    column out would be a cohort nobody had decided about."""
    cohort = seed_default_cohort()

    assert cohort.is_active is True
    assert cohort.status == CohortStatus.RUNNING
    assert cohort.duration_days
    assert cohort.max_people
    assert cohort.questions_per_day
    assert cohort.categories


def test_an_existing_cohort_is_left_alone():
    first = seed_default_cohort()

    assert seed_default_cohort().id == first.id
    assert Cohort.select().count() == 1
