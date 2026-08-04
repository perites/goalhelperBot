"""Schema migrations, and the pragmas the database is opened with.

`create_tables(safe=True)` cannot alter a table that already exists, so from
the first day of the pilot it can no longer carry out any change at all. These
cover the mechanism that takes over from it.
"""
import pytest
from peewee import BooleanField
from playhouse.migrate import SqliteMigrator, migrate as run

from core import migrations
from core import models as database
from core.migrations import (
    SchemaTooNew, apply_migrations, latest_version, schema_version,
)
from core.models import initialize_database


@pytest.fixture(autouse=True)
def db(tmp_path):
    """A real file rather than `:memory:`.

    `user_version` lives in the database header, so a test about how far a
    database has got needs one that has a header to keep. WAL needs a file too.
    This overrides the project-wide fixture for this module only.
    """
    database.db.init(str(tmp_path / "migrate.db"))
    database.db.connect()

    yield database.db

    database.db.close()


def _never_runs(database):
    raise AssertionError("a migration ran against a database that never needed it")


# --- how the database is opened --------------------------------------------

def test_foreign_keys_are_enforced(db):
    """The backstop under services/deletion.py, including against writes that
    never go through this code — sqlite-web, say."""
    assert db.pragma("foreign_keys") == 1


def test_the_database_uses_write_ahead_logging(db):
    """Three processes share this file. Without WAL a writer locks all of it
    and readers queue behind, which shows up as "database is locked" under no
    particular load."""
    assert db.pragma("journal_mode") == "wal"


def test_a_locked_database_is_waited_for(db):
    assert db.pragma("busy_timeout") == 5000


# --- setting up ------------------------------------------------------------

def test_initialize_creates_the_schema(db):
    initialize_database()

    assert set(db.get_tables()) >= {"user", "cohort", "question", "answer"}


def test_initialize_can_be_called_twice(db):
    """Both entry points call it and either may run first."""
    initialize_database()
    initialize_database()  # must not raise "Connection already opened"


def test_a_new_database_is_stamped_at_the_latest_version(db, monkeypatch):
    """It was built from today's models, so it is already at today's shape.
    Replaying the history that led there would fail on the first step adding a
    column it was born with."""
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [("one", _never_runs), ("two", _never_runs)],
    )

    initialize_database()

    assert schema_version(db) == 2


# --- catching an existing database up --------------------------------------

def test_pending_steps_run_in_order(db, monkeypatch):
    initialize_database()  # now it exists, stamped at 0
    applied = []

    monkeypatch.setattr(migrations, "MIGRATIONS", [
        ("first", lambda _: applied.append("first")),
        ("second", lambda _: applied.append("second")),
    ])

    assert apply_migrations(db) == 2
    assert applied == ["first", "second"]
    assert schema_version(db) == 2


def test_a_step_runs_only_once(db, monkeypatch):
    initialize_database()
    applied = []
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [("only", lambda _: applied.append(1))],
    )

    apply_migrations(db)
    apply_migrations(db)
    initialize_database()

    assert applied == [1]


def test_an_up_to_date_database_is_left_alone(db):
    initialize_database()

    assert apply_migrations(db) == 0


def test_a_step_can_actually_change_the_schema(db, monkeypatch):
    """The recipe the module docstring gives, run for real — otherwise the
    documentation is the only thing that says it works."""

    def add_column(target):
        run(SqliteMigrator(target).add_column(
            "user", "reminder_sent", BooleanField(default=False),
        ))

    initialize_database()
    monkeypatch.setattr(
        migrations, "MIGRATIONS", [("add user.reminder_sent", add_column)],
    )

    apply_migrations(db)

    assert "reminder_sent" in {column.name for column in db.get_columns("user")}
    assert schema_version(db) == 1


def test_a_failed_step_leaves_the_database_where_it_was(db, monkeypatch):
    """All of it in one transaction, so a half-applied deploy is not a state
    the database can be in."""
    applied = []

    def explodes(_):
        raise RuntimeError("ALTER TABLE went wrong")

    initialize_database()
    monkeypatch.setattr(migrations, "MIGRATIONS", [
        ("fine", lambda _: applied.append("fine")),
        ("broken", explodes),
    ])

    with pytest.raises(RuntimeError):
        apply_migrations(db)

    assert schema_version(db) == 0


def test_a_database_from_the_future_is_refused(db, monkeypatch):
    """A rollback: a newer bot changed the schema and an older one was started
    against it. Reading a shape we don't understand is how data gets lost."""
    initialize_database()
    db.pragma("user_version", 7)
    monkeypatch.setattr(migrations, "MIGRATIONS", [("one", _never_runs)])

    with pytest.raises(SchemaTooNew):
        apply_migrations(db)


def test_the_refusal_says_what_to_do(db, monkeypatch):
    initialize_database()
    db.pragma("user_version", 7)
    monkeypatch.setattr(migrations, "MIGRATIONS", [("one", _never_runs)])

    with pytest.raises(SchemaTooNew) as raised:
        apply_migrations(db)

    message = str(raised.value)
    assert "7" in message and "newer version" in message


def test_there_are_no_migrations_yet(db):
    """A canary. Every test above monkeypatches MIGRATIONS, so if a real one is
    ever added they all keep passing while `latest_version` quietly moves — and
    the fresh-database stamp is the thing that would go wrong first."""
    assert latest_version() == 0
