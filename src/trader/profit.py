"""Performance metrics. Every number the harness reports is computed here.

Returns are measured against the initial cash, so (1 + IS) * (1 + OOS) == 1 + total.
"""

import math
from dataclasses import dataclass

from trader.engine import Ledger

IS_FRACTION = 0.7
MIN_BARS = 3  # smallest n where both in-sample and out-of-sample are non-empty
OVERFIT_GAP = 0.15


@dataclass(frozen=True)
class Segment:
    ret: float
    mdd: float


@dataclass(frozen=True)
class Report:
    split: int
    total: Segment
    in_sample: Segment
    out_of_sample: Segment
    bh_total: Segment
    bh_in_sample: Segment
    bh_out_of_sample: Segment
    trades: int
    win_rate: float | None
    final_equity: float
    realized_pnl: float
    unrealized_pnl: float

    @property
    def overfit(self) -> bool:
        return self.in_sample.ret - self.out_of_sample.ret > OVERFIT_GAP


def split_index(n: int) -> int:
    if n < MIN_BARS:
        raise ValueError(f"need at least {MIN_BARS} bars, got {n}")
    return math.floor(IS_FRACTION * n)


def segment(start_value: float, values: list[float]) -> Segment:
    peak, mdd = start_value, 0.0
    for v in values:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return Segment(ret=values[-1] / start_value - 1, mdd=mdd)


def _segments(led: Ledger, s: int) -> tuple[Segment, Segment, Segment]:
    e, c0 = led.equity, led.initial_cash
    return segment(c0, e), segment(c0, e[:s]), segment(e[s - 1], e[s - 1 :])


def report(led: Ledger, bh: Ledger) -> Report:
    s = split_index(len(led.equity))
    total, is_, oos = _segments(led, s)
    bh_total, bh_is, bh_oos = _segments(bh, s)
    trips = led.round_trips
    return Report(
        split=s,
        total=total,
        in_sample=is_,
        out_of_sample=oos,
        bh_total=bh_total,
        bh_in_sample=bh_is,
        bh_out_of_sample=bh_oos,
        trades=len(trips),
        win_rate=sum(t.pnl > 0 for t in trips) / len(trips) if trips else None,
        final_equity=led.equity[-1],
        realized_pnl=led.realized_pnl,
        unrealized_pnl=led.unrealized_pnl,
    )
