"""Routes for the admin panel."""
import csv
import io
import json
import os
import secrets
from collections import Counter
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, redirect, render_template, request, Response, session, url_for,
)

from app import clock, models
from app.config import (
    CYCLE_LENGTH_DAYS,
    DEFAULT_CATEGORY_ORDER,
    LOG_DIR,
    LOG_FILE_NAME,
)
from app.enums import CohortStatus, EnrollmentState, QuestionType, Status
from app.models import (
    Answer, Cohort, FinalAnswer, FinalQuestion, Question, User, UserTime,
)
from app.services.cohort import (
    activate_cohort, current_cohort, enrollment_state, seats_left, seats_taken,
)
from app.services.cycle import finish_user, pause_user, resume_user
from app.services.slots import format_slots, saved_slots
from app.services.stats import answered_count, skipped_count, top_emotions

LOG_TAIL_LINES = 400


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("ADMIN_SECRET_KEY") or secrets.token_hex(32)

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

    register_routes(app)

    return app


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def _password():
    return os.getenv("ADMIN_PANEL_PASSWORD")


def _parse_options(raw):
    """The options field is JSON. Blank means an open question."""
    raw = (raw or "").strip()
    if not raw:
        return None

    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("options must be a JSON list")

    return json.dumps(parsed, ensure_ascii=False)


def _next_order():
    highest = Question.select(Question.order).order_by(Question.order.desc()).first()

    return (highest.order + 10) if highest else 10


def register_routes(app):

    # --- auth --------------------------------------------------------------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        expected = _password()

        if expected is None:
            return render_template("login.html", error="ADMIN_PANEL_PASSWORD is not set.")

        if request.method == "POST":
            if secrets.compare_digest(request.form.get("password", ""), expected):
                session["authenticated"] = True
                return redirect(request.args.get("next") or url_for("dashboard"))

            return render_template("login.html", error="Wrong password.")

        return render_template("login.html", error=None)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # --- dashboard ---------------------------------------------------------

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
            recent_problems=_log_lines(60, level="WARNING")[:8],
        )

    # --- questions ---------------------------------------------------------

    @app.route("/questions")
    @login_required
    def questions():
        roots = (
            Question.select()
            .where(Question.parent.is_null(True))
            .order_by(Question.order)
        )
        answered = Counter(
            row.question_id for row in Answer.select(Answer.question)
        )

        return render_template(
            "questions.html",
            questions=roots,
            answered=answered,
            types=list(QuestionType),
        )

    @app.route("/questions/new", methods=["GET", "POST"])
    @app.route("/questions/<int:question_id>", methods=["GET", "POST"])
    @login_required
    def question_form(question_id=None):
        question = Question.get_or_none(Question.id == question_id) if question_id else None
        if question_id and question is None:
            abort(404)

        if request.method == "POST":
            try:
                options = _parse_options(request.form.get("options"))
            except (ValueError, json.JSONDecodeError) as error:
                flash(f"Options aren't valid JSON: {error}", "error")
                return render_template(
                    "question_form.html", question=question, types=list(QuestionType),
                    parents=_possible_parents(question),
                )

            parent_id = request.form.get("parent") or None
            fields = {
                "text": request.form["text"].strip(),
                "type": int(request.form["type"]),
                "options": options,
                "allows_free_text": bool(request.form.get("allows_free_text")),
                "retired": bool(request.form.get("retired")),
                "parent": int(parent_id) if parent_id else None,
            }

            if question is None:
                question = Question.create(order=_next_order(), **fields)
                flash("Question created.", "ok")
            else:
                for key, value in fields.items():
                    setattr(question, key, value)
                question.save()
                flash("Question saved.", "ok")

            return redirect(url_for("questions"))

        return render_template(
            "question_form.html", question=question, types=list(QuestionType),
            parents=_possible_parents(question),
        )

    @app.route("/questions/<int:question_id>/delete", methods=["POST"])
    @login_required
    def question_delete(question_id):
        question = Question.get_or_none(Question.id == question_id)
        if question is None:
            abort(404)

        # Answers point at questions, so removing one that's been asked would
        # orphan them. Retiring keeps the history and stops it being sent.
        if Answer.select().where(Answer.question == question).exists():
            flash("Already answered by someone — retire it instead of deleting.", "error")
            return redirect(url_for("questions"))

        Question.delete().where(Question.parent == question).execute()
        question.delete_instance()
        flash("Question deleted.", "ok")

        return redirect(url_for("questions"))

    # --- closing questions -------------------------------------------------

    @app.route("/final-questions", methods=["GET", "POST"])
    @login_required
    def final_questions():
        if request.method == "POST":
            text = request.form.get("text", "").strip()
            if text:
                highest = (
                    FinalQuestion.select(FinalQuestion.order)
                    .order_by(FinalQuestion.order.desc())
                    .first()
                )
                FinalQuestion.create(text=text, order=(highest.order + 10) if highest else 10)
                flash("Closing question added.", "ok")

            return redirect(url_for("final_questions"))

        return render_template(
            "final_questions.html",
            questions=FinalQuestion.select().order_by(FinalQuestion.order),
        )

    @app.route("/final-questions/<int:question_id>/delete", methods=["POST"])
    @login_required
    def final_question_delete(question_id):
        question = FinalQuestion.get_or_none(FinalQuestion.id == question_id)
        if question is not None:
            question.delete_instance()
            flash("Closing question removed.", "ok")

        return redirect(url_for("final_questions"))

    # --- cohort ------------------------------------------------------------

    @app.route("/cohorts")
    @login_required
    def cohorts():
        rows = []
        for cohort in Cohort.select().order_by(Cohort.is_active.desc(), Cohort.enrollment_opens.desc()):
            rows.append({
                "cohort": cohort,
                "status": CohortStatus(cohort.status),
                "participants": seats_taken(cohort),
                "running": User.select().where(
                    (User.cohort == cohort) & (User.status == Status.ACTIVE)
                ).count(),
            })

        return render_template("cohorts.html", rows=rows)

    @app.route("/cohorts/new", methods=["GET", "POST"])
    @app.route("/cohorts/<int:cohort_id>", methods=["GET", "POST"])
    @login_required
    def cohort_form(cohort_id=None):
        cohort = Cohort.get_or_none(Cohort.id == cohort_id) if cohort_id else None
        if cohort_id and cohort is None:
            abort(404)

        if request.method == "POST":
            fields = {
                "name": request.form["name"].strip() or "Без назви",
                "enrollment_opens": request.form["enrollment_opens"],
                "enrollment_closes": request.form["enrollment_closes"],
                "max_people": int(request.form["max_people"]),
                "duration_days": int(request.form["duration_days"]),
                "questions_per_day": int(request.form["questions_per_day"]),
                "status": int(request.form["status"]),
                # The builder posts one hidden field holding the whole order,
                # since the same category may appear several times.
                "category_order": request.form.get("category_order", "").strip(),
            }

            if cohort is None:
                first_one = not Cohort.select().exists()
                cohort = Cohort.create(is_active=first_one, **fields)
                flash("Когорту створено.", "ok")
            else:
                for key, value in fields.items():
                    setattr(cohort, key, value)
                cohort.save()
                flash("Збережено.", "ok")

            return redirect(url_for("cohort_form", cohort_id=cohort.id))

        return render_template(
            "cohort.html",
            cohort=cohort,
            types=list(QuestionType),
            order=[int(t) for t in cohort.categories] if cohort else
                  [int(t) for t in DEFAULT_CATEGORY_ORDER],
            statuses=list(CohortStatus),
            default_days=CYCLE_LENGTH_DAYS,
        )

    @app.route("/cohorts/<int:cohort_id>/activate", methods=["POST"])
    @login_required
    def cohort_activate(cohort_id):
        cohort = Cohort.get_or_none(Cohort.id == cohort_id)
        if cohort is None:
            abort(404)

        activate_cohort(cohort)
        flash(f"«{cohort.name}» тепер активна.", "ok")

        return redirect(url_for("cohorts"))

    @app.route("/cohorts/<int:cohort_id>/delete", methods=["POST"])
    @login_required
    def cohort_delete(cohort_id):
        cohort = Cohort.get_or_none(Cohort.id == cohort_id)
        if cohort is None:
            abort(404)

        # Participants read their duration, daily total and category order
        # from their cohort, so deleting one with people in it would change
        # the programme under them.
        if User.select().where(User.cohort == cohort).exists():
            flash("У когорті є учасники — її не можна видалити.", "error")
            return redirect(url_for("cohorts"))

        cohort.delete_instance()
        flash("Когорту видалено.", "ok")

        return redirect(url_for("cohorts"))

    # --- users -------------------------------------------------------------

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

        return render_template(
            "user.html",
            user=user,
            status=Status(user.status),
            slots=format_slots(saved_slots(user)) or "—",
            answers=answers,
            final=FinalAnswer.select().where(FinalAnswer.user == user).first(),
            stats={
                "answered": answered_count(user),
                "skipped": skipped_count(user),
                "emotions": top_emotions(user) or "—",
                "steps": answered_count(user, QuestionType.STEP),
                "wins": answered_count(user, QuestionType.WIN),
                "gratitude": answered_count(user, QuestionType.GRATITUDE),
            },
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

    # --- logs --------------------------------------------------------------

    @app.route("/logs")
    @login_required
    def logs():
        level = request.args.get("level") or ""

        return render_template(
            "logs.html",
            lines=_log_lines(LOG_TAIL_LINES, level=level or None),
            level=level,
            path=Path(LOG_DIR) / LOG_FILE_NAME,
        )

    # --- exports -----------------------------------------------------------

    @app.route("/export/users.csv")
    @login_required
    def export_users():
        rows = [(
            "telegram_id", "username", "name", "status", "intention",
            "category", "slots", "started", "cycle_day", "answered", "skipped",
        )]

        for user in User.select():
            rows.append((
                user.telegram_id, user.username, user.name, Status(user.status).name,
                user.intention, user.intention_type,
                format_slots(saved_slots(user)), user.date_started,
                user.cycle_day, answered_count(user), skipped_count(user),
            ))

        return _csv_response(rows, "users.csv")

    @app.route("/export/answers.csv")
    @login_required
    def export_answers():
        rows = [(
            "telegram_id", "name", "cycle_day", "slot", "question",
            "is_follow_up", "answer", "skipped", "sent_at", "answered_at",
        )]

        for answer in Answer.select().order_by(Answer.user, Answer.sent_at):
            rows.append((
                answer.user.telegram_id, answer.user.name, answer.cycle_day,
                answer.slot, answer.question.text,
                "yes" if answer.parent_id else "no",
                answer.answer, "yes" if answer.skipped else "no",
                answer.sent_at, answer.answered_at,
            ))

        for final in FinalAnswer.select():
            rows.append((
                final.user.telegram_id, final.user.name, "", "", "closing block",
                "no", final.answer, "no", final.sent_at, final.answered_at,
            ))

        return _csv_response(rows, "answers.csv")


def _possible_parents(question):
    """A follow-up hangs off a rotation question. A question can't be its own
    parent, and follow-ups of follow-ups aren't supported."""
    candidates = Question.select().where(Question.parent.is_null(True)).order_by(Question.order)

    return [q for q in candidates if question is None or q.id != question.id]


def _last_activity(user):
    latest = (
        Answer.select()
        .where((Answer.user == user) & Answer.answered_at.is_null(False))
        .order_by(Answer.answered_at.desc())
        .first()
    )

    return latest.answered_at if latest else None


def _log_lines(count, level=None):
    path = Path(LOG_DIR) / LOG_FILE_NAME
    if not path.exists():
        return []

    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-count * 4:]

    if level:
        lines = [line for line in lines if f" {level} " in line]

    return [line.rstrip() for line in lines[-count:]]


def _csv_response(rows, filename):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)

    # Excel needs the BOM to read UTF-8 Cyrillic correctly.
    return Response(
        "﻿" + buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
