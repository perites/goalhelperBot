"""The question bank: the daily rotation and the closing block.

Deletion is the part worth reading twice. Anything a participant has already
seen stays on record — the admin withdraws it with «Зняти з ротації» instead —
so these routes re-run the same blockers that grey the buttons out, and a
hand-made POST hits the identical guard.
"""
from flask import abort, flash, redirect, render_template, request, url_for

from admin import forms
from admin.auth import login_required
from core.enums import QuestionType
from core.logs import get_logger
from core.models import FinalQuestion, Question
from core.services.cohort import current_cohort
from core.services.deletion import (
    DeletionBlocked,
    delete_final_question,
    delete_question,
    final_question_blocker,
    question_blocker,
)

logger = get_logger(__name__)


def register(app):
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
                    "text": forms.text_field(request.form, "text", "Текст"),
                    "type": forms.enum_field(
                        request.form, "type", "Категорія", QuestionType),
                    "options": forms.parse_options(request.form.get("options")),
                    "allows_free_text": bool(request.form.get("allows_free_text")),
                    "retired": bool(request.form.get("retired")),
                    "parent": forms.parent_field(request.form, question),
                }
            except forms.FormError as error:
                flash(str(error), "error")
                return redirect(url_for("question_form", question_id=question_id))
            except ValueError as error:
                # Only `parse_options` gets this far; FormError is caught above.
                flash(f"Не вдалося прочитати варіанти: {error}", "error")
                return redirect(url_for("question_form", question_id=question_id))

            if question is None:
                question = Question.create(order=forms.next_order(Question), **fields)
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
            order=forms.next_order(Question),
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
            FinalQuestion.create(text=text, order=forms.next_order(FinalQuestion))
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
