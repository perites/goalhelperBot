"""The overview page: where the pilot is up to, at a glance."""
from collections import Counter

from flask import render_template

from admin.auth import login_required
from admin.logfiles import recent_problems
from core import clock
from core.enums import Status
from core.models import Answer, Question, User
from core.services.cohort import current_cohort, enrollment_state, seats_left, seats_taken


def register(app):
    @app.route("/")
    @login_required
    def dashboard():
        cohort = current_cohort()
        by_status = Counter(user.status for user in User.select())
        today = clock.now_kyiv().replace(hour=0, minute=0, second=0, microsecond=0)

        sent_today = Answer.select().where(Answer.sent_at >= today).count()
        answered_today = (
            Answer.select()
            .where((Answer.answered_at >= today) & Answer.answer.is_null(False))
            .count()
        )

        return render_template(
            "dashboard.html",
            cohort=cohort,
            enrollment=enrollment_state(cohort).name if cohort else "NO_COHORT",
            seats_taken=seats_taken(cohort) if cohort else 0,
            seats_left=seats_left(cohort) if cohort else 0,
            statuses=[(status, by_status.get(status.value, 0)) for status in Status],
            sent_today=sent_today,
            answered_today=answered_today,
            questions=Question.select().where(Question.parent.is_null(True)).count(),
            retired=Question.select().where(Question.retired == True).count(),  # noqa: E712
            recent_problems=recent_problems(60)[:8],
        )
