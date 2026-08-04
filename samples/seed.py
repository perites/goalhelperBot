"""Load the sample data into a database.

Run it yourself when you want it — nothing does this for you:

    python -m samples.seed

Both steps are idempotent: an existing question bank or cohort is left exactly
as it is, so re-running never overwrites edits made through the admin panel.
"""
import json
from datetime import timedelta

from bot import clock
from bot.config import QUESTION_ORDER_STEP
from bot.enums import CohortStatus
from bot.logs import configure_logging, get_logger
from bot.models import Cohort, FinalQuestion, Question, initialize_database
from samples.data import (
    CATEGORY_ORDER_CSV,
    DURATION_DAYS,
    ENROLLMENT_WINDOW_DAYS,
    MAX_PEOPLE,
    QUESTIONS_PER_DAY,
    final_questions,
    sample_questions,
)

# Named explicitly: run as `-m`, __name__ is "__main__", which would log as
# "bot.__main__" and read as though the bot itself had done the seeding.
logger = get_logger("samples.seed")


def _encode_options(options):
    return json.dumps(options, ensure_ascii=False) if options else None


def _create_question(spec, order, parent=None):
    """One seed entry. Everything but text and type is optional."""
    return Question.create(
        text=spec["text"],
        type=spec["type"],
        options=_encode_options(spec.get("options")),
        allows_free_text=spec.get("free_text", False),
        order=order,
        parent=parent,
    )


def seed_questions():
    """Populate both banks once, leaving sparse gaps in `order` so questions
    can be inserted later without renumbering."""
    if not Question.select().exists():
        for position, spec in enumerate(sample_questions, start=1):
            order = position * QUESTION_ORDER_STEP
            parent = _create_question(spec, order)

            # Follow-ups sit inside the parent's order gap, so they stay
            # between it and the next rotation question.
            for offset, follow_up in enumerate(spec.get("follow_ups", ()), start=1):
                _create_question(follow_up, order + offset, parent=parent)

    if not FinalQuestion.select().exists():
        for position, text in enumerate(final_questions, start=1):
            FinalQuestion.create(text=text, order=position * QUESTION_ORDER_STEP)

    logger.info(
        "Question banks ready: %s daily, %s closing",
        Question.select().count(), FinalQuestion.select().count(),
    )


def seed_default_cohort():
    """Create a cohort if none exists, so the bot has one to enrol into."""
    if Cohort.select().exists():
        return Cohort.select().first()

    today = clock.today_kyiv()

    # Every column is given: Cohort declares no defaults, so a cohort that
    # left one out would be one nobody had decided about.
    cohort = Cohort.create(
        name="Пілот",
        is_active=True,
        enrollment_opens=today,
        enrollment_closes=today + timedelta(days=ENROLLMENT_WINDOW_DAYS),
        duration_days=DURATION_DAYS,
        max_people=MAX_PEOPLE,
        questions_per_day=QUESTIONS_PER_DAY,
        category_order=CATEGORY_ORDER_CSV,
        status=CohortStatus.ENROLLING,
    )

    logger.warning(
        "No cohort existed; created a default one open %s..%s with %s seats. "
        "Set real dates before the pilot starts.",
        cohort.enrollment_opens, cohort.enrollment_closes, cohort.max_people,
    )

    return cohort


def main():
    configure_logging()
    logger.info("Seeding sample data")

    initialize_database()
    seed_questions()
    seed_default_cohort()

    logger.info("Sample data loaded")


if __name__ == "__main__":
    main()
