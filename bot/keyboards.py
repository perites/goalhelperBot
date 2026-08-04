"""Every inline keyboard the bot draws.

Gathered here because this is the one place that has to know both halves of the
protocol at once: what a question's options look like (core) and what a tap
must carry back (`bot/callbacks.py`). Keeping it out of the services is what
lets the admin panel read the question bank without importing Telegram.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot import callbacks
from bot.settings import OPTIONS_PER_ROW, SHORT_OPTION_LENGTH, SLOT_TIMES
from bot.texts import (
    question_answer_button,
    question_back_button,
    question_free_text_button,
    question_skip_button,
)
from core.services.questions import group_options, is_group
from core.services.slots import slot_id, slot_label

# The times a participant can choose from. Everything else derives from these.
AVAILABLE_SLOTS = [slot_id(value) for value in SLOT_TIMES]


def _option_rows(buttons):
    """Short labels share a row so a 1–5 scale reads horizontally; anything
    longer gets a row to itself."""
    rows = []
    row_is_short = False

    for button in buttons:
        short = len(button.text) <= SHORT_OPTION_LENGTH
        can_share = short and row_is_short and rows and len(rows[-1]) < OPTIONS_PER_ROW

        if can_share:
            rows[-1].append(button)
        else:
            rows.append([button])
            row_is_short = short

    return rows


def build_question_keyboard(question, answer, group=None):
    """Top level when `group` is None, otherwise that group's choices.

    Which level is showing lives entirely in the callback data, so opening a
    group is just a keyboard swap on the same message — nothing to store and
    nothing to lose on a restart.
    """
    options = question.option_list
    skip = InlineKeyboardButton(
        question_skip_button, callback_data=callbacks.encode(callbacks.SKIP, answer.id)
    )

    if not options:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                question_answer_button,
                callback_data=callbacks.encode(callbacks.ANSWER, answer.id),
            )],
            [skip],
        ])

    if group is None:
        buttons = []
        for index, entry in enumerate(options):
            if is_group(entry):
                # A group with a label but no choices would open an empty
                # screen, so it simply isn't offered.
                if group_options(entry):
                    buttons.append(InlineKeyboardButton(
                        entry[0],
                        callback_data=callbacks.encode(callbacks.GROUP, answer.id, index),
                    ))
            else:
                buttons.append(InlineKeyboardButton(
                    entry,
                    callback_data=callbacks.encode(callbacks.OPTION, answer.id, index),
                ))

        keyboard = _option_rows(buttons)

        # Carries the same callback as [Відповісти] on an open question: it
        # prompts and leaves the row unresolved, so the ordinary text handler
        # picks the reply up. Top level only — Повернутись is one tap away.
        if question.allows_free_text:
            keyboard.append([InlineKeyboardButton(
                question_free_text_button,
                callback_data=callbacks.encode(callbacks.ANSWER, answer.id),
            )])
    else:
        keyboard = _option_rows([
            InlineKeyboardButton(
                choice,
                callback_data=callbacks.encode(callbacks.OPTION, answer.id, group, index),
            )
            for index, choice in enumerate(group_options(options[group]))
        ])
        keyboard.append([InlineKeyboardButton(
            question_back_button,
            callback_data=callbacks.encode(callbacks.GROUP, answer.id, callbacks.BACK),
        )])

    keyboard.append([skip])

    return InlineKeyboardMarkup(keyboard)


def build_slots_keyboard(selected, action, confirm_label):
    """`action` namespaces the callback data so onboarding and the menu editor
    don't claim each other's taps."""
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if slot in selected else ''}{slot_label(slot)}",
            callback_data=callbacks.encode(action, slot),
        )]
        for slot in AVAILABLE_SLOTS
    ]
    keyboard.append([InlineKeyboardButton(
        confirm_label, callback_data=callbacks.encode(action, callbacks.CONTINUE),
    )])

    return InlineKeyboardMarkup(keyboard)
