"""Which cohort statuses the panel may set.

PLANNED and RUNNING are the admin's to choose between — that pair is the act of
launching a cohort. ENDED belongs to the daily sweep, which also stands the
cohort down; setting it from a form would do half of that and leave the cohort
still active.
"""
from core.enums import CohortStatus
from core.models import Cohort
from core.services.cohort import end_cohort

FORM = {
    "name": "Пілот",
    "enrollment_opens": "2026-03-01",
    "enrollment_closes": "2026-03-15",
    "max_people": "10",
    "duration_days": "30",
    "questions_per_day": "3",
    "status": str(int(CohortStatus.PLANNED)),
    "category_order": "0,1,3",
}


def _create(client, **overrides):
    response = client.post("/cohorts/new", data={**FORM, **overrides})
    assert response.status_code == 302

    return Cohort.select().order_by(Cohort.id.desc()).first()


# --- what the form offers --------------------------------------------------

def test_the_form_offers_planned_and_running_only(client):
    page = client.get("/cohorts/new").get_data(as_text=True)

    assert "PLANNED" in page
    assert "RUNNING" in page
    assert "ENROLLING" not in page
    assert ">ENDED<" not in page


def test_a_cohort_can_be_created_planned(client):
    assert _create(client).status == CohortStatus.PLANNED


def test_the_admin_can_promote_it_to_running(client):
    cohort = _create(client)

    response = client.post(
        f"/cohorts/{cohort.id}",
        data={**FORM, "status": str(int(CohortStatus.RUNNING))},
    )

    assert response.status_code == 302
    assert Cohort.get_by_id(cohort.id).status == CohortStatus.RUNNING


# --- what it refuses -------------------------------------------------------

def test_a_posted_ended_is_refused(client):
    """The select never offers it, but the select is not what enforces it."""
    cohort = _create(client)

    client.post(
        f"/cohorts/{cohort.id}",
        data={**FORM, "status": str(int(CohortStatus.ENDED))},
        follow_redirects=True,
    )

    assert Cohort.get_by_id(cohort.id).status == CohortStatus.PLANNED


def test_the_refusal_says_why(client):
    cohort = _create(client)

    page = client.post(
        f"/cohorts/{cohort.id}",
        data={**FORM, "status": str(int(CohortStatus.ENDED))},
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "не встановлюють вручну" in page


def test_the_retired_enrolling_value_is_refused(client):
    """1 is a hole in the enum now, so it fails the same way anything else
    that is not a member does."""
    cohort = _create(client)

    client.post(f"/cohorts/{cohort.id}", data={**FORM, "status": "1"},
                follow_redirects=True)

    assert Cohort.get_by_id(cohort.id).status == CohortStatus.PLANNED


# --- an ended cohort -------------------------------------------------------

def test_an_ended_cohort_shows_no_status_picker(client):
    cohort = _create(client)
    end_cohort(cohort)

    page = client.get(f"/cohorts/{cohort.id}").get_data(as_text=True)

    assert 'name="status"' not in page
    assert "ENDED" in page


def test_an_ended_cohort_is_still_editable(client):
    """The status field drops out; everything else still saves, and the status
    is left where the sweep put it."""
    cohort = _create(client)
    end_cohort(cohort)

    payload = {key: value for key, value in FORM.items() if key != "status"}
    response = client.post(f"/cohorts/{cohort.id}", data={**payload, "name": "Перейменована"})

    assert response.status_code == 302

    saved = Cohort.get_by_id(cohort.id)
    assert saved.name == "Перейменована"
    assert saved.status == CohortStatus.ENDED
