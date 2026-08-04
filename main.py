"""Entry point: wiring and startup."""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from telegram.ext import Application, PicklePersistence

from core.settings import DATA_DIR, admin_chat_ids
from core.logs import alert_handler, configure_logging, get_logger

from bot.handlers.answers import (
    answer_button_handler,
    answer_text_handler,
    ask_command_handler,
    group_button_handler,
    option_button_handler,
    skip_button_handler,
)
from bot.handlers.errors import error_handler
from bot.handlers.menu import (
    contacts_handler,
    edit_time_save_handler,
    edit_time_toggle_handler,
    edit_times_handler,
    finish_confirm_handler,
    finish_handler,
    my_info_handler,
    pause_confirm_handler,
    pause_handler,
    stats_handler,
)
from bot.handlers.onboarding import onboarding_conv_handler
from bot.handlers.start import start_handler
from core.models import initialize_database
from bot.scheduler import schedule

logger = get_logger(__name__)

PERSISTENCE_PATH = os.path.join(DATA_DIR, "ptb_state.pickle")


def build_persistence():
    """Conversation state and user_data, kept across restarts.

    Answering a question already survives a restart, because the pending Answer
    row in the database is the state. Onboarding is the exception, and it fails
    badly: the buttons for consent, category, confirmation and the time slots
    are registered *only inside* the conversation, so once its state is gone
    those taps match no handler anywhere in the application and are discarded
    in silence. The participant taps «✅ Погоджуюсь», nothing happens, and
    nothing tells them that /start would put it right. With Restart=always in
    the unit file and a 30-day pilot, that is a question of when rather than if.

    It carries `user_data` too, so a half-made slot selection is still there
    afterwards instead of resetting to an empty set on the next tap.

    The file holds names and intentions typed during onboarding — the same kind
    of data as the database, kept beside it and needing the same care.
    """
    return PicklePersistence(filepath=PERSISTENCE_PATH)


def register_handlers(app):
    """Order matters twice over: the onboarding conversation must claim its
    own text input before the menu, and `answer_text_handler` catches all
    remaining text so it has to come last."""
    app.add_handler(start_handler)
    app.add_handler(onboarding_conv_handler)
    app.add_handler(ask_command_handler)

    app.add_handler(my_info_handler)
    app.add_handler(contacts_handler)
    app.add_handler(stats_handler)
    app.add_handler(edit_times_handler)
    app.add_handler(pause_handler)
    app.add_handler(finish_handler)

    app.add_handler(pause_confirm_handler)
    app.add_handler(finish_confirm_handler)

    # Save must be matched before the toggle pattern, which is a prefix of it.
    app.add_handler(edit_time_save_handler)
    app.add_handler(edit_time_toggle_handler)

    app.add_handler(answer_button_handler)
    app.add_handler(skip_button_handler)
    app.add_handler(option_button_handler)
    app.add_handler(group_button_handler)
    app.add_handler(answer_text_handler)

    app.add_error_handler(error_handler)

    logger.info("Registered %s handler group(s)", len(app.handlers[0]))


async def on_startup(app):
    """Runs once the event loop exists, which the alert handler needs before
    it can schedule sends."""
    alert_handler.bind(app.bot, asyncio.get_running_loop())

    recipients = admin_chat_ids()
    if recipients:
        logger.info("Admin alerts enabled for %s chat(s)", len(recipients))
    else:
        logger.warning("ADMIN_CHAT_IDS is unset — no one will receive alerts")

    me = await app.bot.get_me()
    logger.info("Connected to Telegram as @%s (id=%s)", me.username, me.id)


async def on_shutdown(app):
    logger.info("Bot stopping")


def main():
    configure_logging()
    logger.info("Starting up")

    # Kept out of module scope so importing this module has no side effects
    # on the database — tests import it freely. Creates the tables if the file
    # is new; it never puts anything in them. Content comes from the admin
    # panel, or from `python -m samples.seed` for a demo database.
    initialize_database()

    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.critical("BOT_TOKEN is not set; cannot start")
        raise SystemExit(1)

    app = (
        Application.builder()
        .token(token)
        .persistence(build_persistence())
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    register_handlers(app)
    schedule(app)

    app.run_polling()


if __name__ == "__main__":
    main()
