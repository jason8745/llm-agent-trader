# LLM Agent Trader

![star](star-history-20251112.png)

A Taiwan stock backtesting harness for coding agents. You discuss a strategy with Claude Code, Claude writes it as a small Python file, and a deterministic engine backtests it. Every run reports in-sample, out-of-sample, and buy-and-hold results side by side, so you can tell a real edge from a curve fit.

Claude Code is the brain. This project is the hands: Taiwan market data, MCP tools, the backtest engine, the profit module, and a read-only viewer. No LLM runs inside the backtest loop, and you do not need an LLM API key.

![viewer](docs/v2/evidence/pr6/detail-timeline.png)

## Install

You need [uv](https://docs.astral.sh/uv/) and Claude Code.

**Claude Code plugin** (MCP tools plus the research skill):

```
/plugin install llm-agent-trader --marketplace jason8745/llm-agent-trader
```

**Any MCP client** (tools only):

```bash
claude mcp add trader -- uvx --from git+https://github.com/jason8745/llm-agent-trader llm-agent-trader mcp
```

## Use

Open Claude Code in a project folder and describe what you want to study:

> 我想研究台積電的趨勢追蹤策略。請使用 2023-01-01 至 2025-12-31 的資料，設計一個均線類策略並回測，至少迭代兩次，最後告訴我結論。

Claude then:

1. Looks up the symbol (`search_stock("台積電")` returns `2330.TW`).
2. Writes `strategies/<name>.py`.
3. Calls `run_backtest` with a stated hypothesis for each iteration and tunes on in-sample results only.
4. Reports the final out-of-sample result against buy-and-hold, with a viewer link.

A full real session is in [docs/v2/evidence/pr7/claude-session.md](docs/v2/evidence/pr7/claude-session.md).

Runs are stored in `.trader/runs.db` in your project. The viewer starts automatically while the MCP server runs. After the session ends, reopen it with:

```bash
uvx --from git+https://github.com/jason8745/llm-agent-trader llm-agent-trader ui
```

## Strategy contract

```python
"""ma_cross: hold while the 10-day SMA is above the 20-day SMA, long only."""

from trader import ta

PARAMS = {"fast": 10, "slow": 20}


def on_bar(hist, pos, p):
    fast = ta.sma(hist.close, p["fast"]).iloc[-1]
    slow = ta.sma(hist.close, p["slow"]).iloc[-1]
    return 1.0 if fast > slow else 0.0
```

- `hist` holds the bars up to and including today: `open, high, low, close, volume, dividend`. The strategy cannot see tomorrow.
- The return value is the target position, from 0.0 to 1.0. It fills at the next day's open, and the position changes only when the returned target changes.
- `trader.ta` provides `sma`, `ema`, `rsi`, `macd`, `bbands`, and `atr` with TA-Lib conventions. Indicators compose, for example `ta.ema(ta.rsi(hist.close, 14), 5)`.

## How the numbers are computed

- **Fees (Taiwan).** Commission is 0.1425% on both sides with a NT$20 minimum. Sell tax is 0.3% for stocks and 0.1% for ETFs. Both are floored to whole NT$. Other markets default to zero fees.
- **Dividends.** Prices are split-adjusted, not dividend-adjusted. Cash dividends are credited on the ex-date, so an ex-dividend drop is not counted as a loss.
- **In-sample and out-of-sample.** The first 70% of the bars is in-sample and the last 30% is out-of-sample, in one continuous run. Returns are measured against initial cash, so (1 + IS) × (1 + OOS) = 1 + total.
- **⚑ overfit flag.** It shows when the annualized in-sample return exceeds the annualized out-of-sample return by more than 15 points.
- **One formatter.** Every number shown by the tools, the CLI, and the viewer comes from `trader.profit` and is rendered by `trader.fmt`. Tests enforce identical strings across all three.

Full definitions are in [docs/v2/design.md](docs/v2/design.md) section 4.

## CLI

```bash
llm-agent-trader search 台積電
llm-agent-trader backtest ma_cross 2330.TW 2023-01-01 2025-12-31 --hypothesis "..."
llm-agent-trader runs
llm-agent-trader show 1
llm-agent-trader ui
llm-agent-trader mcp
```

## Development

```bash
uv sync
uv run pytest                      # TRADER_LIVE=1 also hits yfinance
scripts/mutation_check.sh          # plants known engine bugs; each must fail the suite
uv run --with ta-lib --with numpy python tests/fixtures/gen_talib_reference.py
uv run python scripts/build_stock_list.py
```

- Architecture: [docs/v2/architecture.html](docs/v2/architecture.html)
- Decision log for the v2 build: [docs/v2/decisions.tsv](docs/v2/decisions.tsv)
- v1 (an LLM-endpoint backtester) is archived on the [`archive/v1`](https://github.com/jason8745/llm-agent-trader/tree/archive/v1) branch and the `v1` tag.

## License

MIT. The viewer bundles [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) 5.2.1 under the Apache License 2.0 (`src/trader/viewer/lightweight-charts.LICENSE`).
