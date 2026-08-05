"""Entry point for the admin panel.

    python admin_panel.py

Binds to localhost only — reach it through the SSH tunnel, same as
sqlite-web. See deploy/README-tunnel.md.
"""
import os

from dotenv import load_dotenv

load_dotenv()

from waitress import serve

from admin.app import create_app
from core.settings import ADMIN_LOG_FILE_NAME
from core.logs import configure_logging, get_logger
from core.models import initialize_database

ADMIN_HOST = "127.0.0.1"
ADMIN_PORT = int(os.getenv("ADMIN_PANEL_PORT", "8082"))

# Enough for one person clicking around, and the number of peewee connections
# this process will hold: each request opens one and closes it on teardown, and
# they are thread-local.
ADMIN_THREADS = 4

logger = get_logger("admin")


def main():
    # First, so that everything below reaches the log — including the refusal
    # to start. Its own file: sharing the bot's would mean two processes
    # rotating one path at midnight. Alerts are the bot's job; this process has
    # no event loop to send them from.
    configure_logging(file_name=ADMIN_LOG_FILE_NAME, alerts=False)

    # Creates tables if the bot hasn't run yet; harmless when it has.
    initialize_database()

    if not os.getenv("ADMIN_PANEL_PASSWORD"):
        logger.critical("ADMIN_PANEL_PASSWORD is not set; refusing to start")
        raise SystemExit(
            "ADMIN_PANEL_PASSWORD is not set — refusing to start without a password."
        )

    if not os.getenv("ADMIN_SECRET_KEY"):
        logger.critical("ADMIN_SECRET_KEY is not set; refusing to start")
        raise SystemExit(
            "ADMIN_SECRET_KEY is not set — refusing to start.\n"
            "\n"
            "Sessions are signed with it, so without one the panel invents a new\n"
            "key on every start and logs you out each time it restarts.\n"
            "\n"
            "Generate one and add it to .env:\n"
            '    python -c "import secrets; print(secrets.token_hex(32))"'
        )

    logger.info("Admin panel listening on http://%s:%s", ADMIN_HOST, ADMIN_PORT)

    # Waitress rather than `app.run()`: Flask's built-in server is a
    # development convenience and its own documentation says not to deploy it.
    # Waitress is pure Python, so there is nothing to build on the VPS and the
    # start command stays `python admin_panel.py` — no unit file changes.
    serve(create_app(), host=ADMIN_HOST, port=ADMIN_PORT, threads=ADMIN_THREADS)


if __name__ == "__main__":
    main()
