"""Admin alerting: thresholds, deduplication, rate limiting, and PII."""
import asyncio
import logging

import pytest

from core.settings import ALERT_MAX_PER_MINUTE
from core.logs import TelegramAlertHandler, describe, get_logger


class AlertBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    async def send_message(self, chat_id, text, parse_mode=None, **kwargs):
        if self.fail:
            raise RuntimeError("telegram unreachable")

        self.sent.append({"chat_id": chat_id, "text": text})


@pytest.fixture
def alerts(monkeypatch):
    """A handler on its own logger, bound to the running loop."""
    monkeypatch.setenv("ADMIN_CHAT_IDS", "111,222")

    bot = AlertBot()
    handler = TelegramAlertHandler(level=logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("goalbot.test_alerts")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    yield logger, handler, bot

    logger.handlers = []


async def flush():
    """Let scheduled deliveries run. Each alert awaits one send per admin, so
    a couple of passes isn't always enough to drain them."""
    for _ in range(20):
        await asyncio.sleep(0)


async def test_warning_reaches_every_admin(alerts):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    logger.warning("scheduler fell over")
    await flush()

    assert [m["chat_id"] for m in bot.sent] == [111, 222]
    assert "scheduler fell over" in bot.sent[0]["text"]
    assert "WARNING" in bot.sent[0]["text"]


async def test_info_is_not_alerted(alerts):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    logger.info("routine thing happened")
    await flush()

    assert bot.sent == []


async def test_nothing_sent_before_binding(alerts):
    logger, handler, bot = alerts

    logger.error("too early")
    await flush()

    assert bot.sent == []


async def test_nothing_sent_without_admins(alerts, monkeypatch):
    logger, handler, bot = alerts
    monkeypatch.setenv("ADMIN_CHAT_IDS", "")
    handler.bind(bot, asyncio.get_running_loop())

    logger.error("nobody to tell")
    await flush()

    assert bot.sent == []


async def test_identical_alerts_are_deduplicated(alerts):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    for _ in range(5):
        logger.warning("same failure every hour")
    await flush()

    # One delivery per admin, not five.
    assert len(bot.sent) == 2


async def test_suppressed_count_is_reported(alerts, monkeypatch):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    for _ in range(4):
        logger.warning("repeating failure")
    await flush()

    # Force the dedupe window to lapse, then repeat.
    monkeypatch.setattr("core.logs.ALERT_DEDUPE_WINDOW_SECONDS", 0)
    logger.warning("repeating failure")
    await flush()

    assert "+3 identical suppressed" in bot.sent[-1]["text"]


async def test_different_messages_are_not_collapsed(alerts):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    logger.warning("first problem")
    logger.warning("second problem")
    await flush()

    assert len(bot.sent) == 4  # two alerts x two admins


async def test_rate_limit_caps_delivery(alerts):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    for index in range(ALERT_MAX_PER_MINUTE + 5):
        logger.warning("distinct failure %s", index)
    await flush()

    assert len(bot.sent) == ALERT_MAX_PER_MINUTE * 2


async def test_delivery_failure_does_not_raise_or_recurse(alerts):
    logger, handler, _ = alerts
    broken = AlertBot(fail=True)
    handler.bind(broken, asyncio.get_running_loop())

    logger.error("something broke")
    await flush()

    # Swallowed: routing this back through logging would loop forever.
    assert broken.sent == []


async def test_exception_alert_includes_traceback_not_locals(alerts):
    logger, handler, bot = alerts
    handler.bind(bot, asyncio.get_running_loop())

    secret = "приватна відповідь користувача"  # noqa: F841 - deliberately a local
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("handler failed for user=42")
    await flush()

    text = bot.sent[0]["text"]

    assert "ValueError" in text
    assert "user=42" in text
    # Tracebacks show source lines, never local variable values.
    assert secret not in text


def test_describe_reports_length_not_content():
    assert describe("приватна відповідь") == "18 chars"
    assert describe(None) == "none"
    assert "приватна" not in describe("приватна відповідь")


def test_logger_names_are_namespaced():
    """Pass `__name__` and the line says which package it came from, so the
    two front ends are told apart in a shared log directory."""
    assert get_logger("core.services.cohort").name == "goalbot.core.services.cohort"
    assert get_logger("bot.delivery").name == "goalbot.bot.delivery"
    assert get_logger("admin.app").name == "goalbot.admin.app"
