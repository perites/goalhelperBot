import json
from datetime import datetime, timedelta
from enum import IntEnum

from peewee import (
    SqliteDatabase, Model, IntegerField, CharField, TextField,
    BooleanField, SQL, DateField, DateTimeField, ForeignKeyField, TimeField,
)

db = SqliteDatabase("goalbot.db")

CYCLE_LENGTH_DAYS = 30
PAUSE_DURATION_DAYS = 3
DEFAULT_MAX_PEOPLE = 10
DEFAULT_ENROLLMENT_WINDOW_DAYS = 14


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


class BaseModel(Model):
    class Meta:
        database = db


class Cohort(BaseModel):
    """One pilot run. Holds the enrollment window and capacity — note it has no
    start/end for the 30 days themselves, because each participant's cycle runs
    from their own onboarding completion (ТЗ: "День 1 рахується від дати
    завершення онбордингу")."""
    enrollment_opens = DateField()
    enrollment_closes = DateField()
    duration_days = IntegerField(default=CYCLE_LENGTH_DAYS)
    max_people = IntegerField(default=DEFAULT_MAX_PEOPLE)
    status = IntegerField(default=CohortStatus.PLANNED)


class User(BaseModel):
    telegram_id = IntegerField(primary_key=True)
    username = CharField()
    name = CharField(null=True)
    intention = TextField(null=True)
    intention_type = IntegerField(null=True)
    consent = BooleanField(null=True)
    status = IntegerField()
    cohort = ForeignKeyField(Cohort, null=True, backref="participants")

    paused_days = IntegerField(default=0)
    paused_at = DateTimeField(null=True)

    date_started = DateTimeField(null=True)
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    @property
    def current_pause_days(self) -> int:
        """Days used by a pause that is still running. Capped, because a pause
        expires on its own after PAUSE_DURATION_DAYS even if never resumed."""
        if self.paused_at is None:
            return 0

        elapsed = (datetime.now().date() - self.paused_at.date()).days

        return min(elapsed, PAUSE_DURATION_DAYS)

    @property
    def total_paused_days(self) -> int:
        return self.paused_days + self.current_pause_days

    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None and self.current_pause_days < PAUSE_DURATION_DAYS

    @property
    def pause_days_left(self) -> int:
        return PAUSE_DURATION_DAYS - self.current_pause_days

    @property
    def cycle_length(self) -> int:
        return self.cohort.duration_days if self.cohort else CYCLE_LENGTH_DAYS

    @property
    def cycle_day(self) -> int:
        """Paused days don't count, so a pause pushes the finish line out."""
        if self.date_started is None:
            return 1

        elapsed = (datetime.now().date() - self.date_started.date()).days

        return elapsed - self.total_paused_days + 1

    @property
    def cycle_end_date(self):
        if self.date_started is None:
            return None

        return self.date_started.date() + timedelta(days=self.cycle_length + self.total_paused_days)

    @property
    def is_cycle_complete(self) -> bool:
        return self.date_started is not None and self.cycle_day > self.cycle_length


class UserTime(BaseModel):
    user = ForeignKeyField(User, backref="times")
    time = TimeField()


class Question(BaseModel):
    text = TextField()
    type = IntegerField()
    options = TextField(null=True)
    order = IntegerField(unique=True)
    is_final = BooleanField(default=False)

    @property
    def option_list(self):
        """Parsed answer options, or None for an open question."""
        if self.options is None:
            return None
        return json.loads(self.options)


class Answer(BaseModel):
    user = ForeignKeyField(User, backref="answers")
    question = ForeignKeyField(Question, backref="answers")
    sent_at = DateTimeField()
    answered_at = DateTimeField(null=True)
    answer = TextField(null=True)
    skipped = BooleanField(default=False)


def initialize_database():
    db.connect()
    db.create_tables([Cohort, User, UserTime, Question, Answer], safe=True)
