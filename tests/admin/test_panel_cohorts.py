"""Creating, activating and deleting cohorts.

Exactly one cohort is active at a time — it is the one `/start` enrols into —
so the activation route standing the others down is the rule worth pinning.
"""
import pytest

from core.enums import CohortStatus, QuestionType, Status
from core.models import Cohort

FORM = {
    "name": "Пілот 2",
    "enrollment_opens": "2026-03-01",
    "enrollment_closes": "2026-03-15",
    "max_people": "10",
    "duration_days": "30",
    "questions_per_day": "3",
    "status": str(int(CohortStatus.RUNNING)),
    "category_order": "0,1,3",
}


def _create(client, **overrides):
    response = client.post("/cohorts/new", data={**FORM, **overrides})
    assert response.status_code == 302

    return Cohort.select().order_by(Cohort.id.desc()).first()


# --- creating --------------------------------------------------------------

def test_the_first_cohort_is_made_active(client):
    cohort = _create(client)

    assert cohort.is_active is True
    assert cohort.name == "Пілот 2"
    assert cohort.duration_days == 30
    assert cohort.max_people == 10
    assert cohort.questions_per_day == 3


def test_a_later_cohort_does_not_steal_the_active_flag(client):
    first = _create(client, name="Перша")
    second = _create(client, name="Друга")

    assert Cohort.get_by_id(first.id).is_active is True
    assert second.is_active is False


def test_the_category_order_round_trips(client):
    cohort = _create(client)

    assert cohort.categories == [
        QuestionType.EMOTION, QuestionType.STEP, QuestionType.GRATITUDE,
    ]


def test_an_empty_category_order_is_accepted_and_reads_as_nothing(client):
    """The panel shows plainly what empty means; the bot logs and skips. What
    it must not do is refuse to save a cohort mid-edit."""
    cohort = _create(client, category_order="")

    assert cohort.categories == []


def test_a_nameless_cohort_gets_a_placeholder(client):
    cohort = _create(client, name="   ")

    assert cohort.name == "Без назви"


def test_creating_sends_you_to_the_cohort_page(client):
    response = client.post("/cohorts/new", data=FORM)
    cohort = Cohort.get()

    assert response.headers["Location"] == f"/cohorts/{cohort.id}"


# --- editing ---------------------------------------------------------------

def test_editing_a_cohort(client, cohort):
    client.post(f"/cohorts/{cohort.id}", data={**FORM, "name": "Перейменована"})

    cohort = Cohort.get_by_id(cohort.id)
    assert cohort.name == "Перейменована"
    assert cohort.max_people == 10


def test_editing_does_not_change_which_cohort_is_active(client):
    first = _create(client, name="Перша")
    second = _create(client, name="Друга")

    client.post(f"/cohorts/{second.id}", data={**FORM, "name": "Друга, змінена"})

    assert Cohort.get_by_id(first.id).is_active is True
    assert Cohort.get_by_id(second.id).is_active is False


# --- activating ------------------------------------------------------------

def test_activating_stands_the_others_down(client):
    first = _create(client, name="Перша")
    second = _create(client, name="Друга")

    response = client.post(f"/cohorts/{second.id}/activate")

    assert response.status_code == 302
    assert Cohort.get_by_id(first.id).is_active is False
    assert Cohort.get_by_id(second.id).is_active is True


def test_activating_an_unknown_cohort_is_a_404(client):
    assert client.post("/cohorts/999/activate").status_code == 404


# --- deleting --------------------------------------------------------------

def test_deleting_a_cohort_nobody_joined(client):
    _create(client, name="Перша")
    second = _create(client, name="Помилкова")

    response = client.post(f"/cohorts/{second.id}/delete")

    assert response.status_code == 302
    assert response.headers["Location"] == "/cohorts"
    assert Cohort.get_or_none(Cohort.id == second.id) is None


def test_the_active_cohort_cannot_be_deleted(client):
    """It is the one new participants land in — stand another up first."""
    cohort = _create(client)

    response = client.post(f"/cohorts/{cohort.id}/delete")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/cohorts/{cohort.id}"
    assert Cohort.get_or_none(Cohort.id == cohort.id) is not None


def test_a_cohort_with_participants_cannot_be_deleted(client, cohort, make_user):
    make_user(telegram_id=701, status=Status.FINISHED)

    client.post(f"/cohorts/{cohort.id}/delete")

    assert Cohort.get_or_none(Cohort.id == cohort.id) is not None


def test_deleting_an_unknown_cohort_is_a_404(client):
    assert client.post("/cohorts/999/delete").status_code == 404


# --- input the form did not produce ----------------------------------------

@pytest.mark.parametrize(
    "field,value",
    [
        ("max_people", "десять"),
        ("max_people", "0"),
        ("duration_days", ""),
        ("duration_days", "-1"),
        ("questions_per_day", "багато"),
        ("enrollment_opens", "not-a-date"),
        ("enrollment_closes", "31.12.2026"),
        ("status", "99"),
        ("category_order", "0,99"),
    ],
)
def test_bad_input_is_reported_rather_than_crashing(client, field, value):
    """The template marks these `required` and `type=number`, but that is the
    browser's opinion — a stale tab or a replayed POST sends whatever it likes,
    and it used to reach `int()` and `DateField` unexamined."""
    response = client.post("/cohorts/new", data={**FORM, field: value})

    assert response.status_code == 302
    assert response.headers["Location"] == "/cohorts/new"
    assert Cohort.select().count() == 0


def test_bad_input_says_which_field_was_wrong(client):
    response = client.post(
        "/cohorts/new", data={**FORM, "max_people": "десять"}, follow_redirects=True,
    )

    assert "Місць" in response.get_data(as_text=True)


def test_a_bad_edit_leaves_the_existing_cohort_alone(client, cohort):
    before = cohort.max_people

    client.post(f"/cohorts/{cohort.id}", data={**FORM, "duration_days": "nope"})

    assert Cohort.get_by_id(cohort.id).max_people == before
