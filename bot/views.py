"""Turning data into the words a participant reads.

The templates themselves are in `texts.py`; this is where they meet the
database. Kept out of the services so that counting answers and describing them
stay separate jobs — the admin panel wants the first and has its own opinion
about the second.
"""
from bot.texts import (
    menu_stats_no_emotions,
    menu_stats_template,
    question_message_template,
)
from core.services.stats import stats_for


def render_question(answer):
    """The question message as it was originally sent. Uses the stored
    cycle_day so a reply arriving the next day doesn't redraw a wrong number."""
    # A follow-up arrives mid-exchange, so it skips the day/intention header
    # that has just been shown above it.
    if answer.parent_id is not None:
        return answer.question.text

    user = answer.user

    return question_message_template.format(
        day=answer.cycle_day if answer.cycle_day is not None else user.cycle_day,
        total=user.cycle_length,
        intention=user.intention,
        question=answer.question.text,
    )


def build_stats_text(user):
    stats = stats_for(user)

    return menu_stats_template.format(
        day=user.cycle_day,
        **{**stats, "emotions": stats["emotions"] or menu_stats_no_emotions},
    )
