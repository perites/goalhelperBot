import json
from datetime import timedelta

from peewee import (
    SqliteDatabase, Model, IntegerField, CharField, TextField,
    BooleanField, SQL, DateField, DateTimeField, ForeignKeyField, TimeField,
)

from app import clock
from app.enums import CohortStatus, QuestionType
from app.config import (
    DATABASE_NAME,
    CYCLE_LENGTH_DAYS,
    DEFAULT_CATEGORY_ORDER,
    DEFAULT_CATEGORY_ORDER_CSV,
    DEFAULT_MAX_PEOPLE,
    DEFAULT_QUESTIONS_PER_DAY,
    PAUSE_DURATION_DAYS,
)

db = SqliteDatabase(DATABASE_NAME)


class BaseModel(Model):
    class Meta:
        database = db


class Cohort(BaseModel):
    """One pilot run. Holds the enrollment window and capacity — note it has no
    start/end for the 30 days themselves, because each participant's cycle runs
    from their own onboarding completion (ТЗ: "День 1 рахується від дати
    завершення онбордингу")."""
    name = CharField(default="Пілот")

    # Exactly one cohort is active; it's the one /start enrols into. Others
    # are kept for their history and their participants' settings, which are
    # read per-user through User.cohort rather than from here.
    is_active = BooleanField(default=False)

    enrollment_opens = DateField()
    enrollment_closes = DateField()
    duration_days = IntegerField(default=CYCLE_LENGTH_DAYS)
    max_people = IntegerField(default=DEFAULT_MAX_PEOPLE)
    status = IntegerField(default=CohortStatus.PLANNED)

    # How many questions a participant gets per day, spread across the slots
    # they picked. See config.DEFAULT_QUESTIONS_PER_DAY for the caveats.
    questions_per_day = IntegerField(default=DEFAULT_QUESTIONS_PER_DAY)

    # The rhythm of the daily questions, as QuestionType values joined by
    # commas — "0,1,3". Integers rather than names so an admin panel can render
    # them as a picker without parsing prose.
    category_order = CharField(default=DEFAULT_CATEGORY_ORDER_CSV)

    @property
    def categories(self):
        """The category order as QuestionType values. Unknown or malformed
        entries are dropped rather than raising, so a bad edit degrades to a
        shorter cycle instead of stopping every send."""
        known = {member.value for member in QuestionType}
        parsed = []

        for part in (self.category_order or "").split(","):
            part = part.strip()
            if part.isdigit() and int(part) in known:
                parsed.append(QuestionType(int(part)))

        return parsed or list(DEFAULT_CATEGORY_ORDER)


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

        elapsed = (clock.now_kyiv().date() - self.paused_at.date()).days

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

        elapsed = (clock.now_kyiv().date() - self.date_started.date()).days

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
    """Daily questions and their follow-ups. The closing questions live in
    FinalQuestion, which is a different shape entirely.

    A row with a `parent` is a follow-up: it is reached only by answering that
    parent, never by the daily rotation. `parent IS NULL` is therefore the
    filter that defines the rotation, and it maintains itself — point a
    question at a parent and it leaves the rotation automatically.
    """
    text = TextField()
    type = IntegerField()
    options = TextField(null=True)
    order = IntegerField(unique=True)
    parent = ForeignKeyField("self", null=True, backref="follow_ups")

    # Offer a "write your own" button alongside the listed options. Only
    # meaningful when there are options — a question without any already
    # accepts typed answers and nothing else.
    allows_free_text = BooleanField(default=False)

    # Taken out of rotation without being deleted. A question that has been
    # answered can't be removed — the answers reference it — so retiring is
    # how an admin withdraws one while keeping participants' replies intact.
    retired = BooleanField(default=False)

    @property
    def option_list(self):
        """Parsed answer options, or None for an open question."""
        if self.options is None:
            return None
        return json.loads(self.options)

    @property
    def type_name(self):
        return QuestionType(self.type).name

    @property
    def option_count(self):
        """How many choices this offers, counting inside groups."""
        options = self.option_list
        if not options:
            return 0

        return sum(len(entry) - 1 if isinstance(entry, list) else 1 for entry in options)


class Answer(BaseModel):
    user = ForeignKeyField(User, backref="answers")
    question = ForeignKeyField(Question, backref="answers")
    sent_at = DateTimeField()
    answered_at = DateTimeField(null=True)
    answer = TextField(null=True)
    skipped = BooleanField(default=False)

    # Needed to edit the question message once it's answered: a typed reply
    # arrives as a separate message with no reference back to the question.
    message_id = IntegerField(null=True)

    # The cycle day this was asked on. Stored rather than recomputed, so a
    # reply that lands the next day doesn't redraw with the wrong number.
    cycle_day = IntegerField(null=True)

    # Which slot's run this belongs to, or NULL for sends outside the schedule
    # (the onboarding question, /ask). It can't be inferred from sent_at:
    # answering the 09:00 question at 12:30 sends the next one at 12:30, still
    # as part of the morning run.
    slot = CharField(null=True)

    # The answer this one follows up on. Set once, at creation. Nothing in
    # delivery depends on it — what comes next is decided by Question.parent —
    # but it keeps a reply and its follow-up together in the export, and it's
    # what the quota and statistics exclude on.
    parent = ForeignKeyField("self", null=True, backref="follow_ups")

    # Which position in the cohort's category order this send came from. Recorded
    # rather than derived from the question's type, because a category may
    # appear at several positions and the type alone wouldn't say which.
    category_index = IntegerField(null=True)

    @classmethod
    def open_for(cls, user):
        """Questions sent to this user that are still awaiting a reply."""
        return cls.select().where(
            (cls.user == user)
            & cls.answered_at.is_null(True)
            & (cls.skipped == False)  # noqa: E712 - peewee needs the comparison
        )


class FinalQuestion(BaseModel):
    """ТЗ §15's closing questions. Sent as one block and answered in one
    message, so there's no per-question answer row."""
    text = TextField()
    order = IntegerField(unique=True)


class FinalAnswer(BaseModel):
    """One row per user: their single reply to the whole closing block."""
    user = ForeignKeyField(User, backref="final_answers")
    sent_at = DateTimeField()
    answered_at = DateTimeField(null=True)
    answer = TextField(null=True)

    message_id = IntegerField(null=True)
    message_text = TextField(null=True)


def initialize_database():
    db.connect()
    db.create_tables(
        [Cohort, User, UserTime, Question, Answer, FinalQuestion, FinalAnswer],
        safe=True,
    )
