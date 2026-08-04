"""Shared fixtures.

Every test runs against a fresh in-memory database and a frozen clock, so
nothing touches goalbot.db and no assertion depends on the wall clock.

The data comes from `tests/factories.py` rather than from `samples/`: the demo
content exists to be thrown away and replaced with Ксенія's real bank, which it
cannot be while the test suite is asserting on it.
"""
from datetime import datetime, timedelta, time as dt_time
from types import SimpleNamespace

import pytest

from core import clock
from core import models as database
from core.enums import Status
from core.models import Cohort, User, UserTime, Question, Answer, FinalQuestion, FinalAnswer
from tests import factories

MODELS = [Cohort, User, UserTime, Question, Answer, FinalQuestion, FinalAnswer]

# Arbitrary fixed "now" — a Wednesday at 09:30, well away from midnight and
# DST boundaries so date arithmetic in tests is unambiguous.
FROZEN_NOW = datetime(2026, 3, 11, 9, 30)


@pytest.fixture(autouse=True)
def db():
    """Fresh in-memory database per test."""
    database.db.init(":memory:")
    database.db.connect()
    database.db.create_tables(MODELS)

    yield database.db

    # The whole database is going, so the constraints that guard real data
    # would only argue about the drop order — a question still holds its
    # follow-ups, an answer its own.
    database.db.pragma("foreign_keys", 0)
    database.db.drop_tables(MODELS)
    database.db.close()


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Freeze time at FROZEN_NOW, returning a setter to move it.

    Patching `clock` alone is enough because every module calls
    `clock.now_kyiv()` rather than importing the function by name.
    """
    current = {"now": FROZEN_NOW}

    monkeypatch.setattr(clock, "now_kyiv", lambda: current["now"])
    monkeypatch.setattr(clock, "today_kyiv", lambda: current["now"].date())

    def travel(**kwargs):
        """travel(days=3) / travel(hours=2) — move the frozen clock forward."""
        current["now"] = current["now"] + timedelta(**kwargs)
        return current["now"]

    travel.now = lambda: current["now"]
    travel.set = lambda dt: current.__setitem__("now", dt) or dt

    return travel


class FakeBot:
    """Records outgoing messages and edits instead of calling Telegram."""

    def __init__(self):
        self.sent = []
        self.edits = []
        self._last_message_id = 1000

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self._last_message_id += 1
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "markup": reply_markup,
            "message_id": self._last_message_id,
        })

        return SimpleNamespace(message_id=self._last_message_id, chat_id=chat_id, text=text)

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, **kwargs):
        self.edits.append({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "markup": reply_markup,
        })

    @property
    def texts(self):
        return [message["text"] for message in self.sent]

    def edit_for(self, message_id):
        """The latest edit applied to a given message, if any."""
        matching = [edit for edit in self.edits if edit["message_id"] == message_id]

        return matching[-1] if matching else None


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def cohort():
    return factories.build_cohort()


@pytest.fixture
def questions():
    """The daily bank. Rotation questions only — follow-ups are reached through
    their parent, and are on `question.follow_ups` when a test wants them."""
    return factories.build_question_bank()


@pytest.fixture
def make_user(cohort):
    """Create a participant. `started_days_ago` sets their cycle position."""

    def _make(telegram_id=1, status=Status.ACTIVE, started_days_ago=0, slots=(), **kwargs):
        user = User.create(
            telegram_id=telegram_id,
            username=f"user{telegram_id}",
            name=f"Name{telegram_id}",
            intention="Я хочу побудувати звичку",
            intention_type=3,
            consent=True,
            status=status,
            cohort=kwargs.pop("cohort", cohort),
            date_started=kwargs.pop(
                "date_started", clock.now_kyiv() - timedelta(days=started_days_ago)
            ),
            **kwargs,
        )

        for hour in slots:
            UserTime.create(user=user, time=dt_time(hour, 0))

        return user

    return _make
