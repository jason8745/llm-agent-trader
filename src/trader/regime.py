"""Market regime segmentation: an ex-post description of a price series, not a signal.

Range windows are found first (a tight band held long enough); the stretches between
them are split into legs with a zigzag and each leg is classified by its return.
"""

from dataclasses import dataclass
from typing import Literal

REVERSAL = 0.10  # zigzag pivot when price reverses >= 10% from the running extreme
TREND = 0.15  # a leg is "up" if its return >= +15%, "down" if <= -15%, else "range"
RANGE_BAND = 0.12  # a range window: max/min - 1 <= 12% ...
RANGE_MIN_BARS = 60  # ... for at least 60 bars (j - i >= 60)

Kind = Literal["up", "down", "range"]


@dataclass(frozen=True)
class Regime:
    start: int  # bar indices into close, inclusive; neighbours share the boundary bar
    end: int
    kind: Kind


def _band(c: list[float], i: int, j: int) -> float:
    seg = c[i : j + 1]
    return max(seg) / min(seg) - 1


def _range_windows(c: list[float]) -> list[tuple[int, int]]:
    out, i, n = [], 0, len(c)
    while i < n - 1:
        j, lo, hi = i, c[i], c[i]
        while j + 1 < n and max(hi, c[j + 1]) / min(lo, c[j + 1]) - 1 <= RANGE_BAND:
            j += 1
            lo, hi = min(lo, c[j]), max(hi, c[j])
        if j - i >= RANGE_MIN_BARS:
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _zigzag(c: list[float], a: int, b: int) -> list[int]:
    """Pivot indices of c[a..b]; a and b are always pivots (no pivots if a == b)."""
    if a >= b:
        return []
    pivots, direction, ext = [a], 0, a
    for i in range(a + 1, b + 1):
        if direction == 0:
            if abs(c[i] / c[a] - 1) >= REVERSAL:
                direction, ext = (1 if c[i] > c[a] else -1), i
        elif direction * (c[i] - c[ext]) > 0:
            ext = i
        elif direction * (c[i] / c[ext] - 1) <= -REVERSAL:
            pivots.append(ext)
            direction, ext = -direction, i
    pivots.append(b)
    return pivots


def _kind(ret: float) -> Kind:
    return "up" if ret >= TREND else "down" if ret <= -TREND else "range"


def segment(close: list[float]) -> list[Regime]:
    """Tile close[0..n-1] with regimes. Raises ValueError for fewer than 2 bars."""
    c = list(close)
    if len(c) < 2:
        raise ValueError(f"need at least 2 closes, got {len(c)}")
    windows = _range_windows(c)

    raw: list[Regime] = []
    cursor = 0
    for i, j in [*windows, (len(c) - 1, None)]:
        p = _zigzag(c, cursor, i)
        raw += [Regime(x, y, _kind(c[y] / c[x] - 1)) for x, y in zip(p, p[1:], strict=False)]
        if j is not None:
            raw.append(Regime(i, j, "range"))
            cursor = j

    merged = [raw[0]]
    for g in raw[1:]:
        last = merged[-1]
        if g.kind == last.kind and (g.kind != "range" or _band(c, last.start, g.end) <= RANGE_BAND):
            merged[-1] = Regime(last.start, g.end, g.kind)
        else:
            merged.append(g)
    return merged
