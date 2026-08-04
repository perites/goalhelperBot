"""Onboarding survives a restart.

Answering a question already did — the pending Answer row in the database is
the state. Onboarding was the exception, and it failed silently: every button
in it is registered *only inside* the conversation, so once that state was gone
the taps matched no handler anywhere and were discarded without a word.
"""
from telegram.ext import PicklePersistence

from bot.handlers.onboarding import CONSENT, onboarding_conv_handler


def test_the_onboarding_conversation_is_persistent():
    assert onboarding_conv_handler.persistent is True


def test_its_name_is_the_key_the_state_is_filed_under():
    """Changing this abandons whatever is already stored, so it is worth
    noticing when someone does."""
    assert onboarding_conv_handler.name == "onboarding"


async def test_conversation_state_survives_a_new_process(tmp_path):
    path = tmp_path / "ptb_state.pickle"

    before = PicklePersistence(filepath=path)
    await before.update_conversation("onboarding", (7, 7), CONSENT)
    await before.flush()

    after = PicklePersistence(filepath=path)

    assert (await after.get_conversations("onboarding"))[(7, 7)] == CONSENT


async def test_a_half_made_slot_selection_survives(tmp_path):
    """`user_data` carries the toggles in the time editor. Losing it meant the
    next tap started from an empty set, and saving then wrote just that one
    slot over the participant's real choice."""
    path = tmp_path / "ptb_state.pickle"

    before = PicklePersistence(filepath=path)
    await before.update_user_data(7, {"edit_time_slots": {"09:00", "19:00"}})
    await before.flush()

    after = PicklePersistence(filepath=path)
    restored = await after.get_user_data()

    assert restored[7]["edit_time_slots"] == {"09:00", "19:00"}
