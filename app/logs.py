"""Logging: a rotating file, the console, and Telegram alerts for admins.

Nothing here ever records the text of an answer, an intention, or a name.
Participants consented to those being stored for their own reflection, not for
operations — so log calls describe content (length, ids) instead of quoting it.
"""
import asyncio
import html
import logging
import logging.handlers
import sys
import time
from collections import deque
from pathlib import Path

from app.config import (
    ALERT_DEDUPE_WINDOW_SECONDS,
    ALERT_LEVEL,
    ALERT_MAX_PER_MINUTE,
    LOG_DATE_FORMAT,
    LOG_DIR,
    LOG_FILE_NAME,
    LOG_FORMAT,
    LOG_LEVEL,
    LOG_RETENTION_DAYS,
    admin_chat_ids,
)

ROOT_LOGGER_NAME = "app"

# Telegram caps messages at 4096 characters.
MAX_ALERT_LENGTH = 3500


def get_logger(name):
    """Logger for a module, namespaced under the app root."""
    suffix = name.removeprefix("app.") if name.startswith("app.") else name

    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{suffix}")


def describe(text):
    """Refer to user content without reproducing it."""
    if text is None:
        return "none"

    return f"{len(text)} chars"


class TelegramAlertHandler(logging.Handler):
    """Forwards WARNING and above to the admin chats.

    Sending is scheduled on the bot's event loop rather than awaited, so
    logging never blocks. Identical alerts are collapsed inside a window and
    the whole handler is rate limited, so a failure loop can't flood a phone.
    """

    def __init__(self, level=logging.WARNING):
        super().__init__(level)
        self._bot = None
        self._loop = None
        self._seen = {}
        self._sent_at = deque()
        self._dropped = 0

    def bind(self, bot, loop):
        """Called once the event loop is running (from post_init)."""
        self._bot = bot
        self._loop = loop

    @staticmethod
    def _fingerprint(record):
        exc_type = record.exc_info[0].__name__ if record.exc_info else ""

        return f"{record.levelno}:{record.name}:{record.getMessage()}:{exc_type}"

    def _prune(self, now):
        expiry = ALERT_DEDUPE_WINDOW_SECONDS * 2
        stale = [key for key, seen in self._seen.items() if now - seen["last"] > expiry]

        for key in stale:
            del self._seen[key]

    def _suppressed_count(self, record, now):
        """None if this alert should be swallowed, otherwise how many
        identical ones were suppressed since the last delivery."""
        fingerprint = self._fingerprint(record)
        seen = self._seen.get(fingerprint)

        if seen is not None and now - seen["last"] < ALERT_DEDUPE_WINDOW_SECONDS:
            seen["suppressed"] += 1
            return None

        suppressed = seen["suppressed"] if seen else 0
        self._seen[fingerprint] = {"last": now, "suppressed": 0}

        return suppressed

    def _within_rate_limit(self, now):
        while self._sent_at and now - self._sent_at[0] > 60:
            self._sent_at.popleft()

        if len(self._sent_at) >= ALERT_MAX_PER_MINUTE:
            self._dropped += 1
            return False

        self._sent_at.append(now)

        return True

    def _format_alert(self, record, suppressed):
        icon = "🛑" if record.levelno >= logging.ERROR else "⚠️"
        lines = [
            f"{icon} <b>{record.levelname}</b> · <code>{html.escape(record.name)}</code>",
            "",
            html.escape(record.getMessage()),
        ]

        if record.exc_info:
            trace = self.format(record).split("\n", 1)
            if len(trace) > 1:
                lines += ["", f"<pre>{html.escape(trace[1][-1500:])}</pre>"]

        if suppressed:
            lines += ["", f"<i>(+{suppressed} identical suppressed)</i>"]

        if self._dropped:
            lines += ["", f"<i>({self._dropped} alerts dropped by rate limit)</i>"]
            self._dropped = 0

        return "\n".join(lines)[:MAX_ALERT_LENGTH]

    async def _deliver(self, text):
        for chat_id in admin_chat_ids():
            try:
                await self._bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except Exception as error:  # noqa: BLE001
                # Deliberately not logged: routing a send failure back through
                # logging would call this handler again, forever.
                sys.stderr.write(f"alert delivery to {chat_id} failed: {error!r}\n")

    def emit(self, record):
        if self._bot is None or self._loop is None or not self._loop.is_running():
            return

        if not admin_chat_ids():
            return

        try:
            now = time.monotonic()
            self._prune(now)

            suppressed = self._suppressed_count(record, now)
            if suppressed is None:
                return

            if not self._within_rate_limit(now):
                return

            text = self._format_alert(record, suppressed)
            asyncio.run_coroutine_threadsafe(self._deliver(text), self._loop)
        except Exception:  # noqa: BLE001
            self.handleError(record)


alert_handler = TelegramAlertHandler(level=getattr(logging, ALERT_LEVEL))


def configure_logging():
    """Wire up file, console, and alert handlers. Safe to call twice."""
    root = logging.getLogger(ROOT_LOGGER_NAME)

    if root.handlers:
        return root

    root.setLevel(getattr(logging, LOG_LEVEL))
    root.propagate = False

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        when="midnight",
        backupCount=LOG_RETENTION_DAYS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    alert_handler.setFormatter(formatter)

    root.addHandler(file_handler)
    root.addHandler(console)
    root.addHandler(alert_handler)

    # httpx logs every Telegram API call at INFO, which drowns everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    return root
