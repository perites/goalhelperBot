"""Time-slot picking, shared by onboarding and the menu editor."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import SLOT_TIMES, CONTINUE_ACTION as CONTINUE
from database import UserTime
from messages_texts import slot_labels

# Times come from config, labels from messages_texts — joined here so callers
# still see one dict.
TIME_SLOTS_CHOICES = {
    key: {"time": slot_time, "label": slot_labels[key]}
    for key, slot_time in SLOT_TIMES.items()
}


def build_keyboard(selected, prefix, confirm_label):
    """`prefix` namespaces the callback data so onboarding and the menu
    editor don't claim each other's taps."""
    keyboard = [
        [InlineKeyboardButton(
            f"{'✅ ' if key in selected else ''}{slot['label']}",
            callback_data=f"{prefix}:{key}",
        )]
        for key, slot in TIME_SLOTS_CHOICES.items()
    ]
    keyboard.append([InlineKeyboardButton(confirm_label, callback_data=f"{prefix}:{CONTINUE}")])

    return InlineKeyboardMarkup(keyboard)


def toggle(selected, key):
    selected.symmetric_difference_update({key})

    return selected


def slot_key(callback_data):
    return callback_data.split(":")[1]


def saved_slots(user):
    """The slot keys currently persisted for this user."""
    stored = {slot.time for slot in user.times}

    return {key for key, slot in TIME_SLOTS_CHOICES.items() if slot["time"] in stored}


def save_slots(user_id, keys):
    UserTime.delete().where(UserTime.user == user_id).execute()
    UserTime.bulk_create([
        UserTime(user=user_id, time=TIME_SLOTS_CHOICES[key]["time"])
        for key in keys
    ])


def format_slots(keys):
    return ", ".join(
        TIME_SLOTS_CHOICES[key]["label"] for key in TIME_SLOTS_CHOICES if key in keys
    )
