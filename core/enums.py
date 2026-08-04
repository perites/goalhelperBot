"""Domain vocabulary.

Kept apart from models.py so that texts.py can label a question type without
importing the database layer.
"""
from enum import IntEnum


class Status(IntEnum):
    ONBOARDING = 0
    ACTIVE = 1
    PAUSED = 2
    FINISHED = 3
    STOPPED = 4
    WAITLIST = 5
    DECLINED = 6


class IntentionCategory(IntEnum):
    """The nine ways a participant's «Я хочу» can begin.

    A member's *value* is what `User.intention_type` stores and what the
    onboarding keyboard sends back, so reordering these reassigns the category
    of every participant already in the database. The wording lives in
    `bot/texts.py::category_labels`, in this order — `test_texts.py` checks the
    two have not drifted apart.
    """
    START = 0
    FINISH = 1
    LEARN = 2
    BUILD_HABIT = 3
    GET_RESULT = 4
    BECOME_MORE = 5
    LET_GO = 6
    FIGURE_OUT = 7
    OTHER = 8


class QuestionType(IntEnum):
    EMOTION = 0
    STEP = 1
    SUPPORT = 2
    GRATITUDE = 3
    OBSTACLE = 4
    WIN = 5
    FOCUS = 6


class CohortStatus(IntEnum):
    """Where a cohort is in its life.

    Only ENDED changes what the bot does — it is what closes enrollment for
    good, via `enrollment_state`. The other three are labels the admin sets and
    reads; whether a cohort is taking people is decided by its dates, its
    capacity and `is_active`, not by this. Kept as-is because the values are
    already stored in the database.
    """

    PLANNED = 0
    ENROLLING = 1
    RUNNING = 2
    ENDED = 3


class EnrollmentState(IntEnum):
    OPEN = 0
    NOT_OPEN_YET = 1
    FULL = 2
    CLOSED = 3
    NO_COHORT = 4
