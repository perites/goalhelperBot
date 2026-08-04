"""Settings both front ends read.

Telegram-only knobs — which times are offered, how a keyboard is laid out, how
callback data is namespaced — live in `bot/settings.py` instead. The split is
the same one that separates this package from that one: if the admin panel has
no use for it, it does not belong here.

This module imports nothing from the project, so nothing can import it back.
"""
import os


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

# --- Message slots ---------------------------------------------------------

# Which emoji labels a slot, since there's no stored name to carry that. Shared
# rather than Telegram-only: the panel shows a participant's chosen times the
# same way the bot does, so the two must agree on what "morning" means.
SLOT_MORNING_UNTIL_HOUR = 12
SLOT_EVENING_FROM_HOUR = 17

# --- Questions -------------------------------------------------------------

# Gap left between the `order` values of a question's follow-ups, so another
# can be slotted in later without renumbering.
QUESTION_ORDER_STEP = 10

# How many of the most frequent emotions the statistics screen lists.
TOP_EMOTIONS_SHOWN = 3

# --- Logging ---------------------------------------------------------------

LOG_DIR = os.path.join(DATA_DIR, "logs")
LOG_FILE_NAME = "bot.log"

# The panel runs as its own process and must not write the bot's file: a
# TimedRotatingFileHandler renames the file it owns at midnight, and two
# processes doing that to one path lose records. Both files live in LOG_DIR and
# both are listed on the panel's logs page.
ADMIN_LOG_FILE_NAME = "admin.log"

# Everything at this level and above reaches the file and the console.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
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


def admin_chat_ids():
    """Read at call time so an unset value never blocks module import."""
    raw = os.getenv("ADMIN_CHAT_IDS", "")

    return [int(part) for part in raw.replace(" ", "").split(",") if part]
