"""Single source of "now" for the bot.

Everything runs on Kyiv wall-clock time regardless of where the server is.
`now_kyiv` returns a *naive* datetime holding Kyiv local time: peewee's
DateTimeField drops tzinfo when it formats to SQLite anyway, so keeping every
timestamp naive avoids mixing aware and naive values in comparisons.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def now_kyiv() -> datetime:
    return datetime.now(KYIV_TZ).replace(tzinfo=None)


def today_kyiv():
    return now_kyiv().date()
