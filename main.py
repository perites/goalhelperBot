"""Entry point: wiring and startup."""
import os

from dotenv import load_dotenv

load_dotenv()

from telegram.ext import Application

from app.handlers.answers import (
    answer_button_handler,
    answer_text_handler,
    ask_command_handler,
    option_button_handler,
    skip_button_handler,
)
from app.handlers.errors import error_handler
from app.handlers.menu import (
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
from app.handlers.onboarding import onboarding_conv_handler
from app.handlers.start import start_handler
from app.models import initialize_database
from app.services.cohort import seed_default_cohort
from app.services.questions import seed_questions
from app.services.scheduler import schedule


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
    app.add_handler(answer_text_handler)

    app.add_error_handler(error_handler)


def main():
    # Kept out of module scope so importing this module has no side effects
    # on the database — tests import it freely.
    initialize_database()
    seed_questions()
    seed_default_cohort()

    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()

    register_handlers(app)
    schedule(app)

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
