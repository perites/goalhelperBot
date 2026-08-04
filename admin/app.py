"""Routes for the admin panel."""
import csv
import io
import json
import logging
import os
import secrets
from collections import Counter
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request, Response,
    send_from_directory, session, url_for,
)

from bot import clock, models
from bot.config import (
    ADMIN_LOG_FILE_NAME, LOG_DIR, LOG_FILE_NAME, QUESTION_ORDER_STEP,
)
from bot.enums import CohortStatus, QuestionType, Status
from bot.logs import ROOT_LOGGER_NAME, get_logger
from bot.models import (
    Answer, Cohort, FinalAnswer, FinalQuestion, Question, User, )
from bot.services.cohort import (
    activate_cohort, current_cohort, enrollment_state, seats_left, seats_taken,
)
from bot.services.cycle import finish_user, pause_user, resume_user
from bot.services.deletion import (
    DeletionBlocked,
    cohort_blocker,
    delete_cohort,
    delete_final_question,
    delete_question,
    final_question_blocker,
    question_blocker,
)
from bot.services.slots import format_slots, saved_slots
from bot.services.stats import answered_count, skipped_count, top_emotions

LOG_TAIL_LINES = 400

# The two files that are written to right now, as opposed to rotated archives.
# The bot's comes first: it is what the logs page opens on.
LIVE_LOG_NAMES = (LOG_FILE_NAME, ADMIN_LOG_FILE_NAME)

logger = get_logger("admin.app")


def _attach_logging(app):
    """Send Flask's own records to whatever `configure_logging` set up.

    `app.logger` lives outside the "bot" namespace, so without this it reaches
    no handler at all — and an unhandled exception in a route would leave no
    trace anywhere, least of all on the logs page this same process serves.

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


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("ADMIN_SECRET_KEY") or secrets.token_hex(32)

    _attach_logging(app)

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


def _safe_next(target):
    """Where to land after signing in — only ever somewhere inside the panel.

    `next` is read straight out of the URL, so without this a crafted link
    would bounce the admin off-site the moment they typed the password. A
    leading `//` is a protocol-relative URL and goes elsewhere too, so a plain
    startswith("/") is not enough on its own.
    """
    if target and target.startswith("/") and not target.startswith("//"):
        return target

    return url_for("dashboard")


def _parse_options(raw):
    """The options field is JSON. Blank means an open question."""
    raw = (raw or "").strip()
    if not raw:
        return None

    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("options must be a JSON list")

    return json.dumps(parsed, ensure_ascii=False)


# --- form fields -----------------------------------------------------------
#
# The templates mark their inputs `required` and `type=number`, but that is the
# browser's opinion and only the browser's: a stale tab, a resubmitted form or
# anything not a browser posts whatever it likes. These read each field once
# and say what was wrong, so a bad value is a message rather than a 500 — and
# so nothing out of range reaches a column other pages later read back.

class FormError(ValueError):
    """A submitted field the panel could not make sense of.

    The message is shown to the admin as-is, so it names the field and says
    what was expected. Raised rather than returned so a whole form can be read
    as one expression, with the first problem stopping it.
    """


def _text_field(form, name, label):
    value = (form.get(name) or "").strip()
    if not value:
        raise FormError(f"«{label}»: не може бути порожнім.")

    return value


def _int_field(form, name, label, minimum=1):
    raw = (form.get(name) or "").strip()

    try:
        value = int(raw)
    except ValueError:
        raise FormError(f"«{label}»: очікується число, а не «{raw}».")

    if value < minimum:
        raise FormError(f"«{label}»: не може бути менше {minimum}.")

    return value


def _date_field(form, name, label):
    raw = (form.get(name) or "").strip()

    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise FormError(
            f"«{label}»: очікується дата у форматі РРРР-ММ-ДД, а не «{raw}»."
        )


def _enum_field(form, name, label, enum):
    """One `int()` and one lookup, so a value that is not a number and a number
    that is not a member fail the same way."""
    raw = (form.get(name) or "").strip()

    try:
        return enum(int(raw))
    except ValueError:
        raise FormError(f"«{label}»: невідоме значення «{raw}».")


def _category_order_field(form, name="category_order"):
    """The rhythm as the builder posts it: QuestionType values joined by commas.

    Empty is allowed and means "not decided yet" — the cohort page says plainly
    what that costs, and refusing to save would trap a half-built cohort.
    """
    raw = (form.get(name) or "").strip()
    if not raw:
        return ""

    known = {member.value for member in QuestionType}

    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) not in known:
            raise FormError(f"«Порядок категорій»: невідома категорія «{part}».")

    return raw


def _parent_field(form, question):
    """Which rotation question this one is a follow-up to, or None.

    The dropdown only ever offers rotation questions, but nothing stopped a
    POST naming something else — and a question parented to itself, or hung off
    another follow-up, leaves the rotation without any way back.
    """
    raw = (form.get("parent") or "").strip()
    if not raw:
        return None

    try:
        parent_id = int(raw)
    except ValueError:
        raise FormError(f"«Уточнення до»: невідоме питання «{raw}».")

    parent = Question.get_or_none(Question.id == parent_id)
    if parent is None:
        raise FormError("«Уточнення до»: такого питання вже немає.")

    if question is not None and parent.id == question.id:
        raise FormError("«Уточнення до»: питання не може уточнювати саме себе.")

    if parent.parent_id is not None:
        raise FormError("«Уточнення до»: уточнення до уточнення не підтримуються.")

    return parent.id


def _next_order():
    highest = Question.select(Question.order).order_by(Question.order.desc()).first()

    return (highest.order + QUESTION_ORDER_STEP) if highest else QUESTION_ORDER_STEP


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
                logger.info("Admin signed in from %s", request.remote_addr)

                return redirect(_safe_next(request.args.get("next")))

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
            recent_problems=_recent_problems(60)[:8],
        )

    # --- questions ---------------------------------------------------------

    @app.route("/questions")
    @login_required
    def questions():
        """Daily questions and the closing block on one page, as two views."""
        view = request.args.get("view", "rotation")
        cohort = current_cohort()

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

        final = list(FinalQuestion.select().order_by(FinalQuestion.order))

        return render_template(
            "questions.html",
            view=view,
            grouped=grouped,
            final=final,
            # Why each row can't be deleted, keyed by id — the same functions
            # the delete routes enforce with.
            blocked={q.id: question_blocker(q) for group in grouped
                     for root in group["questions"]
                     for q in (root, *root.follow_ups)},
            final_blocked={q.id: final_question_blocker(q) for q in final},
            # Nothing is in rotation without an active cohort to define one.
            in_rotation=[int(t) for t in (cohort.categories if cohort else [])],
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
                fields = {
                    "text": _text_field(request.form, "text", "Текст"),
                    "type": _enum_field(request.form, "type", "Категорія", QuestionType),
                    "options": _parse_options(request.form.get("options")),
                    "allows_free_text": bool(request.form.get("allows_free_text")),
                    "retired": bool(request.form.get("retired")),
                    "parent": _parent_field(request.form, question),
                }
            except FormError as error:
                flash(str(error), "error")
                return redirect(url_for("question_form", question_id=question_id))
            except ValueError as error:
                # Only `_parse_options` gets this far; FormError is caught above.
                flash(f"Не вдалося прочитати варіанти: {error}", "error")
                return redirect(url_for("question_form", question_id=question_id))

            if question is None:
                question = Question.create(order=_next_order(), **fields)
                logger.info("Question id=%s created from the admin panel", question.id)
                flash("Питання створено.", "ok")
            else:
                for key, value in fields.items():
                    setattr(question, key, value)
                question.save()
                logger.info("Question id=%s edited from the admin panel", question.id)
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
            blocked=question_blocker(question) if question else None,
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

    @app.route("/questions/<int:question_id>/delete", methods=["POST"])
    @login_required
    def question_delete(question_id):
        """Only for questions nobody has seen yet — see services/deletion.py."""
        question = Question.get_or_none(Question.id == question_id)
        if question is None:
            abort(404)

        try:
            delete_question(question)
        except DeletionBlocked as blocked:
            flash(f"Питання не видалено. {blocked}", "error")
            return redirect(url_for("question_form", question_id=question_id))

        flash("Питання видалено.", "ok")

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
            FinalQuestion.create(
                text=text,
                order=(highest.order + QUESTION_ORDER_STEP) if highest else QUESTION_ORDER_STEP,
            )
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

    @app.route("/questions/final/<int:question_id>/delete", methods=["POST"])
    @login_required
    def final_question_delete(question_id):
        question = FinalQuestion.get_or_none(FinalQuestion.id == question_id)
        if question is None:
            abort(404)

        try:
            delete_final_question(question)
        except DeletionBlocked as blocked:
            flash(f"Питання не видалено. {blocked}", "error")
        else:
            flash("Підсумкове питання видалено.", "ok")

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
                "blocked": cohort_blocker(cohort),
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
            try:
                fields = {
                    "name": (request.form.get("name") or "").strip() or "Без назви",
                    "enrollment_opens": _date_field(
                        request.form, "enrollment_opens", "Початок набору"),
                    "enrollment_closes": _date_field(
                        request.form, "enrollment_closes", "Кінець набору"),
                    "max_people": _int_field(request.form, "max_people", "Місць"),
                    "duration_days": _int_field(
                        request.form, "duration_days", "Тривалість циклу"),
                    "questions_per_day": _int_field(
                        request.form, "questions_per_day", "Питань на день"),
                    "status": _enum_field(request.form, "status", "Стан", CohortStatus),
                    # The builder posts one hidden field holding the whole order,
                    # since the same category may appear several times.
                    "category_order": _category_order_field(request.form),
                }
            except FormError as error:
                flash(str(error), "error")
                return redirect(url_for("cohort_form", cohort_id=cohort_id))

            if cohort is None:
                first_one = not Cohort.select().exists()
                cohort = Cohort.create(is_active=first_one, **fields)
                logger.info(
                    "Cohort id=%s (%s) created from the admin panel", cohort.id, cohort.name
                )
                flash("Когорту створено.", "ok")
            else:
                for key, value in fields.items():
                    setattr(cohort, key, value)
                cohort.save()
                logger.info(
                    "Cohort id=%s (%s) edited from the admin panel", cohort.id, cohort.name
                )
                flash("Збережено.", "ok")

            return redirect(url_for("cohort_form", cohort_id=cohort.id))

        return render_template(
            "cohort.html",
            cohort=cohort,
            types=list(QuestionType),
            # A new cohort starts with no rhythm: the builder below is where it
            # gets decided, and the preview says plainly what empty means.
            order=[int(t) for t in cohort.categories] if cohort else [],
            statuses=list(CohortStatus),
            blocked=cohort_blocker(cohort) if cohort else None,
        )

    @app.route("/cohorts/<int:cohort_id>/delete", methods=["POST"])
    @login_required
    def cohort_delete(cohort_id):
        """Only for cohorts nobody has joined — see services/deletion.py."""
        cohort = Cohort.get_or_none(Cohort.id == cohort_id)
        if cohort is None:
            abort(404)

        try:
            delete_cohort(cohort)
        except DeletionBlocked as blocked:
            flash(f"Когорту не видалено. {blocked}", "error")
            return redirect(url_for("cohort_form", cohort_id=cohort_id))

        flash(f"Когорту «{cohort.name}» видалено.", "ok")

        return redirect(url_for("cohorts"))

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
        # The bot and the panel write separate files, so which one you are
        # looking at is part of the page's state.
        name = _live_log_name(request.args.get("file"))
        path = _log_path(name)

        return render_template(
            "logs.html",
            lines=_log_lines(LOG_TAIL_LINES, path, level=level or None),
            level=level,
            path=path,
            file=name,
            files=LIVE_LOG_NAMES,
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
        path = _log_path(_live_log_name(request.args.get("file")))

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


def _log_path(name=LOG_FILE_NAME):
    return Path(LOG_DIR) / name


def _live_log_name(requested):
    """Which of the two live logs a request is asking for.

    Anything unrecognised falls back to the bot's, so a hand-typed `?file=`
    can never name a path of the caller's choosing.
    """
    return requested if requested in LIVE_LOG_NAMES else LOG_FILE_NAME


def _log_files():
    """Both processes' logs: the current files first, then whatever the nightly
    rotation has left behind — those are named `<name>.YYYY-MM-DD`, so newest
    is last by name.

    This list is also the allowlist the download route checks against, so a
    file missing from here is a file that cannot be downloaded.
    """
    directory = Path(LOG_DIR)
    if not directory.exists():
        return []

    entries = []
    for live_name in LIVE_LOG_NAMES:
        for path in sorted(directory.glob(f"{live_name}*"), reverse=True):
            if not path.is_file():
                continue

            stat = path.stat()
            entries.append({
                "name": path.name,
                "size_kb": max(1, round(stat.st_size / 1024)),
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y %H:%M"),
                "current": path.name == live_name,
            })

    entries.sort(key=lambda entry: not entry["current"])
    return entries


def _log_lines(count, path, level=None):
    if not path.exists():
        return []

    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-count * 4:]

    if level:
        lines = [line for line in lines if f" {level} " in line]

    return [line.rstrip() for line in lines[-count:]]


def _recent_problems(count):
    """Warnings from both processes together.

    Every line opens with a timestamp in the same fixed-width format, so
    sorting them as plain strings is sorting them by time.
    """
    lines = []
    for name in LIVE_LOG_NAMES:
        lines += _log_lines(count, _log_path(name), level="WARNING")

    return sorted(lines)[-count:]


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
