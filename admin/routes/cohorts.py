"""Cohorts: the enrollment window, capacity, and the daily rhythm.

Exactly one is active — it is the one `/start` enrols into — so activating a
cohort stands the rest down in the same transaction.
"""
from flask import abort, flash, redirect, render_template, request, url_for

from admin import forms
from admin.auth import login_required
from core.enums import CohortStatus, QuestionType, Status
from core.logs import get_logger
from core.models import Cohort, User
from core.services.cohort import activate_cohort, seats_taken
from core.services.deletion import DeletionBlocked, cohort_blocker, delete_cohort

logger = get_logger(__name__)

# ENDED is left out on purpose: the daily sweep sets it, once no participant is
# still running. Offering it here would let the panel end a cohort without
# standing it down, which is the other half of what ending one means.
SETTABLE_STATUSES = [CohortStatus.PLANNED, CohortStatus.RUNNING]


def register(app):
    @app.route("/cohorts")
    @login_required
    def cohorts():
        rows = []
        for cohort in Cohort.select().order_by(
                Cohort.is_active.desc(), Cohort.enrollment_opens.desc()):
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

        # An ended cohort keeps its status: the form stops offering the field
        # rather than offering it and refusing every value.
        ended = cohort is not None and cohort.status == CohortStatus.ENDED

        if request.method == "POST":
            try:
                fields = {
                    "name": (request.form.get("name") or "").strip() or "Без назви",
                    "enrollment_opens": forms.date_field(
                        request.form, "enrollment_opens", "Початок набору"),
                    "enrollment_closes": forms.date_field(
                        request.form, "enrollment_closes", "Кінець набору"),
                    "max_people": forms.int_field(request.form, "max_people", "Місць"),
                    "duration_days": forms.int_field(
                        request.form, "duration_days", "Тривалість циклу"),
                    "questions_per_day": forms.int_field(
                        request.form, "questions_per_day", "Питань на день"),
                    # The builder posts one hidden field holding the whole order,
                    # since the same category may appear several times.
                    "category_order": forms.category_order_field(request.form),
                }

                if not ended:
                    fields["status"] = forms.enum_field(
                        request.form, "status", "Стан", CohortStatus,
                        allowed=SETTABLE_STATUSES,
                    )
            except forms.FormError as error:
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
            # A new cohort starts with no rhythm: the builder is where it gets
            # decided, and the preview says plainly what empty means.
            order=[int(t) for t in cohort.categories] if cohort else [],
            statuses=SETTABLE_STATUSES,
            ended=ended,
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
