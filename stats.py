"""Per-user statistics, shared by the menu and the end-of-cycle summary."""
from collections import Counter

from database import Question, Answer, QuestionType
from messages_texts import menu_stats_template, menu_stats_no_emotions

TOP_EMOTIONS = 3


def answered_count(user, question_type=None):
    query = (
        Answer.select()
        .join(Question)
        .where((Answer.user == user) & Answer.answer.is_null(False))
    )

    if question_type is not None:
        query = query.where(Question.type == question_type)

    return query.count()


def skipped_count(user):
    return Answer.select().where((Answer.user == user) & (Answer.skipped == True)).count()  # noqa: E712


def top_emotions(user):
    chosen = (
        Answer.select(Answer.answer)
        .join(Question)
        .where(
            (Answer.user == user)
            & (Question.type == QuestionType.EMOTION)
            & Answer.answer.is_null(False)
        )
    )

    ranked = Counter(row.answer for row in chosen).most_common(TOP_EMOTIONS)

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
