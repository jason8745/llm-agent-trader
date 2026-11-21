import pytest
from bars import random_bars

from trader.regime import RANGE_BAND, Regime, segment


def ramp(*knots, steps=10):
    """Linear path through knots, steps bars per segment, shared knots not repeated."""
    out = [float(knots[0])]
    for a, b in zip(knots, knots[1:], strict=False):
        out += [a + (b - a) * k / steps for k in range(1, steps + 1)]
    return out


def kinds(c):
    return [(g.kind, g.start, g.end) for g in segment(c)]


def band(c, g):
    return max(c[g.start : g.end + 1]) / min(c[g.start : g.end + 1]) - 1


def test_trends():
    assert kinds(ramp(100, 150, steps=29)) == [("up", 0, 29)]
    assert kinds(ramp(100, 70, steps=29)) == [("down", 0, 29)]
    # pivot at the peak; both legs share it
    assert kinds(ramp(100, 150, 100, steps=30)) == [("up", 0, 30), ("down", 30, 60)]


def test_zigzag_leg_under_trend_threshold_is_range():
    # +12% decides the direction (>= 10%) but is under 15%; then -15.2% from 112
    assert kinds(ramp(100, 112, 95)) == [("range", 0, 10), ("down", 10, 20)]


def test_small_move_has_no_pivot():
    # +9% never reaches the 10% reversal, so the whole series is one leg
    assert kinds(ramp(100, 109, 100, 109)) == [("range", 0, 30)]
    # -8.5% dip is no pivot, so it is one +20% leg (an 8% threshold would split range/up)
    assert kinds(ramp(100, 91.5, 120)) == [("up", 0, 20)]


def test_range_window_needs_60_bars():
    # flat 61 bars (j - i = 60) is a range window; then +30% is an up leg
    assert kinds([100.0] * 61 + [130.0] * 5) == [("range", 0, 60), ("up", 60, 65)]
    # flat 60 bars (j - i = 59) is not; the zigzag sees one +30% leg
    assert kinds([100.0] * 60 + [130.0] * 5) == [("up", 0, 64)]


def test_adjacent_range_windows_merge_only_within_band():
    # 100 and 110 fit one 12% band; 120 breaks it, so a second window starts at the last 110
    c = [100.0] * 70 + [110.0] * 70 + [120.0] * 70
    assert kinds(c) == [("range", 0, 139), ("range", 139, 209)]  # merged would be 20%


def test_adjacent_range_legs_merge_within_band():
    # +11.5% then -10.3%: two "range" legs; together 11.5% <= 12% so they merge
    assert kinds(ramp(100, 111.5, 100)) == [("range", 0, 20)]
    # +14% then -10.5%: together 14% > 12%, kept apart
    assert kinds(ramp(100, 114, 102)) == [("range", 0, 10), ("range", 10, 20)]


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_tiling_and_merge_invariants(seed):
    c = random_bars(n=700, seed=seed)["close"].tolist()
    regs = segment(c)
    assert regs[0].start == 0 and regs[-1].end == len(c) - 1
    for a, b in zip(regs, regs[1:], strict=False):
        assert a.end == b.start and a.start < a.end
        if a.kind == b.kind:
            assert a.kind == "range" and band(c, Regime(a.start, b.end, "range")) > RANGE_BAND
    assert segment(c) == regs  # deterministic


def test_too_short():
    with pytest.raises(ValueError):
        segment([100.0])
    assert kinds([100.0, 101.0]) == [("range", 0, 1)]
