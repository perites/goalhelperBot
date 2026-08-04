"""All tunable settings for the bot, in one place.

Everything else imports this module, so it must not import anything back —
with the single exception of `bot.enums`, which is itself dependency-free and
so can't complete a cycle.
"""
import os
from datetime import time


# --- Storage ---------------------------------------------------------------

# Where the database and logs live. Defaults to the working directory, which
# is what you want when running locally or under systemd; containers set
# DATA_DIR to a mounted volume so the data survives a rebuild.
DATA_DIR = os.getenv("DATA_DIR", ".")

DATABASE_NAME = os.path.join(DATA_DIR, "goalbot.db")

# --- Time ------------------------------------------------------------------

# Everything runs on this timezone regardless of where the server is.
TIMEZONE = "Europe/Kyiv"

# --- Personal cycle --------------------------------------------------------

# A pause expires on its own after this many days, even if never resumed.
# Paused days don't count toward the cycle, so the finish line moves out.
PAUSE_DURATION_DAYS = 3

# --- Scheduler -------------------------------------------------------------

TICK_INTERVAL_HOURS = 1

# Hour of the daily housekeeping pass: expire pauses, close finished cycles,
# end the cohort. Runs in addition to that hour's question sending.
SWEEP_HOUR = 6

# --- Message slots ---------------------------------------------------------

# Keys must match `slot_labels` in messages_texts.py.
# The times a participant can pick from. A slot is identified by its own time
# ("09:00"), so this is the only place that decides what's on offer — adding
# time(7, 0) here needs no other change anywhere.
#
# Delivery happens on the hour: the scheduler ticks hourly and matches on the
# hour alone, so a time with minutes would fire at the top of its hour.

# purely for UI picks
SLOT_TIMES = [
    time(9, 0),
    time(13, 0),
    time(16, 0),
    time(19, 0),
]

# Which emoji labels a slot, since there's no stored name to carry that.
SLOT_MORNING_UNTIL_HOUR = 12
SLOT_EVENING_FROM_HOUR = 17

# --- Questions -------------------------------------------------------------

# Gap left between the `order` values of a question's follow-ups, so another
# can be slotted in later without renumbering.
QUESTION_ORDER_STEP = 10

# How many of the most frequent emotions the statistics screen lists.
TOP_EMOTIONS_SHOWN = 3

# --- Contacts --------------------------------------------------------------

KSENIA_TELEGRAM = "@kryskaks"

# --- Logging ---------------------------------------------------------------

LOG_DIR = os.path.join(DATA_DIR, "logs")
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

# Returns from a group of options to the top level of a question's keyboard.
BACK_ACTION = "back"

# Options shorter than this share a row, so a 1–5 scale reads as a scale
# instead of five stacked buttons. Longer labels still get a row each.
SHORT_OPTION_LENGTH = 12
OPTIONS_PER_ROW = 5
