"""Per-user statistics, shared by the menu and the end-of-cycle summary.

Follow-up answers are excluded throughout. A question and its follow-up are
one reflective unit, so counting both would inflate "Відповідей"; and an
intensity follow-up carries its parent's question type, so without the filter
its values ("7") would rank alongside real emotions in "найчастіші емоції".
"""
from collections import Counter

from bot.config import TOP_EMOTIONS_SHOWN
from bot.enums import QuestionType
from bot.models import Question, Answer
from bot.texts import menu_stats_template, menu_stats_no_emotions


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


def build_stats_text(user):
    return menu_stats_template.format(
        day=user.cycle_day,
        answered=answered_count(user),
        skipped=skipped_count(user),
        emotions=top_emotions(user) or menu_stats_no_emotions,
        steps=answered_count(user, QuestionType.STEP),
        wins=answered_count(user, QuestionType.WIN),
        gratitude=answered_count(user, QuestionType.GRATITUDE),
    )
