#!/bin/bash
# Plants known bugs in the engine, runner and profit modules; each one must make the test suite fail.
set -u
cd "$(dirname "$0")/.."
mutate() {
  local file=$1 from=$2 to=$3 label=$4
  cp "$file" "$file.bak"
  python3 -c "import sys;p,a,b=sys.argv[1:];s=open(p).read();assert a in s,a;open(p,'w').write(s.replace(a,b,1))" "$file" "$from" "$to"
  if uv run pytest tests -q -x >/dev/null 2>&1; then echo "SURVIVED  $label"; status=1; else echo "KILLED    $label"; fi
  mv "$file.bak" "$file"
}
status=0
mutate src/trader/engine.py 'o, _, _, c, _, div = rows[t]' 'c, _, _, o, _, div = rows[t]' "fill at close instead of next open"
mutate src/trader/engine.py 'decide(bars.iloc[: t + 1].copy(), pos)' 'decide(bars.iloc[: t + 2].copy(), pos)' "strategy sees tomorrow's bar"
mutate src/trader/engine.py 'float(math.floor(amount + _FLOOR_EPS))' 'float(round(amount))' "fees rounded instead of floored"
mutate src/trader/engine.py 'max(self._round(gross * self.commission_rate), self.min_commission)' 'self._round(gross * self.commission_rate)' "minimum commission ignored"
mutate src/trader/engine.py 'cash += div_cash' 'pass' "dividends not credited"
mutate src/trader/runner.py 'start=job["start"])' 'start=job["start"] + 1)' "backtest starts one bar late"
mutate src/trader/runner.py 'bars = bars.iloc[max(0, k - WARMUP_BARS) :]' 'bars = bars.iloc[k:]' "warm-up history dropped"
mutate src/trader/profit.py 'price_change=math.prod(1 + r.price_change for r in g) - 1' 'price_change=sum(r.price_change for r in g)' "regime summary adds instead of compounding"
mutate src/trader/profit.py '            peak, peak_i = v, t' '            peak_i = t' "drawdown peak never rises"
exit $status
