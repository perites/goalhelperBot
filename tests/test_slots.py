"""Time-slot persistence and the shared toggle keyboard."""
"""Time-slot persistence and the shared toggle keyboard."""
from bot import callbacks, settings
from bot.keyboards import AVAILABLE_SLOTS, build_slots_keyboard
from bot.texts import main_menu_buttons
from core.models import UserTime
from core.services.slots import (
    format_slots, save_slots, saved_slots, slot_id, toggle_slot,
)


def test_offered_slots_derive_from_settings():
    assert AVAILABLE_SLOTS == [slot_id(value) for value in settings.SLOT_TIMES]


def test_save_and_read_back_round_trips(make_user):
    user = make_user()
    save_slots(user.telegram_id, {"09:00", "19:00"})

    assert saved_slots(user) == {"09:00", "19:00"}


def test_saving_replaces_rather_than_appends(make_user):
    user = make_user()
    save_slots(user.telegram_id, {"09:00", "19:00"})
    save_slots(user.telegram_id, {"13:00"})

    assert UserTime.select().where(UserTime.user == user).count() == 1
    assert saved_slots(user) == {"13:00"}


def test_saving_nothing_clears_all_slots(make_user):
    user = make_user()
    save_slots(user.telegram_id, {"09:00"})
    save_slots(user.telegram_id, set())

    assert saved_slots(user) == set()


def test_toggle_flips_membership():
    selected = set()

    toggle_slot(selected, "09:00")
    assert selected == {"09:00"}

    toggle_slot(selected, "13:00")
    toggle_slot(selected, "09:00")
    assert selected == {"13:00"}


def test_keyboard_marks_only_selected_slots():
    keyboard = build_slots_keyboard({"09:00"}, callbacks.TIME_SLOT, "Далі")
    labels = [button.text for row in keyboard.inline_keyboard for button in row]

    assert labels[0].startswith("✅")
    assert not labels[1].startswith("✅")
    assert labels[-1] == "Далі"


def test_keyboard_namespaces_are_disjoint():
    onboarding = build_slots_keyboard(set(), callbacks.TIME_SLOT, "Далі")
    editor = build_slots_keyboard(set(), callbacks.EDIT_TIME, "Зберегти")

    onboarding_data = {b.callback_data for row in onboarding.inline_keyboard for b in row}
    editor_data = {b.callback_data for row in editor.inline_keyboard for b in row}

    assert not onboarding_data & editor_data


def test_slot_id_survives_the_round_trip_through_a_button():
    """The id contains the separator itself ("09:00"), so it has to come back
    whole rather than split into two parts."""
    keyboard = build_slots_keyboard(set(), callbacks.TIME_SLOT, "Далі")
    first = keyboard.inline_keyboard[0][0].callback_data

    assert callbacks.payload(first) in AVAILABLE_SLOTS
    assert keyboard.inline_keyboard[-1][0].callback_data.endswith(callbacks.CONTINUE)


def test_format_slots_is_stable_regardless_of_set_order():
    assert format_slots({"19:00", "09:00"}) == format_slots({"09:00", "19:00"})


def test_menu_button_labels_are_all_registered():
    # answer_text_handler excludes exactly this list; a missing entry would
    # mean a menu tap gets saved as a question answer.
    from bot.handlers.menu import main_menu_keyboard

    rendered = {b.text for row in main_menu_keyboard().keyboard for b in row}

    assert rendered == set(main_menu_buttons)
