"""CSV export — how the pilot's data leaves the machine.

Both files get opened in Excel by a non-technical reader, so the byte-order
mark is part of the contract rather than an accident: without it Excel reads
UTF-8 Cyrillic as mojibake.
"""
import csv
import io

from flask import Response

from admin.auth import login_required
from core.enums import Status
from core.models import Answer, FinalAnswer, User
from core.services.slots import format_slots, saved_slots
from core.services.stats import answered_count, skipped_count

BOM = "﻿"


def _csv_response(rows, filename):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)

    return Response(
        BOM + buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def register(app):
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
