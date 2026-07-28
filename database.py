import json
from datetime import datetime
from enum import IntEnum

from peewee import (
    SqliteDatabase, Model, IntegerField, CharField, TextField,
    BooleanField, SQL, DateTimeField, ForeignKeyField, TimeField,
)

db = SqliteDatabase("goalbot.db")

CYCLE_LENGTH_DAYS = 30


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


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    telegram_id = IntegerField(primary_key=True)
    username = CharField()
    name = CharField(null=True)
    intention = TextField(null=True)
    intention_type = IntegerField(null=True)
    consent = BooleanField(null=True)
    status = IntegerField()

    date_started = DateTimeField(null=True)
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])

    @property
    def cycle_day(self) -> int:
        if self.date_started is None:
            return 1

        return (datetime.now().date() - self.date_started.date()).days + 1


class UserTime(BaseModel):
    user = ForeignKeyField(User, backref="times")
    time = TimeField()


class Question(BaseModel):
    text = TextField()
    type = IntegerField()
    options = TextField(null=True)
    order = IntegerField(unique=True)

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
    db.create_tables([User, UserTime, Question, Answer], safe=True)
