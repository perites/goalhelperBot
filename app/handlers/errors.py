import html
import os
import traceback


def admin_chat_id():
    """Read at call time, not import time — an unset value shouldn't stop the
    module being imported."""
    raw = os.getenv("ADMIN_CHAT_ID")

    return int(raw) if raw else None


async def error_handler(update, context):
    chat_id = admin_chat_id()
    if chat_id is None:
        return

    # Get full traceback
    tb = "".join(traceback.format_exception(
        type(context.error), context.error, context.error.__traceback__
    ))

    # Build message
    message = (
        f"⚠️ <b>Bot Error</b>\n\n"
        f"<b>Error:</b> {html.escape(str(context.error))}\n\n"
        f"<b>Traceback:</b>\n<pre>{html.escape(tb[-3000:])}</pre>"
    )

    # Add update info if available
    if update:
        message += f"\n\n<b>Update:</b> <pre>{html.escape(str(update))[:500]}</pre>"

    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML"
    )
