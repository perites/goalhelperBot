"""The copy, where it is coupled to something structural.

Most of `texts.py` is prose and has nothing to check. These are the places
where a wording change would break something other than itself.
"""
import re

from bot import texts
from core.enums import IntentionCategory

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def test_every_intention_category_has_a_label():
    """`User.intention_type` stores the *index*, and the label is looked up by
    position — so a label added or removed without the enum silently changes
    what every stored category means."""
    assert len(texts.category_labels) == len(IntentionCategory)


def test_the_menu_button_list_covers_every_button():
    """`answer_text_handler` excludes exactly this list. A button missing from
    it gets its label saved as somebody's answer to the question of the day."""
    from bot.handlers.menu import main_menu_keyboard

    rendered = {button.text for row in main_menu_keyboard().keyboard for button in row}

    assert rendered == set(texts.main_menu_buttons)


def test_no_message_is_left_in_english():
    """A participant typing /cancel used to be answered with "Cancelled."."""
    reachable = [
        texts.onboarding_cancelled_message,
        texts.consent_declined_message,
        texts.question_saved_message,
        texts.question_skipped_message,
        texts.question_already_closed_message,
        texts.menu_not_participant_message,
    ]

    for message in reachable:
        assert re.search(r"[а-яїєіґА-ЯЇЄІҐ]", message), message


def test_templates_only_ask_for_fields_their_callers_pass():
    """A stray `{...}` reaches the participant verbatim, which is how a message
    ends up reading "День {day} із {total}"."""
    expected = {
        "question_message_template": {"day", "total", "intention", "question"},
        "menu_my_info_template": {"intention", "name", "category", "times", "day", "total"},
        "menu_stats_template": {
            "day", "answered", "skipped", "emotions", "steps", "wins", "gratitude",
        },
        "onboarding_confirm_template": {"intention", "name", "category", "times"},
        "menu_edit_times_saved_template": {"times"},
        "menu_already_paused_template": {"days_left"},
        "cycle_final_summary_intro": {"total"},
        "cycle_final_intro": {"total"},
        "question_answered_suffix": {"answer"},
        "onboarding_intention_message": {"intention_type"},
    }

    for name, fields in expected.items():
        assert set(PLACEHOLDER.findall(getattr(texts, name))) == fields, name
