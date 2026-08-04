"""Editing the question bank through the panel.

Deletion is the interesting part: anything a participant has already seen must
survive, and the routes re-run the same blockers the buttons are greyed out
with — so a hand-made POST hits the identical guard.
"""
import pytest

from core import clock
from core.settings import QUESTION_ORDER_STEP
from core.enums import QuestionType
from core.models import Answer, FinalAnswer, FinalQuestion, Question


# --- creating and editing --------------------------------------------------

def test_creating_a_question(client):
    response = client.post(
        "/questions/new",
        data={"text": "  Що сьогодні важливо?  ", "type": str(int(QuestionType.FOCUS))},
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/questions"

    question = Question.get()
    assert question.text == "Що сьогодні важливо?"  # stripped
    assert question.type == QuestionType.FOCUS
    assert question.order == QUESTION_ORDER_STEP
    assert question.options is None
    assert question.parent is None


def test_each_new_question_leaves_a_gap_in_the_order(client):
    for index in range(3):
        client.post("/questions/new", data={"text": f"Q{index}", "type": "0"})

    orders = [q.order for q in Question.select().order_by(Question.order)]

    assert orders == [10, 20, 30]


def test_editing_a_question(client, questions):
    question = questions[1]

    response = client.post(
        f"/questions/{question.id}",
        data={
            "text": "Переписане питання",
            "type": str(int(QuestionType.WIN)),
            "retired": "on",
        },
    )

    assert response.status_code == 302

    question = Question.get_by_id(question.id)
    assert question.text == "Переписане питання"
    assert question.type == QuestionType.WIN
    assert question.retired is True


def test_options_round_trip_through_the_form(client):
    client.post(
        "/questions/new",
        data={
            "text": "Яка емоція?",
            "type": "0",
            "options": '["радість", ["Складні", "сум", "втома"]]',
            "allows_free_text": "on",
        },
    )

    question = Question.get()
    assert question.option_list == ["радість", ["Складні", "сум", "втома"]]
    assert question.allows_free_text is True
    # Two inside the group plus the loose one.
    assert question.option_count == 3


def test_unicode_options_are_stored_readably(client):
    """`ensure_ascii=False`, so the column stays legible in sqlite-web."""
    client.post("/questions/new", data={"text": "Q", "type": "0", "options": '["радість"]'})

    assert "радість" in Question.get().options


@pytest.mark.parametrize("options", ["not json at all", '{"not": "a list"}'])
def test_unreadable_options_are_refused_without_creating_anything(client, options):
    response = client.post(
        "/questions/new", data={"text": "Q", "type": "0", "options": options},
    )

    assert response.status_code == 302
    assert Question.select().count() == 0


def test_a_question_can_be_attached_to_a_parent(client, questions):
    parent = questions[1]

    client.post(
        "/questions/new",
        data={"text": "А що з цього простіше?", "type": "1", "parent": str(parent.id)},
    )

    child = Question.get(Question.text == "А що з цього простіше?")
    assert child.parent_id == parent.id


# --- input the form did not produce ----------------------------------------

@pytest.mark.parametrize(
    "data",
    [
        {"text": "", "type": "0"},
        {"text": "   ", "type": "0"},
        {"text": "Q", "type": "99"},
        {"text": "Q", "type": "категорія"},
        {"text": "Q", "type": ""},
    ],
    ids=["blank text", "whitespace text", "unknown type", "type not a number", "no type"],
)
def test_a_question_the_form_could_not_have_produced_is_refused(client, data):
    """An out-of-range `type` used to save happily and then simply never
    appear on the questions page again, since that page groups by the known
    categories."""
    response = client.post("/questions/new", data=data)

    assert response.status_code == 302
    assert Question.select().count() == 0


def test_a_question_cannot_be_made_its_own_follow_up(client, questions):
    question = questions[1]

    client.post(
        f"/questions/{question.id}",
        data={"text": question.text, "type": "1", "parent": str(question.id)},
    )

    assert Question.get_by_id(question.id).parent_id is None


def test_a_follow_up_cannot_hang_off_another_follow_up(client, questions):
    """The dropdown only ever offers rotation questions; nothing used to stop a
    POST naming something else, which would strand the whole branch."""
    parent = next(question for question in questions if question.follow_ups)
    existing_follow_up = list(parent.follow_ups)[0]

    response = client.post(
        "/questions/new",
        data={"text": "Ще глибше?", "type": "0", "parent": str(existing_follow_up.id)},
    )

    assert response.status_code == 302
    assert Question.get_or_none(Question.text == "Ще глибше?") is None


def test_a_parent_that_no_longer_exists_is_refused(client):
    response = client.post(
        "/questions/new", data={"text": "Q", "type": "0", "parent": "999"},
    )

    assert response.status_code == 302
    assert Question.select().count() == 0


# --- retiring --------------------------------------------------------------

def test_retiring_and_restoring_a_question(client, questions):
    question = questions[0]
    assert question.retired is False

    client.post(f"/questions/{question.id}/retire")
    assert Question.get_by_id(question.id).retired is True

    client.post(f"/questions/{question.id}/retire")
    assert Question.get_by_id(question.id).retired is False


# --- duplicating -----------------------------------------------------------

def test_duplicating_a_question_brings_its_follow_ups(client, questions):
    original = next(question for question in questions if question.follow_ups)
    before = Question.select().count()

    response = client.post(f"/questions/{original.id}/duplicate")

    assert response.status_code == 302
    assert Question.select().count() == before + 1 + len(list(original.follow_ups))

    copies = list(Question.select().where(
        (Question.text == original.text) & (Question.id != original.id)
    ))
    assert len(copies) == 1
    assert len(list(copies[0].follow_ups)) == len(list(original.follow_ups))


def test_the_copy_is_where_the_form_sends_you(client, questions):
    response = client.post(f"/questions/{questions[1].id}/duplicate")

    copy = Question.select().order_by(Question.id.desc()).first()
    assert response.headers["Location"] == f"/questions/{copy.id}"


# --- deleting --------------------------------------------------------------

def test_deleting_a_question_nobody_has_seen(client):
    client.post("/questions/new", data={"text": "Одруківка", "type": "0"})
    question = Question.get()

    response = client.post(f"/questions/{question.id}/delete")

    assert response.status_code == 302
    assert response.headers["Location"] == "/questions"
    assert Question.select().count() == 0


def test_a_question_that_has_been_sent_cannot_be_deleted(client, questions, make_user):
    question = next(q for q in questions if not q.follow_ups)
    user = make_user(telegram_id=601)
    Answer.create(user=user, question=question, sent_at=clock.now_kyiv(), cycle_day=1)

    response = client.post(f"/questions/{question.id}/delete")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/questions/{question.id}"
    assert Question.get_or_none(Question.id == question.id) is not None


def test_a_question_with_follow_ups_cannot_be_deleted(client, questions):
    parent = next(question for question in questions if question.follow_ups)

    client.post(f"/questions/{parent.id}/delete")

    assert Question.get_or_none(Question.id == parent.id) is not None


def test_deleting_an_unknown_question_is_a_404(client):
    assert client.post("/questions/999/delete").status_code == 404


# --- closing questions -----------------------------------------------------

def test_adding_a_closing_question(client):
    response = client.post("/questions/final/add", data={"text": "  Що змінилось?  "})

    assert response.status_code == 302
    assert response.headers["Location"] == "/questions?view=final"

    question = FinalQuestion.get()
    assert question.text == "Що змінилось?"
    assert question.order == QUESTION_ORDER_STEP


def test_a_blank_closing_question_is_ignored(client):
    client.post("/questions/final/add", data={"text": "   "})

    assert FinalQuestion.select().count() == 0


def test_retiring_and_restoring_a_closing_question(client, questions):
    question = FinalQuestion.get()

    client.post(f"/questions/final/{question.id}/retire")
    assert FinalQuestion.get_by_id(question.id).retired is True

    client.post(f"/questions/final/{question.id}/retire")
    assert FinalQuestion.get_by_id(question.id).retired is False


def test_deleting_a_closing_question_nobody_has_seen(client):
    client.post("/questions/final/add", data={"text": "Одруківка"})
    question = FinalQuestion.get()

    client.post(f"/questions/final/{question.id}/delete")

    assert FinalQuestion.select().count() == 0


def test_a_closing_question_already_sent_in_a_block_cannot_be_deleted(
    client, questions, make_user,
):
    """`FinalAnswer` holds no reference to individual questions — the block is
    one message — so the stored body is the record of what was asked."""
    question = FinalQuestion.get()
    user = make_user(telegram_id=602)
    FinalAnswer.create(
        user=user,
        sent_at=clock.now_kyiv(),
        message_text=f"Ось кілька останніх питань.\n\n1. {question.text}",
    )

    client.post(f"/questions/final/{question.id}/delete")

    assert FinalQuestion.get_or_none(FinalQuestion.id == question.id) is not None
