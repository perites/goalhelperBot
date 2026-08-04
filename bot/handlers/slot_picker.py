"""The message-time picker, which onboarding and the menu editor both use.

The same four steps in both places — draw it, flip a slot and redraw, refuse an
empty selection, save — differing only in which callback action namespaces the
taps, what the confirm button says, and where the answer ends up. They were
written out twice, which is how the two came to disagree about whether a
half-made selection survives a restart.
"""
from bot import callbacks
from bot.keyboards import build_slots_keyboard
from bot.texts import slots_prompt_message
from core.services.slots import toggle_slot


async def show(message, selected, action, confirm_label):
    """Open the picker on a fresh message."""
    await message.reply_text(
        slots_prompt_message,
        reply_markup=build_slots_keyboard(selected, action, confirm_label),
    )


async def toggle(query, selected, action, confirm_label):
    """Flip the slot this tap names, then redraw in place.

    Only the keyboard changes, so there is no state here beyond the set the
    caller passes in — which is the set that gets saved.
    """
    toggle_slot(selected, callbacks.payload(query.data))

    await query.edit_message_reply_markup(
        reply_markup=build_slots_keyboard(selected, action, confirm_label),
    )

    return selected
