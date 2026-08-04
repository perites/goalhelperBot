"""Entry point for the admin panel.

    python admin_panel.py

Binds to localhost only — reach it through the SSH tunnel, same as
sqlite-web. See deploy/README-tunnel.md.
"""
import os

from dotenv import load_dotenv

load_dotenv()

from admin.app import create_app
from bot.models import initialize_database

ADMIN_HOST = "127.0.0.1"
ADMIN_PORT = int(os.getenv("ADMIN_PANEL_PORT", "8082"))


def main():
    # Creates tables if the bot hasn't run yet; harmless when it has.
    initialize_database()

    if not os.getenv("ADMIN_PANEL_PASSWORD"):
        raise SystemExit(
            "ADMIN_PANEL_PASSWORD is not set — refusing to start without a password."
        )

    create_app().run(host=ADMIN_HOST, port=ADMIN_PORT)


if __name__ == "__main__":
    main()
