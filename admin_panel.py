"""Entry point for the admin panel.

    python admin_panel.py

Binds to localhost only — reach it through the SSH tunnel, same as
sqlite-web. See deploy/README-tunnel.md.
"""
import os

from dotenv import load_dotenv

load_dotenv()

from admin.app import create_app
from bot.config import ADMIN_LOG_FILE_NAME
from bot.logs import configure_logging, get_logger
from bot.models import initialize_database

ADMIN_HOST = "127.0.0.1"
ADMIN_PORT = int(os.getenv("ADMIN_PANEL_PORT", "8082"))

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

    create_app().run(host=ADMIN_HOST, port=ADMIN_PORT)


if __name__ == "__main__":
    main()
