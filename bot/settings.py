"""Settings only the Telegram bot has a use for.

Anything the admin panel also reads belongs in `core/settings.py`.
"""
from datetime import time


# --- Scheduler -------------------------------------------------------------

TICK_INTERVAL_HOURS = 1

# Hour of the daily housekeeping pass: expire pauses, close finished cycles,
# end the cohort. Runs in addition to that hour's question sending.
SWEEP_HOUR = 6

# --- Message slots ---------------------------------------------------------

# The times a participant can pick from. A slot is identified by its own time
# ("09:00"), so this is the only place that decides what's on offer — adding
# time(7, 0) here needs no other change anywhere.
#
# Delivery happens on the hour: the scheduler ticks hourly and matches on the
# hour alone, so a time with minutes would fire at the top of its hour.
SLOT_TIMES = [
    time(9, 0),
    time(13, 0),
    time(16, 0),
    time(19, 0),
]

# --- Keyboards -------------------------------------------------------------

# Options shorter than this share a row, so a 1–5 scale reads as a scale
# instead of five stacked buttons. Longer labels still get a row each.
SHORT_OPTION_LENGTH = 12
OPTIONS_PER_ROW = 5

# --- Contacts --------------------------------------------------------------

KSENIA_TELEGRAM = "@kryskaks"
