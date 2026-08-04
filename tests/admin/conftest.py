"""Fixtures for the admin panel's tests.

Two things differ from the rest of the suite, and both are about matching how
the panel actually runs rather than about convenience.

**A file-backed database, not `:memory:`.** `create_app` opens a peewee
connection per request and closes it again on teardown. SQLite discards an
in-memory database the moment its last connection closes, so under the
project-wide fixture the schema would vanish after the very first request and
every test would fail on "no such table". A temporary file behaves exactly as
production does, and exercises the real per-request open/close while it is
there.

**A temporary log directory.** `LOG_DIR` resolves relative to the working
directory, so on a developer's machine it is the project's own `logs/` — the
dashboard and the logs page would read real bot logs, and results would differ
from machine to machine. Pointing it somewhere empty keeps these hermetic.
"""
import pytest

from admin.app import create_app
from core import models as database
from core.models import (
    Answer, Cohort, FinalAnswer, FinalQuestion, Question, User, UserTime,
)

MODELS = [Cohort, User, UserTime, Question, Answer, FinalQuestion, FinalAnswer]

PASSWORD = "smoke-test-password"


@pytest.fixture(autouse=True)
def db(tmp_path):
    """Replaces the project-wide in-memory database — see the module docstring.

    Overriding by name means only this one runs for tests in this directory;
    the rest of the suite is untouched.
    """
    # No `pragmas=` on purpose: peewee only replaces them when given some, so
    # leaving it out keeps the production set from models.py — foreign keys,
    # WAL and the busy timeout. Passing a subset here would also overwrite them
    # on the shared `db` singleton for every test that ran afterwards.
    database.db.init(str(tmp_path / "admin.db"))
    database.db.connect()
    database.db.create_tables(MODELS)

    yield database.db

    database.db.close()


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """An empty log directory, patched in where `admin.app` looks it up.

    `LOG_DIR` is imported by name, so the binding to replace is the one in
    `admin.logfiles` — rebinding `core.settings.LOG_DIR` would have no effect.
    """
    directory = tmp_path / "logs"
    directory.mkdir()
    monkeypatch.setattr("admin.logfiles.LOG_DIR", str(directory))

    return directory


@pytest.fixture
def app(log_dir, monkeypatch):
    monkeypatch.setenv("ADMIN_PANEL_PASSWORD", PASSWORD)
    monkeypatch.setenv("ADMIN_SECRET_KEY", "smoke-test-secret")

    application = create_app()

    # Let exceptions surface with their own traceback instead of a bare 500, so
    # a failing smoke test names the actual cause rather than just the status.
    application.config["TESTING"] = True

    return application


@pytest.fixture
def anon(app):
    """A client that has not logged in."""
    return app.test_client()


@pytest.fixture
def client(app):
    """A logged-in client, which is what most of these tests want."""
    test_client = app.test_client()
    response = test_client.post("/login", data={"password": PASSWORD})

    assert response.status_code == 302, "the fixture itself failed to authenticate"

    return test_client
