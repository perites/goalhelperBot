"""Participants: the list, one person's page, and the status actions.

Those four buttons are the only way Ксенія changes somebody's state by hand,
and two of them are one-way.
"""
from flask import abort, flash, redirect, render_template, request, url_for

from admin.auth import login_required
from core.enums import Status
from core.models import Answer, FinalAnswer, User
from core.services.cycle import finish_user, pause_user, resume_user
from core.services.slots import format_slots, saved_slots
from core.services.stats import answered_count, skipped_count, stats_for


def _last_activity(user):
    latest = (
        Answer.select()
        .where((Answer.user == user) & Answer.answered_at.is_null(False))
        .order_by(Answer.answered_at.desc())
        .first()
    )

    return latest.answered_at if latest else None


def register(app):
    @app.route("/users")
    @login_required
    def users():
        rows = []
        for user in User.select().order_by(User.created_at.desc()):
            rows.append({
                "user": user,
                "status": Status(user.status),
                "answered": answered_count(user),
                "skipped": skipped_count(user),
                "last_seen": _last_activity(user),
            })

        return render_template("users.html", rows=rows, statuses=list(Status))

    @app.route("/users/<int:telegram_id>")
    @login_required
    def user_detail(telegram_id):
        user = User.get_or_none(User.telegram_id == telegram_id)
        if user is None:
            abort(404)

        answers = (
            Answer.select()
            .where(Answer.user == user)
            .order_by(Answer.sent_at.desc())
        )
        stats = stats_for(user)

        return render_template(
            "user.html",
            user=user,
            status=Status(user.status),
            slots=format_slots(saved_slots(user)) or "—",
            answers=answers,
            final=FinalAnswer.select().where(FinalAnswer.user == user).first(),
            stats={**stats, "emotions": stats["emotions"] or "—"},
        )

    @app.route("/users/<int:telegram_id>/action", methods=["POST"])
    @login_required
    def user_action(telegram_id):
        user = User.get_or_none(User.telegram_id == telegram_id)
        if user is None:
            abort(404)

        action = request.form.get("action")

        if action == "pause":
            pause_user(user)
        elif action == "resume":
            resume_user(user)
        elif action == "finish":
            finish_user(user)
        elif action == "stop":
            user.status = Status.STOPPED
            user.save()
        else:
            abort(400)

        flash(f"{action.title()} applied.", "ok")

        return redirect(url_for("user_detail", telegram_id=telegram_id))
