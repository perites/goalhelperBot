"""Per-user counts, shared by the bot's statistics screen, the end-of-cycle
summary, and the admin panel.

Follow-up answers are excluded throughout. A question and its follow-up are
one reflective unit, so counting both would inflate "Відповідей"; and an
intensity follow-up carries its parent's question type, so without the filter
its values ("7") would rank alongside real emotions in "найчастіші емоції".

Numbers only — the sentence they get written into is the bot's, and lives in
`bot/views.py`.
"""
from collections import Counter

from core.enums import QuestionType
from core.models import Answer, Question
from core.settings import TOP_EMOTIONS_SHOWN


def answered_count(user, question_type=None):
    query = (
        Answer.select()
        .join(Question)
        .where(
            (Answer.user == user)
            & Answer.answer.is_null(False)
            & Answer.parent.is_null(True)
        )
    )

    if question_type is not None:
        query = query.where(Question.type == question_type)

    return query.count()


def skipped_count(user):
    return (
        Answer.select()
        .where(
            (Answer.user == user)
            & (Answer.skipped == True)  # noqa: E712
            & Answer.parent.is_null(True)
        )
        .count()
    )


def top_emotions(user):
    chosen = (
        Answer.select(Answer.answer)
        .join(Question)
        .where(
            (Answer.user == user)
            & (Question.type == QuestionType.EMOTION)
            & Answer.answer.is_null(False)
            & Answer.parent.is_null(True)
        )
    )

    ranked = Counter(row.answer for row in chosen).most_common(TOP_EMOTIONS_SHOWN)

    return ", ".join(emotion for emotion, _ in ranked)


def stats_for(user):
    """Every number both front ends show about a participant, in one place.

    `emotions` comes back as it is — possibly empty. What to print instead is a
    matter of tone and belongs to whoever is printing it: the bot says «поки що
    немає», the panel says «—».
    """
    return {
        "answered": answered_count(user),
        "skipped": skipped_count(user),
        "emotions": top_emotions(user),
        "steps": answered_count(user, QuestionType.STEP),
        "wins": answered_count(user, QuestionType.WIN),
        "gratitude": answered_count(user, QuestionType.GRATITUDE),
    }
