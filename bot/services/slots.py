"""Message-time slots, shared by onboarding and the menu editor.

A slot is identified by its own time, formatted "HH:MM" — not by a name like
"morning". That means the offered set below is just a list of times: adding
one is a one-line change, and nothing downstream needs a matching label,
enum, or key. Zero-padding also makes the ids sort chronologically as plain
strings, which is what the distribution below relies on.
"""
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import (
    CONTINUE_ACTION,
    DEFAULT_QUESTIONS_PER_DAY,
    SLOT_EVENING_FROM_HOUR,
    SLOT_TIMES,
    SLOT_MORNING_UNTIL_HOUR,
)
from bot.models import UserTime

SLOT_FORMAT = "%H:%M"


def slot_id(slot_time):
    """The identifier for a time: 09:00, 13:00, 19:00."""
    return slot_time.strftime(SLOT_FORMAT)


def slot_time(slot):
    """Back to a time object, for storing on UserTime."""
    return datetime.strptime(slot, SLOT_FORMAT).time()


# The times a participant can choose from. Everything else derives from these.
AVAILABLE_SLOTS = [slot_id(value) for value in SLOT_TIMES]


def slot_label(slot):
    """Time of day conveyed by an emoji rather than a stored name, so any hour
    can be offered without inventing a word for it."""
    hour = slot_time(slot).hour

    if hour < SLOT_MORNING_UNTIL_HOUR:
        icon = "🌅"
    elif hour < SLOT_EVENING_FROM_HOUR:
        icon = "🌤"
    else:
        icon = "🌙"

    return f"{icon} {slot}"


def build_slots_keyboard(selected, prefix, confirm_label):
    """`prefix` namespaces the callback data so onboarding and the menu
    editor don't claim each other's taps."""
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if slot in selected else ''}{slot_label(slot)}",
            callback_data=f"{prefix}:{slot}",
        )]
        for slot in AVAILABLE_SLOTS
    ]
    keyboard.append(
        [InlineKeyboardButton(confirm_label, callback_data=f"{prefix}:{CONTINUE_ACTION}")]
    )

    return InlineKeyboardMarkup(keyboard)


def toggle_slot(selected, slot):
    selected.symmetric_difference_update({slot})

    return selected


def slot_from_callback(callback_data):
    """The slot id out of "edit_time:09:00" — split once, since the id itself
    contains a colon."""
    return callback_data.split(":", 1)[1]


def saved_slots(user):
    """The slots currently persisted for this user.

    Read straight off UserTime, so a time that isn't in AVAILABLE_SLOTS any
    more still shows up instead of being silently dropped.
    """
    return {slot_id(row.time) for row in user.times}


def save_slots(user_id, slots):
    UserTime.delete().where(UserTime.user == user_id).execute()
    UserTime.bulk_create([
        UserTime(user=user_id, time=slot_time(slot))
        for slot in slots
    ])


def slots_in_order(slots):
    """Chronological. Zero-padded HH:MM sorts correctly as a string."""
    return sorted(slots)


def questions_per_slot(user_slots, total=None):
    """Spread the day's questions across the slots someone picked.

    Remainders go to the later slots, so the day builds rather than
    front-loads. Every chosen slot gets at least one — a slot you asked for
    should never be silent — which is why asking for fewer questions than you
    have slots raises the daily total instead of quieting one.
    """
    ordered = slots_in_order(user_slots)
    if not ordered:
        return {}

    total = DEFAULT_QUESTIONS_PER_DAY if total is None else total
    base, remainder = divmod(total, len(ordered))

    # Fewer questions than slots: one each, and the remainder is meaningless.
    if base == 0:
        return {slot: 1 for slot in ordered}

    counts = {slot: base for slot in ordered}
    for slot in ordered[len(ordered) - remainder:]:
        counts[slot] += 1

    return counts


def format_slots(slots):
    """Single display format for chosen slots, used by onboarding's summary,
    the menu's info screen, and the save confirmation."""
    return ", ".join(slot_label(slot) for slot in slots_in_order(slots))
