"""Getting in, and staying out.

One shared password, checked against the environment on every request rather
than captured at startup, so rotating it does not need a restart.
"""
import os
import secrets
from functools import wraps

from flask import redirect, render_template, request, session, url_for

from core.logs import get_logger

logger = get_logger(__name__)


def password():
    return os.getenv("ADMIN_PANEL_PASSWORD")


def safe_next(target):
    """Where to land after signing in — only ever somewhere inside the panel.

    `next` is read straight out of the URL, so without this a crafted link
    would bounce the admin off-site the moment they typed the password. A
    leading `//` is a protocol-relative URL and goes elsewhere too, so a plain
    startswith("/") is not enough on its own.
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target

    return url_for("dashboard")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))

        return view(*args, **kwargs)

    return wrapper


def register(app):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        expected = password()

        if expected is None:
            return render_template("login.html", error="ADMIN_PANEL_PASSWORD is not set.")

        if request.method == "POST":
            if secrets.compare_digest(request.form.get("password", ""), expected):
                session["authenticated"] = True
                logger.info("Admin signed in from %s", request.remote_addr)

                return redirect(safe_next(request.args.get("next")))

            # WARNING so it surfaces under «Останні попередження» on the
            # dashboard. This process has no alert handler, so it reaches the
            # log without buzzing anyone's phone.
            logger.warning("Failed admin sign-in from %s", request.remote_addr)

            return render_template("login.html", error="Wrong password.")

        return render_template("login.html", error=None)

    @app.route("/logout")
    def logout():
        session.clear()

        return redirect(url_for("login"))
