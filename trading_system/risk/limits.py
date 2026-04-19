from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from trading_system.storage.models import Position, Signal


@dataclass
class RiskLimits:
    max_positions: int = 10
    max_position_pct: float = 0.05
    max_sector_pct: float = 0.20
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    max_trades_per_day: int = 20
    min_price: float = 5.0
    min_volume: int = 500  # IEX free feed captures ~2% of real volume; 500 IEX shares ≈ 25,000 real shares

    def __repr__(self) -> str:
        return f"RiskLimits(max_positions={self.max_positions}, max_position_pct={self.max_position_pct}, max_drawdown_pct={self.max_drawdown_pct})"


# ---------------------------------------------------------------------------
# Portfolio-level risk manager (sector exposure + concentration checks)
# ---------------------------------------------------------------------------

try:
    from trading_system.data.universe import _infer_sector  # type: ignore[import]
except ImportError:  # pragma: no cover
    def _infer_sector(symbol: str) -> str:  # type: ignore[misc]
        return "Other"


class PortfolioRiskManager:
    """Enforce sector-level and portfolio-level exposure limits.

    Checks performed before allowing a new position:
        1. Sector exposure: the new position must not push any sector above
           ``max_sector_pct`` of total portfolio equity.
        2. Max positions: total open positions must be < ``risk_limits.max_positions``.
        3. Daily trade count: must be < ``risk_limits.max_trades_per_day``.
        4. Single-position size: notional ≤ ``risk_limits.max_position_pct`` of equity.
    """

    def __init__(self, risk_limits: RiskLimits) -> None:
        self.limits = risk_limits
        self._daily_trade_count: int = 0
        self._daily_reset_date: Optional[str] = None
        self.logger = logging.getLogger("trading_system.risk.portfolio")

    def __repr__(self) -> str:
        return f"PortfolioRiskManager(max_positions={self.limits.max_positions}, max_sector_pct={self.limits.max_sector_pct:.0%})"

    def reset_daily_counters(self, date_str: str) -> None:
        """Reset per-day counters; call once at market open."""
        if self._daily_reset_date != date_str:
            self._daily_trade_count = 0
            self._daily_reset_date = date_str
            self.logger.info("Daily counters reset for %s", date_str)

    def record_trade(self) -> None:
        """Increment daily trade counter."""
        self._daily_trade_count += 1

    def sector_exposures(self, positions: dict[str, Position], equity: float) -> dict[str, float]:
        """Return fraction of equity committed to each sector."""
        sector_notional: dict[str, float] = defaultdict(float)
        for symbol, pos in positions.items():
            sector = _infer_sector(symbol)
            sector_notional[sector] += pos.qty * pos.entry_price
        if equity <= 0:
            return {}
        return {sector: round(notional / equity, 4) for sector, notional in sector_notional.items()}

    def is_position_allowed(
        self,
        symbol: str,
        notional: float,
        positions: dict[str, Position],
        equity: float,
    ) -> tuple[bool, str]:
        """Return (allowed, rejection_reason).

        ``notional`` is the dollar value of the proposed trade (qty × price).
        """
        # Max positions
        if len(positions) >= self.limits.max_positions:
            return False, f"max positions reached ({len(positions)}/{self.limits.max_positions})"

        # Daily trade count
        if self._daily_trade_count >= self.limits.max_trades_per_day:
            return False, f"daily trade limit reached ({self._daily_trade_count}/{self.limits.max_trades_per_day})"

        # Single-position size cap
        if equity > 0 and notional / equity > self.limits.max_position_pct:
            return False, f"position size {notional/equity:.1%} > max {self.limits.max_position_pct:.1%}"

        # Sector cap
        if equity > 0:
            sector = _infer_sector(symbol)
            current_exposures = self.sector_exposures(positions, equity)
            current_sector_pct = current_exposures.get(sector, 0.0)
            new_sector_pct = current_sector_pct + notional / equity
            if new_sector_pct > self.limits.max_sector_pct:
                return False, (
                    f"sector '{sector}' exposure {new_sector_pct:.1%} "
                    f"would exceed limit {self.limits.max_sector_pct:.1%}"
                )

        return True, ""

