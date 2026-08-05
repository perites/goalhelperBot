"""CSV export — how the pilot's data actually leaves the machine.

Both files are opened in Excel by a non-technical reader, so the BOM and the
header row are part of the contract, not incidental.
"""
import csv
import io

from core import clock
from core.enums import Status
from core.models import Answer, FinalAnswer, User

BOM = "﻿"


def _rows(response):
    body = response.get_data(as_text=True)
    assert body.startswith(BOM), "Excel needs the BOM to read UTF-8 Cyrillic"

    return list(csv.reader(io.StringIO(body[len(BOM):])))


def test_users_export_is_a_download(client):
    response = client.get("/export/users.csv")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert 'filename="users.csv"' in response.headers["Content-Disposition"]


def test_users_export_has_a_header_even_when_empty(client):
    rows = _rows(client.get("/export/users.csv"))

    assert rows[0][:2] == ["telegram_id", "name"]
    assert len(rows) == 1


def test_users_export_lists_one_row_per_participant(client, cohort, make_user):
    first = make_user(telegram_id=901, slots=(9, 19))
    make_user(telegram_id=902)

    rows = _rows(client.get("/export/users.csv"))
    by_id = {row[0]: row for row in rows[1:]}

    assert set(by_id) == {"901", "902"}
    assert by_id["901"][1] == first.name
    assert by_id["901"][2] == "ACTIVE"
    assert "09:00" in by_id["901"][5] and "19:00" in by_id["901"][5]


def test_users_export_includes_people_with_no_cohort(client):
    """The waitlist is exactly who Ксенія wants to contact when a place opens,
    so it must survive the export — this reads `cycle_day`, which copes with a
    missing cohort, rather than `cycle_length`, which does not."""
    User.create(telegram_id=903, status=Status.WAITLIST, cohort=None)

    rows = _rows(client.get("/export/users.csv"))

    assert rows[1][0] == "903"
    assert rows[1][2] == "WAITLIST"


def test_answers_export_is_a_download(client):
    response = client.get("/export/answers.csv")

    assert response.status_code == 200
    assert 'filename="answers.csv"' in response.headers["Content-Disposition"]


def test_answers_export_carries_the_question_and_the_reply(
    client, cohort, questions, make_user,
):
    user = make_user(telegram_id=904)
    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="радість", cycle_day=3, slot="09:00",
    )

    rows = _rows(client.get("/export/answers.csv"))

    assert rows[0][:5] == ["telegram_id", "name", "cycle_day", "slot", "question"]
    assert rows[1][:8] == [
        "904", user.name, "3", "09:00", questions[0].text, "no", "радість", "no",
    ]


def test_answers_export_marks_follow_ups(client, cohort, questions, make_user):
    user = make_user(telegram_id=905)
    parent = Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="сум", cycle_day=1,
    )
    follow_up = list(questions[0].follow_ups)[0]
    Answer.create(
        user=user, question=follow_up, sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="4", cycle_day=1, parent=parent,
    )

    flags = [row[5] for row in _rows(client.get("/export/answers.csv"))[1:]]

    assert sorted(flags) == ["no", "yes"]


def test_answers_export_marks_skips(client, cohort, questions, make_user):
    user = make_user(telegram_id=906)
    Answer.create(
        user=user, question=questions[0], sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), skipped=True, cycle_day=1,
    )

    assert _rows(client.get("/export/answers.csv"))[1][7] == "yes"


def test_answers_export_includes_the_closing_block(client, cohort, make_user):
    user = make_user(telegram_id=907)
    FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), answered_at=clock.now_kyiv(),
        answer="Стало спокійніше", message_text="1. Що змінилось?",
    )

    rows = _rows(client.get("/export/answers.csv"))

    assert rows[1][4] == "closing block"
    assert rows[1][6] == "Стало спокійніше"
