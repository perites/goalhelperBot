from enum import IntEnum

from peewee import SqliteDatabase, Model, IntegerField, CharField, SQL, DateTimeField, ForeignKeyField, TimeField

db = SqliteDatabase("users.db")


class Status(IntEnum):
    JUSTSTARTED = 0


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    telegram_id = IntegerField(primary_key=True)
    username = CharField()
    name = CharField(null=True)
    intention = CharField(null=True)
    intention_type = IntegerField(null=True)
    status = IntegerField()

    date_started = DateTimeField(null=True)
    created_at = DateTimeField(constraints=[SQL("DEFAULT CURRENT_TIMESTAMP")])


class UserTime(BaseModel):
    user = ForeignKeyField(User, backref="times")
    time = TimeField()


def initialize_database():
    db.connect()
    db.create_tables([User, UserTime], safe=True)
