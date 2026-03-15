from __future__ import annotations

from datetime import time as dt_time


REGULAR_MARKET_OPEN = dt_time(hour=9, minute=30)
REGULAR_MARKET_CLOSE = dt_time(hour=16, minute=0)
EXTENDED_MARKET_OPEN = dt_time(hour=4, minute=0)
EXTENDED_MARKET_CLOSE = dt_time(hour=20, minute=0)


def market_session_allows(now, session_mode):
    current_time = now.time()
    if session_mode == "extended":
        return EXTENDED_MARKET_OPEN <= current_time <= EXTENDED_MARKET_CLOSE
    return REGULAR_MARKET_OPEN <= current_time <= REGULAR_MARKET_CLOSE
