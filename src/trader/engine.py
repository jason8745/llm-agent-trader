"""Deterministic long-only backtest engine.

A decision made on bar t's close is filled at bar t+1's open. The strategy only ever
sees a copy of the bars up to and including t.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

BAR_COLUMNS = ("open", "high", "low", "close", "volume", "dividend")

# Guards floor() against float noise such as 1422.9999999998 for an exact 1423.
_FLOOR_EPS = 1e-9


class StrategyError(Exception):
    pass


@dataclass(frozen=True)
class Fees:
    commission_rate: float = 0.0
    min_commission: float = 0.0
    sell_tax_rate: float = 0.0
    floor_to_unit: bool = False

    def _round(self, amount: float) -> float:
        return float(math.floor(amount + _FLOOR_EPS)) if self.floor_to_unit else amount

    def commission(self, gross: float) -> float:
        if gross <= 0 or self.commission_rate <= 0:
            return 0.0
        return max(self._round(gross * self.commission_rate), self.min_commission)

    def tax(self, gross: float) -> float:
        if gross <= 0 or self.sell_tax_rate <= 0:
            return 0.0
        return self._round(gross * self.sell_tax_rate)


NO_FEES = Fees()
TW_STOCK_FEES = Fees(
    commission_rate=0.001425, min_commission=20, sell_tax_rate=0.003, floor_to_unit=True
)
TW_ETF_FEES = Fees(
    commission_rate=0.001425, min_commission=20, sell_tax_rate=0.001, floor_to_unit=True
)


def fees_for(symbol: str) -> Fees:
    code, _, suffix = symbol.upper().partition(".")
    if suffix not in ("TW", "TWO"):
        return NO_FEES
    return TW_ETF_FEES if code.startswith("00") else TW_STOCK_FEES


@dataclass(frozen=True)
class Fill:
    bar: int
    date: str
    side: Literal["BUY", "SELL"]
    price: float
    shares: int
    gross: float
    commission: float
    tax: float

    @property
    def cash_delta(self) -> float:
        if self.side == "BUY":
            return -(self.gross + self.commission)
        return self.gross - self.commission - self.tax


@dataclass(frozen=True)
class RoundTrip:
    entry_bar: int
    exit_bar: int
    entry_date: str
    exit_date: str
    pnl: float

    @property
    def holding_bars(self) -> int:
        return self.exit_bar - self.entry_bar


@dataclass
class Ledger:
    initial_cash: float
    dates: list[str] = field(default_factory=list)
    cash: list[float] = field(default_factory=list)
    shares: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    round_trips: list[RoundTrip] = field(default_factory=list)
    dividends: list[float] = field(default_factory=list)
    realized_pnl: float = 0.0
    cost_basis: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return self.equity[-1] - self.cash[-1] - self.cost_basis


Decide = Callable[[pd.DataFrame, float], float]


def _parse_target(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyError(f"on_bar must return a number between 0 and 1, got {value!r}")
    w = float(value)
    if not math.isfinite(w) or w < 0 or w > 1:
        raise StrategyError(f"on_bar must return a number between 0 and 1, got {value!r}")
    return w


def _affordable_shares(cash: float, price: float, fees: Fees) -> int:
    n = math.floor(cash / price + _FLOOR_EPS)
    while n > 0 and n * price + fees.commission(n * price) > cash:
        n -= 1
    return max(n, 0)


def simulate(
    bars: pd.DataFrame,
    decide: Decide,
    fees: Fees,
    initial_cash: float,
    initial_target: float | None = None,
) -> Ledger:
    """Run decide over bars. initial_target, when set, is filled at bar 0's open."""
    led = Ledger(initial_cash=initial_cash)
    cash, shares = float(initial_cash), 0
    pending = initial_target
    last_target = initial_target
    entry_bar, trip_pnl = -1, 0.0
    dates = [d.strftime("%Y-%m-%d") for d in bars.index]
    rows = bars[list(BAR_COLUMNS)].to_numpy(dtype=float)
    n = len(rows)

    for t in range(n):
        o, _, _, c, _, div = rows[t]
        date = dates[t]

        div_cash = shares * div if shares and div else 0.0
        if div_cash:
            cash += div_cash
            led.realized_pnl += div_cash
            trip_pnl += div_cash
        led.dividends.append(div_cash)

        if pending is not None:
            equity_at_open = cash + shares * o
            target_shares = math.floor(pending * equity_at_open / o + _FLOOR_EPS) if pending else 0
            if target_shares < shares:
                qty = shares - target_shares
                gross = qty * o
                f = Fill(t, date, "SELL", o, qty, gross, fees.commission(gross), fees.tax(gross))
                released = led.cost_basis * qty / shares
                gain = f.cash_delta - released
                cash += f.cash_delta
                led.realized_pnl += gain
                trip_pnl += gain
                led.cost_basis -= released
                shares = target_shares
                led.fills.append(f)
                if shares == 0:
                    led.cost_basis = 0.0
                    led.round_trips.append(
                        RoundTrip(entry_bar, t, dates[entry_bar], date, trip_pnl)
                    )
            elif target_shares > shares:
                qty = min(target_shares - shares, _affordable_shares(cash, o, fees))
                if qty > 0:
                    gross = qty * o
                    f = Fill(t, date, "BUY", o, qty, gross, fees.commission(gross), 0.0)
                    if shares == 0:
                        entry_bar, trip_pnl = t, 0.0
                    cash += f.cash_delta
                    led.cost_basis -= f.cash_delta
                    shares += qty
                    led.fills.append(f)
            pending = None

        led.dates.append(date)
        led.cash.append(cash)
        led.shares.append(shares)
        led.equity.append(cash + shares * c)

        if t < n - 1:
            pos = shares * c / led.equity[-1] if led.equity[-1] > 0 else 0.0
            target = _parse_target(decide(bars.iloc[: t + 1].copy(), pos))
            if target != last_target:
                pending = last_target = target

    return led


def buy_and_hold(bars: pd.DataFrame, fees: Fees, initial_cash: float) -> Ledger:
    return simulate(bars, lambda _h, _p: 1.0, fees, initial_cash, initial_target=1.0)
