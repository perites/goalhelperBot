"""Cross-site request forgery protection.

Every page here is behind a password and an SSH tunnel, which sounds like
enough until you remember where the browser is. Anything else open in it can
post to http://127.0.0.1:8082 while the tunnel is up, and the session cookie
goes along for the ride — enough to activate a cohort, retire a question, or
end somebody's participation, with no sign of it except a flash message the
admin never sees.

Browsers' `SameSite=Lax` default already blocks most of that. But it is a
default nobody here chose, it does not cover every request shape, and it is one
browser setting away from not being true. A token in the form is a control we
own.

No dependency for it: one token per session, compared in constant time, checked
on every method that can change something.
"""
import secrets

from flask import abort, request, session

FIELD = "csrf_token"

# Everything that is not a read.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def token():
    """This session's token, minted the first time anything asks for it."""
    if FIELD not in session:
        session[FIELD] = secrets.token_urlsafe(32)

    return session[FIELD]


def protect(app):
    """Require a matching token on every unsafe request, and let templates
    render one."""

    @app.before_request
    def _require_token():
        # Asked for on every request, not just the ones being checked, so a
        # form rendered on a page that was opened before the session existed
        # still has something to post back.
        expected = token()

        if request.method not in UNSAFE_METHODS:
            return

        if not secrets.compare_digest(request.form.get(FIELD, ""), expected):
            abort(400)

    app.jinja_env.globals[FIELD] = token
