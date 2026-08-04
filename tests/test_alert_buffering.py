"""Alerts raised before there is a bot to send them with.

`configure_logging` runs first, then the database is opened and migrated, and
only then does `post_init` hand the alert handler a bot. Anything that went
wrong in that window used to be dropped on the floor — which is the window
where most startup problems live.
"""
import asyncio
import logging

import pytest

from core.logs import MAX_PENDING_ALERTS, TelegramAlertHandler


class AlertBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})


@pytest.fixture
def handler(monkeypatch):
    """A handler on its own logger, deliberately not yet bound to a bot."""
    monkeypatch.setenv("ADMIN_CHAT_IDS", "111")

    alerts = TelegramAlertHandler(level=logging.WARNING)
    alerts.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("goalbot.test_buffering")
    logger.handlers = [alerts]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    yield logger, alerts

    logger.handlers = []


async def test_an_early_alert_is_delivered_once_the_bot_arrives(handler):
    logger, alerts = handler
    logger.warning("database would not open")

    bot = AlertBot()
    alerts.bind(bot, asyncio.get_running_loop())
    await asyncio.sleep(0.05)

    assert len(bot.sent) == 1
    assert "database would not open" in bot.sent[0]["text"]
    assert bot.sent[0]["chat_id"] == 111


async def test_nothing_is_delivered_before_the_bot_arrives(handler):
    """Held, not sent — there is nothing to send with yet."""
    logger, alerts = handler
    logger.warning("too early")

    bot = AlertBot()
    await asyncio.sleep(0.05)

    assert bot.sent == []


async def test_ordinary_alerts_still_work_afterwards(handler):
    logger, alerts = handler
    bot = AlertBot()
    alerts.bind(bot, asyncio.get_running_loop())

    logger.warning("something later")
    await asyncio.sleep(0.05)

    assert len(bot.sent) == 1
    assert "something later" in bot.sent[0]["text"]


async def test_binding_twice_does_not_replay_what_was_already_sent(handler):
    logger, alerts = handler
    logger.warning("only once")

    bot = AlertBot()
    alerts.bind(bot, asyncio.get_running_loop())
    alerts.bind(bot, asyncio.get_running_loop())
    await asyncio.sleep(0.05)

    assert len(bot.sent) == 1


def test_nothing_is_held_when_there_is_nobody_to_tell(monkeypatch):
    """No admin chats means no recipients, now or later."""
    monkeypatch.delenv("ADMIN_CHAT_IDS", raising=False)
    alerts = TelegramAlertHandler(level=logging.WARNING)

    alerts.emit(logging.LogRecord("goalbot.x", logging.WARNING, __file__, 1, "m", None, None))

    assert not alerts._pending


def test_the_backlog_is_bounded(monkeypatch):
    """A startup that never reaches `bind` must not grow without limit."""
    monkeypatch.setenv("ADMIN_CHAT_IDS", "111")
    alerts = TelegramAlertHandler(level=logging.WARNING)

    for index in range(MAX_PENDING_ALERTS + 20):
        alerts.emit(
            logging.LogRecord("goalbot.x", logging.WARNING, __file__, 1, f"m{index}", None, None)
        )

    assert len(alerts._pending) == MAX_PENDING_ALERTS
