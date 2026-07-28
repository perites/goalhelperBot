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
