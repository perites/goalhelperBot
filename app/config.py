"""All tunable settings for the bot, in one place.

This module must not import anything else from the project — everything else
imports it, so keeping it dependency-free avoids circular imports.
"""
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

# --- Callback data prefixes ------------------------------------------------

# These namespace inline-button taps so the onboarding conversation and the
# menu editor don't claim each other's callbacks.
TIME_SLOT_PREFIX = "time_slot"
EDIT_TIME_PREFIX = "edit_time"
CONTINUE_ACTION = "continue"
