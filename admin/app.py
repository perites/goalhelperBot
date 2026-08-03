"""Routes for the admin panel."""
import csv
import io
import json
import os
import secrets
from collections import Counter
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, Response,
    send_from_directory, session, url_for,
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
        """Daily questions and the closing block on one page, as two views."""
        view = request.args.get("view", "rotation")

        grouped = []
        if view == "rotation":
            for category in QuestionType:
                rows = list(
                    Question.select()
                    .where((Question.parent.is_null(True)) & (Question.type == category))
                    .order_by(Question.order)
                )
                grouped.append({
                    "category": category,
                    "questions": rows,
                    "live": sum(0 if q.retired else 1 for q in rows),
                })

        return render_template(
            "questions.html",
            view=view,
            grouped=grouped,
            final=FinalQuestion.select().order_by(FinalQuestion.order),
            in_rotation=[int(t) for t in (current_cohort().categories if current_cohort()
                                          else DEFAULT_CATEGORY_ORDER)],
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
                flash(f"Не вдалося прочитати варіанти: {error}", "error")
                return redirect(url_for("question_form", question_id=question_id))

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
                flash("Питання створено.", "ok")
            else:
                for key, value in fields.items():
                    setattr(question, key, value)
                question.save()
                flash("Збережено.", "ok")

            return redirect(url_for("questions"))

        return render_template(
            "question_form.html",
            question=question,
            types=list(QuestionType),
            parents=[
                {"id": q.id, "text": q.text, "type": q.type}
                for q in Question.select().where(Question.parent.is_null(True))
                         .order_by(Question.type, Question.order)
                if question is None or q.id != question.id
            ],
        )

    @app.route("/questions/<int:question_id>/retire", methods=["POST"])
    @login_required
    def question_retire(question_id):
        """Questions are never deleted — answers reference them, and the
        wording is part of the record of what was asked."""
        question = Question.get_or_none(Question.id == question_id)
        if question is None:
            abort(404)

        question.retired = not question.retired
        question.save()

        flash("Знято з ротації." if question.retired else "Повернуто в ротацію.", "ok")

        return redirect(url_for("questions"))

    @app.route("/questions/<int:question_id>/duplicate", methods=["POST"])
    @login_required
    def question_duplicate(question_id):
        original = Question.get_or_none(Question.id == question_id)
        if original is None:
            abort(404)

        copy = Question.create(
            text=original.text,
            type=original.type,
            options=original.options,
            allows_free_text=original.allows_free_text,
            parent=original.parent,
            retired=original.retired,
            order=_next_order(),
        )

        # A root question is only really duplicated if its follow-ups come
        # too, otherwise the copy behaves differently from the original.
        for index, follow_up in enumerate(original.follow_ups, start=1):
            Question.create(
                text=follow_up.text,
                type=follow_up.type,
                options=follow_up.options,
                allows_free_text=follow_up.allows_free_text,
                parent=copy,
                retired=follow_up.retired,
                order=copy.order + index,
            )

        flash("Копію створено — відредагуйте її.", "ok")

        return redirect(url_for("question_form", question_id=copy.id))

    # --- closing questions -------------------------------------------------

    @app.route("/questions/final/add", methods=["POST"])
    @login_required
    def final_question_add():
        text = request.form.get("text", "").strip()
        if text:
            highest = (
                FinalQuestion.select(FinalQuestion.order)
                .order_by(FinalQuestion.order.desc())
                .first()
            )
            FinalQuestion.create(text=text, order=(highest.order + 10) if highest else 10)
            flash("Підсумкове питання додано.", "ok")

        return redirect(url_for("questions", view="final"))

    @app.route("/questions/final/<int:question_id>/retire", methods=["POST"])
    @login_required
    def final_question_retire(question_id):
        question = FinalQuestion.get_or_none(FinalQuestion.id == question_id)
        if question is None:
            abort(404)

        question.retired = not question.retired
        question.save()

        flash("Знято." if question.retired else "Повернуто.", "ok")

        return redirect(url_for("questions", view="final"))

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
        path = _log_path()

        return render_template(
            "logs.html",
            lines=_log_lines(LOG_TAIL_LINES, level=level or None),
            level=level,
            path=path,
            # Where the live tail should start reading from, so it appends
            # only what arrives after this render.
            offset=path.stat().st_size if path.exists() else 0,
            archives=_log_files(),
        )

    @app.route("/logs/tail")
    @login_required
    def logs_tail():
        """New bytes since `offset`. Polled rather than streamed: a long-lived
        connection would tie up a worker and has to be re-established after
        every restart, for no gain at this size."""
        offset = request.args.get("offset", type=int, default=0)
        level = request.args.get("level") or None
        path = _log_path()

        if not path.exists():
            return jsonify(offset=0, lines=[])

        size = path.stat().st_size

        # Midnight rotation leaves the offset past the end of a fresh file.
        if offset > size:
            offset = 0

        with path.open("rb") as handle:
            handle.seek(offset)
            chunk = handle.read()

        # Stop at the last newline so a half-written line isn't shown, and so
        # the next poll doesn't start mid-character.
        cut = chunk.rfind(b"\n") + 1
        chunk, offset = chunk[:cut], offset + cut

        lines = chunk.decode("utf-8", errors="replace").splitlines()
        if level:
            lines = [line for line in lines if f" {level} " in line]

        return jsonify(offset=offset, lines=lines)

    @app.route("/logs/download/<path:name>")
    @login_required
    def logs_download(name):
        # Only ever the files we listed ourselves — never a caller-supplied path.
        if name not in {entry["name"] for entry in _log_files()}:
            abort(404)

        return send_from_directory(
            Path(LOG_DIR).resolve(), name, as_attachment=True, mimetype="text/plain",
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


def _log_path():
    return Path(LOG_DIR) / LOG_FILE_NAME


def _log_files():
    """The current log first, then whatever the nightly rotation has left
    behind — those are named `bot.log.YYYY-MM-DD`, so newest is last by name."""
    directory = Path(LOG_DIR)
    if not directory.exists():
        return []

    entries = []
    for path in sorted(directory.glob(f"{LOG_FILE_NAME}*"), reverse=True):
        if not path.is_file():
            continue

        stat = path.stat()
        entries.append({
            "name": path.name,
            "size_kb": max(1, round(stat.st_size / 1024)),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M"),
            "current": path.name == LOG_FILE_NAME,
        })

    entries.sort(key=lambda entry: not entry["current"])
    return entries


def _log_lines(count, level=None):
    path = _log_path()
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
