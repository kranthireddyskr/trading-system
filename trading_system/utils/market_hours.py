from __future__ import annotations

from datetime import datetime
import pytz


def is_market_open(now: datetime | None = None) -> bool:
    et = pytz.timezone("America/New_York")
    now = now or datetime.now(et)
    if now.tzinfo is None:
        now = et.localize(now)
    else:
        now = now.astimezone(et)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close


def is_past_shutdown(now: datetime | None = None) -> bool:
    et = pytz.timezone("America/New_York")
    now = now or datetime.now(et)
    if now.tzinfo is None:
        now = et.localize(now)
    else:
        now = now.astimezone(et)
    return now.weekday() < 5 and (now.hour > 16 or (now.hour == 16 and now.minute >= 5))
