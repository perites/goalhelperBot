"""Building the panel.

Wiring only — the pages themselves live in `admin/routes/`, the form parsing in
`admin/forms.py`, and signing in in `admin/auth.py`. Nothing here imports `bot`:
the two front ends meet in `core/` and nowhere else, which is what lets a Flask
process serve this without a Telegram library in it.
"""
import logging
import os
import secrets

from flask import Flask, render_template

from admin import csrf
from admin.routes import register_all
from core import models
from core.logs import ROOT_LOGGER_NAME, get_logger

logger = get_logger(__name__)


def _attach_logging(app):
    """Send Flask's own records to whatever `configure_logging` set up.

    `app.logger` lives outside the project's logger namespace, so without this
    it reaches no handler at all — and an unhandled exception in a route would
    leave no trace anywhere, least of all on the logs page this same process
    serves.

    The handlers are reused rather than rebuilt: a second
    TimedRotatingFileHandler on the same path would fight the first over the
    midnight rotation. If nothing is configured — under tests, or when an
    embedder has wired its own — this leaves Flask's default alone.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)
    if not root.handlers:
        return

    app.logger.handlers = root.handlers
    app.logger.setLevel(root.level)
    app.logger.propagate = False


def _register_error_pages(app):
    """A 404 or a 500 should still look like the panel, and a 500 should leave
    a line in the log — the route that raised it may not have."""

    @app.errorhandler(400)
    def bad_request(error):
        return render_template(
            "error.html",
            code=400,
            message="Форма застаріла або дані не читаються. Відкрийте сторінку заново.",
        ), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="Сторінки немає."), 404

    @app.errorhandler(500)
    def server_error(error):
        logger.error("Unhandled error in the admin panel", exc_info=error)

        return render_template(
            "error.html", code=500, message="Щось пішло не так. Подробиці в логах.",
        ), 500


def create_app():
    app = Flask(__name__)

    _attach_logging(app)

    secret = os.getenv("ADMIN_SECRET_KEY")
    if not secret:
        # Sessions are signed with this, so a fresh random key on every start
        # means every restart logs the admin out. admin_panel.py refuses to
        # start without one for that reason; it is tolerated here so tests and
        # one-off scripts can build an app without the ceremony.
        logger.warning(
            "ADMIN_SECRET_KEY is not set; sessions will not survive a restart"
        )
        secret = secrets.token_hex(32)

    app.secret_key = secret

    # peewee connections aren't shared safely between threads, and Flask
    # serves requests on several — so each request gets its own.
    @app.before_request
    def _open_db():
        if models.db.is_closed():
            models.db.connect()

    @app.teardown_request
    def _close_db(_exception):
        if not models.db.is_closed():
            models.db.close()

    _register_error_pages(app)
    csrf.protect(app)
    register_all(app)

    return app
