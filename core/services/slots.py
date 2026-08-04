"""Message-time slots.

A slot is identified by its own time, formatted "HH:MM" — not by a name like
"morning". That means the set on offer is just a list of times: adding one is a
one-line change, and nothing downstream needs a matching label, enum, or key.
Zero-padding also makes the ids sort chronologically as plain strings, which is
what the distribution below relies on.

Which times are offered, and the keyboard for picking them, are the bot's
business — see `bot/settings.py` and `bot/keyboards.py`. What a slot *is*, and
how a day's questions divide across the ones somebody chose, is shared: the
panel shows the same times back.
"""
from datetime import datetime

from core.settings import SLOT_EVENING_FROM_HOUR, SLOT_MORNING_UNTIL_HOUR
from core.models import UserTime

SLOT_FORMAT = "%H:%M"


def slot_id(slot_time):
    """The identifier for a time: 09:00, 13:00, 19:00."""
    return slot_time.strftime(SLOT_FORMAT)


def slot_time(slot):
    """Back to a time object, for storing on UserTime."""
    return datetime.strptime(slot, SLOT_FORMAT).time()


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


def toggle_slot(selected, slot):
    selected.symmetric_difference_update({slot})

    return selected


def saved_slots(user):
    """The slots currently persisted for this user.

    Read straight off UserTime, so a time that is no longer on offer still
    shows up instead of being silently dropped.
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


def questions_per_slot(user_slots, total):
    """Spread the day's questions across the slots someone picked.

    Remainders go to the later slots, so the day builds rather than
    front-loads. Every chosen slot gets at least one — a slot you asked for
    should never be silent — which is why asking for fewer questions than you
    have slots raises the daily total instead of quieting one.
    """
    ordered = slots_in_order(user_slots)
    if not ordered:
        return {}

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
    the menu's info screen, the save confirmation, and the admin panel."""
    return ", ".join(slot_label(slot) for slot in slots_in_order(slots))
