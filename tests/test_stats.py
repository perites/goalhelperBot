"""Statistics counting."""
from core import clock
from core.settings import TOP_EMOTIONS_SHOWN
from core.enums import QuestionType
from core.models import Answer, FinalAnswer, Question
from bot.views import build_stats_text
from core.services.stats import answered_count, skipped_count, top_emotions


def _answer(user, question, text=None, skipped=False):
    now = clock.now_kyiv()

    return Answer.create(
        user=user, question=question, sent_at=now,
        answered_at=None if (text is None and not skipped) else now,
        answer=text, skipped=skipped,
    )


def _of_type(question_type):
    return Question.select().where(Question.type == question_type).first()


def test_counts_start_at_zero(questions, make_user):
    user = make_user()

    assert answered_count(user) == 0
    assert skipped_count(user) == 0
    assert top_emotions(user) == ""


def test_answered_and_skipped_are_counted_separately(questions, make_user):
    user = make_user()
    _answer(user, questions[0], text="одна")
    _answer(user, questions[1], text="дві")
    _answer(user, questions[2], skipped=True)
    _answer(user, questions[3])  # still open

    assert answered_count(user) == 2
    assert skipped_count(user) == 1


def test_counts_are_per_user(questions, make_user):
    mine = make_user(telegram_id=1)
    theirs = make_user(telegram_id=2)

    _answer(mine, questions[0], text="моя")
    _answer(theirs, questions[0], text="їхня")

    assert answered_count(mine) == 1
    assert answered_count(theirs) == 1


def test_counts_by_question_type(questions, make_user):
    user = make_user()
    _answer(user, _of_type(QuestionType.STEP), text="крок")
    _answer(user, _of_type(QuestionType.WIN), text="перемога")

    assert answered_count(user, QuestionType.STEP) == 1
    assert answered_count(user, QuestionType.GRATITUDE) == 0


def test_top_emotions_ranks_by_frequency(questions, make_user):
    user = make_user()
    emotion_question = _of_type(QuestionType.EMOTION)

    for text in ["втома", "втома", "втома", "цікавість", "цікавість", "спокій", "сум"]:
        _answer(user, emotion_question, text=text)

    ranked = top_emotions(user).split(", ")

    assert ranked[0] == "втома"
    assert ranked[1] == "цікавість"
    assert len(ranked) == TOP_EMOTIONS_SHOWN


def test_closing_answers_do_not_pollute_stats(questions, make_user):
    user = make_user()
    _answer(user, questions[0], text="щоденна")
    FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(),
        answered_at=clock.now_kyiv(), answer="підсумкова",
    )

    # FinalAnswer is a separate table, so it can't leak into daily counts.
    assert answered_count(user) == 1


def test_stats_text_renders_without_placeholders(questions, make_user):
    user = make_user(started_days_ago=11)
    _answer(user, questions[0], text="одна")

    text = build_stats_text(user)

    assert "{" not in text and "}" not in text
    assert "12" in text
