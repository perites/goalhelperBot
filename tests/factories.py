"""Test-owned data.

The suite used to build its fixtures by running `samples.seed`, which quietly
made the demo content part of the contract: editing a placeholder question
could turn a test red for no reason, and replacing the placeholders with
Ксенія's real bank — the entire point of them being placeholders — would have
turned a great many red at once.

What is here is deliberately shaped like the sample bank, because the tests
were written against that shape: ten rotation questions covering every
category, the first offering grouped options and a follow-up, five closing
questions. The difference is that it is now the tests' own shape to change.

`samples/` is still exercised, by `test_samples_seed.py`. A seeder is one of
the few things that has to be tested through the data it seeds.
"""
import json
from datetime import timedelta

from core import clock
from core.enums import CohortStatus, QuestionType
from core.models import Cohort, FinalQuestion, Question
from core.settings import QUESTION_ORDER_STEP

# --- the cohort under test -------------------------------------------------

DURATION_DAYS = 30
MAX_PEOPLE = 10
QUESTIONS_PER_DAY = 3
ENROLLMENT_WINDOW_DAYS = 14

CATEGORY_ORDER = [QuestionType.EMOTION, QuestionType.STEP, QuestionType.GRATITUDE]
CATEGORY_ORDER_CSV = ",".join(str(int(category)) for category in CATEGORY_ORDER)

# --- the question bank -----------------------------------------------------

intensity_options = ["1", "2", "3", "4", "5"]

# A nested list is a group: the first item labels it, the rest are choices.
# Several tests reach for `option_list[0][1]`, so the first entry must stay a
# group with at least one choice in it.
emotion_options = [
    ["Радше приємні", "радість", "натхнення", "спокій"],
    ["Радше складні", "тривога", "сум", "втома"],
    "байдужість",
]

# Order matters: tests index into this list, and the fixture returns rotation
# questions ordered by `order`, which follows this sequence.
QUESTION_SPECS = [
    {
        "text": "Тестове питання про емоцію.",
        "type": QuestionType.EMOTION,
        "options": emotion_options,
        "follow_ups": [
            {
                "text": "Наскільки сильно?",
                "type": QuestionType.EMOTION,
                "options": intensity_options,
            },
        ],
    },
    {"text": "Тестове питання про крок.", "type": QuestionType.STEP},
    {"text": "Тестове питання про опору.", "type": QuestionType.SUPPORT},
    {"text": "Тестове питання про вдячність.", "type": QuestionType.GRATITUDE},
    {
        "text": "Тестове питання про перешкоду.",
        "type": QuestionType.OBSTACLE,
        "follow_ups": [
            {"text": "Що з цього простіше?", "type": QuestionType.OBSTACLE},
        ],
    },
    {"text": "Тестове питання про перемогу.", "type": QuestionType.WIN},
    {"text": "Тестове питання про фокус.", "type": QuestionType.FOCUS},
    {"text": "Ще одне тестове питання про крок.", "type": QuestionType.STEP},
    {
        "text": "Ще одне тестове питання про емоцію.",
        "type": QuestionType.EMOTION,
        "options": emotion_options,
        "free_text": True,
        "follow_ups": [
            {"text": "Що вона підказує?", "type": QuestionType.EMOTION},
        ],
    },
    {"text": "Ще одне тестове питання про фокус.", "type": QuestionType.FOCUS},
]

FINAL_QUESTIONS = [
    "Тестове підсумкове питання про намір.",
    "Тестове підсумкове питання про зроблене.",
    "Тестове підсумкове питання про емоції.",
    "Тестове підсумкове питання про крок.",
    "Тестове підсумкове питання про продовження.",
]

# Kept under the name the tests already used, so swapping the source of this
# data did not also mean rewording every assertion about it.
final_questions = FINAL_QUESTIONS


def build_cohort(**overrides):
    """A cohort with every column stated — `Cohort` declares no defaults, on
    purpose, so there is no such thing as a partly-decided one."""
    today = clock.today_kyiv()

    fields = {
        "name": "Пілот",
        "is_active": True,
        "enrollment_opens": today,
        "enrollment_closes": today + timedelta(days=ENROLLMENT_WINDOW_DAYS),
        "duration_days": DURATION_DAYS,
        "max_people": MAX_PEOPLE,
        "questions_per_day": QUESTIONS_PER_DAY,
        "category_order": CATEGORY_ORDER_CSV,
        "status": CohortStatus.RUNNING,
    }
    fields.update(overrides)

    return Cohort.create(**fields)


def _create_question(spec, order, parent=None):
    options = spec.get("options")

    return Question.create(
        text=spec["text"],
        type=spec["type"],
        options=json.dumps(options, ensure_ascii=False) if options else None,
        allows_free_text=spec.get("free_text", False),
        order=order,
        parent=parent,
    )


def build_question_bank():
    """Both banks, with sparse `order` values so a question can be slotted in
    between two others without renumbering — the same convention the seeder
    uses, because `_next_order` in the panel relies on it."""
    for position, spec in enumerate(QUESTION_SPECS, start=1):
        order = position * QUESTION_ORDER_STEP
        parent = _create_question(spec, order)

        # Follow-ups sit inside the parent's gap, so they stay between it and
        # the next rotation question.
        for offset, follow_up in enumerate(spec.get("follow_ups", ()), start=1):
            _create_question(follow_up, order + offset, parent=parent)

    for position, text in enumerate(FINAL_QUESTIONS, start=1):
        FinalQuestion.create(text=text, order=position * QUESTION_ORDER_STEP)

    return list(
        Question.select().where(Question.parent.is_null(True)).order_by(Question.order)
    )
