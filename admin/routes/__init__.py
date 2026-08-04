"""The panel's pages, one module per thing you can look at.

Each exposes `register(app)` and adds its own routes. Endpoint names are flat
rather than blueprint-scoped — `url_for("questions")`, not
`url_for("questions.index")` — because with two dozen routes and one template
directory the prefixes would buy nothing but a rename of every link.
"""
from admin import auth
from admin.routes import cohorts, dashboard, exports, logs, questions, users

MODULES = (auth, dashboard, questions, cohorts, users, logs, exports)


def register_all(app):
    for module in MODULES:
        module.register(app)
