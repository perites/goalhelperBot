"""All tunable settings for the bot, in one place.

This module must not import anything else from the project — everything else
imports it, so keeping it dependency-free avoids circular imports.
"""
import os
from datetime import time

# --- Storage ---------------------------------------------------------------

DATABASE_NAME = "goalbot.db"

# --- Time ------------------------------------------------------------------

# Everything runs on this timezone regardless of where the server is.
TIMEZONE = "Europe/Kyiv"

# --- Personal cycle --------------------------------------------------------

CYCLE_LENGTH_DAYS = 30

# A pause expires on its own after this many days, even if never resumed.
# Paused days don't count toward the cycle, so the finish line moves out.
PAUSE_DURATION_DAYS = 3

# --- Cohort ----------------------------------------------------------------

DEFAULT_MAX_PEOPLE = 10
DEFAULT_ENROLLMENT_WINDOW_DAYS = 14

# --- Scheduler -------------------------------------------------------------

TICK_INTERVAL_HOURS = 1

# Hour of the daily housekeeping pass: expire pauses, close finished cycles,
# end the cohort. Runs in addition to that hour's question sending.
SWEEP_HOUR = 6

# --- Message slots ---------------------------------------------------------

# Keys must match `slot_labels` in messages_texts.py.
SLOT_TIMES = {
    "morning": time(9, 0),
    "noon": time(13, 0),
    "evening": time(19, 0),
}

# --- Questions -------------------------------------------------------------

# Gap left between question `order` values so new ones can be slotted in
# later without renumbering the whole bank.
QUESTION_ORDER_STEP = 10

# How many of the most frequent emotions the statistics screen lists.
TOP_EMOTIONS_SHOWN = 3

# --- Contacts --------------------------------------------------------------

KSENIA_TELEGRAM = "@kryskaks"

# --- Logging ---------------------------------------------------------------

LOG_DIR = "logs"
LOG_FILE_NAME = "bot.log"

# Everything at this level and above reaches the file and the console.
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# The log rotates at midnight; this many days are kept.
LOG_RETENTION_DAYS = 30

# --- Admin alerts ----------------------------------------------------------

# Records at this level and above are also delivered to the admin chats.
ALERT_LEVEL = "WARNING"

# An identical alert is sent at most once per window; repeats inside it are
# counted and reported with the next one that gets through.
ALERT_DEDUPE_WINDOW_SECONDS = 300

# Hard ceiling on delivery, so a tight failure loop can't flood a phone.
ALERT_MAX_PER_MINUTE = 5

# Never log the text of an answer, an intention, or a name — participants
# consented to those being stored for their own reflection, not for ops.
# Helpers below describe content without reproducing it.
LOG_TEXT_PREVIEW = False


def admin_chat_ids():
    """Read at call time so an unset value never blocks module import."""
    raw = os.getenv("ADMIN_CHAT_IDS", "")

    return [int(part) for part in raw.replace(" ", "").split(",") if part]

# --- Callback data prefixes ------------------------------------------------

# These namespace inline-button taps so the onboarding conversation and the
# menu editor don't claim each other's callbacks.
TIME_SLOT_PREFIX = "time_slot"
EDIT_TIME_PREFIX = "edit_time"
CONTINUE_ACTION = "continue"
