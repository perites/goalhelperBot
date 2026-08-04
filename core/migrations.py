"""Schema changes, applied in order and exactly once.

`create_tables(safe=True)` creates tables that are missing and nothing else. It
will never add a column to a table that already exists, so once there are real
answers in the database — which is to say, from the first day of the pilot
onwards — it cannot carry out any change at all. Every edit to models.py after
that point needs a step here as well.

How far a database has got is recorded in SQLite's own `user_version` header
field. No extra table to keep in sync, nothing that can disagree with itself,
and it is readable straight from sqlite-web:

    PRAGMA user_version;

Adding one
----------
Append to MIGRATIONS. **Never** reorder or edit an entry that has shipped: a
database that already applied it will not apply it again, so a changed entry
means two databases claiming the same version with different schemas.

    from peewee import BooleanField
    from playhouse.migrate import SqliteMigrator, migrate as run

    def _add_reminder_sent(database):
        migrator = SqliteMigrator(database)
        run(migrator.add_column(
            "answer", "reminder_sent", BooleanField(default=False),
        ))

    MIGRATIONS = [
        ("add answer.reminder_sent", _add_reminder_sent),
    ]

A step takes the database and nothing else. Deliberately: it must describe the
change to the *stored* schema, which is a different thing from whatever
models.py happens to say today. Writing steps against the model classes is how
migrations start failing a year later, when a column they mention has been
renamed out from under them.

Nothing here imports models.py, so models.py can import this.
"""
from core.logs import get_logger

logger = get_logger(__name__)

# (description, step) pairs. The version of a database is how many of these it
# has applied, so position in this list is identity — see the warning above.
MIGRATIONS = []


class SchemaTooNew(RuntimeError):
    """The database has been through migrations this code has never heard of.

    Almost always a rollback: a newer version of the bot ran, changed the
    schema, and an older one was then started against it. Continuing would mean
    reading a shape we do not understand and writing over data we cannot see.
    """

    def __init__(self, found, known):
        super().__init__(
            f"Database schema is at version {found}, but this code only knows "
            f"{known}. It was written by a newer version of the bot — deploy "
            f"that one, or restore a backup from before it ran."
        )


def latest_version():
    return len(MIGRATIONS)


def schema_version(database):
    return database.pragma("user_version")


def stamp(database, version):
    """Record how far a database has got, without running anything.

    For databases built from scratch: `create_tables` already gave them today's
    shape, so replaying the history that led there would fail on the first step
    that added a column they were born with.
    """
    database.pragma("user_version", version)
    logger.info("New database stamped at schema version %s", version)


def apply_migrations(database):
    """Bring an existing database up to date. Returns how many steps ran."""
    current = schema_version(database)

    if current > latest_version():
        raise SchemaTooNew(current, latest_version())

    if current == latest_version():
        logger.debug("Database schema is up to date (version %s)", current)
        return 0

    # One IMMEDIATE transaction for the lot, with the version read again inside
    # it: the bot and the admin panel can start at the same moment, and this is
    # what stops both deciding to apply the same step. It also means a step
    # that raises leaves the database exactly where it was.
    with database.atomic("IMMEDIATE"):
        current = schema_version(database)
        applied = 0

        for offset, (description, step) in enumerate(MIGRATIONS[current:], start=1):
            version = current + offset
            logger.info("Applying schema migration %s: %s", version, description)

            step(database)
            database.pragma("user_version", version)
            applied += 1

    if applied:
        logger.info("Database schema now at version %s", latest_version())

    return applied
