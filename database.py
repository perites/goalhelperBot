from enum import IntEnum

from peewee import (
    SqliteDatabase, Model, IntegerField, CharField, TextField,
    BooleanField, SQL, DateTimeField, ForeignKeyField, TimeField,
)

db = SqliteDatabase("goalbot.db")


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


class UserTime(BaseModel):
    user = ForeignKeyField(User, backref="times")
    time = TimeField()


def initialize_database():
    db.connect()
    db.create_tables([User, UserTime], safe=True)
