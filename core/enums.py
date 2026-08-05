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
    """Where a cohort is in its life. Each value decides something.

    PLANNED and ENDED both close enrollment outright. Only RUNNING hands the
    question to the dates and the seat count — so a cohort promoted ahead of
    its opening day still turns people away until that day arrives, and starts
    taking them the moment it does, with nothing left to remember to press.

    The two transitions have different owners. PLANNED -> RUNNING is the
    admin's, deliberately: it is the act of launching a cohort, and nothing
    should do it on a date's say-so. RUNNING -> ENDED belongs to the daily
    sweep, once no participant is still working through their cycle.

    Values are stored in the database, so they are never renumbered. 1 is a
    gap where ENROLLING used to be — it said "taking people" but did not
    actually decide it, which is the job RUNNING now has.
    """

    PLANNED = 0
    RUNNING = 2
    ENDED = 3


class EnrollmentState(IntEnum):
    OPEN = 0
    NOT_OPEN_YET = 1
    FULL = 2
    CLOSED = 3
    NO_COHORT = 4
