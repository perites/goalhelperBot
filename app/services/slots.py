"""Message-time slots, shared by onboarding and the menu editor."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import CONTINUE_ACTION, SLOT_TIMES
from app.models import UserTime
from app.texts import slot_labels

# Times come from config, labels from texts — joined here so callers see one
# dict. The two must share keys; tests assert that.
SLOTS = {
    key: {"time": slot_time, "label": slot_labels[key]}
    for key, slot_time in SLOT_TIMES.items()
}


def build_slots_keyboard(selected, prefix, confirm_label):
    """`prefix` namespaces the callback data so onboarding and the menu
    editor don't claim each other's taps."""
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if key in selected else ''}{slot['label']}",
            callback_data=f"{prefix}:{key}",
        )]
        for key, slot in SLOTS.items()
    ]
    keyboard.append(
        [InlineKeyboardButton(confirm_label, callback_data=f"{prefix}:{CONTINUE_ACTION}")]
    )

    return InlineKeyboardMarkup(keyboard)


def toggle_slot(selected, key):
    selected.symmetric_difference_update({key})

    return selected


def slot_key(callback_data):
    return callback_data.split(":")[1]


def saved_slots(user):
    """The slot keys currently persisted for this user."""
    stored = {slot.time for slot in user.times}

    return {key for key, slot in SLOTS.items() if slot["time"] in stored}


def save_slots(user_id, keys):
    UserTime.delete().where(UserTime.user == user_id).execute()
    UserTime.bulk_create([
        UserTime(user=user_id, time=SLOTS[key]["time"])
        for key in keys
    ])


def format_slots(keys):
    """Single display format for chosen slots, used by onboarding's summary,
    the menu's info screen, and the save confirmation."""
    return ", ".join(
        f"{slot['label']} ({slot['time'].strftime('%H:%M')})"
        for key, slot in SLOTS.items()
        if key in keys
    )
