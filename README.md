# 台股回測 LLM Agent Trader

![star](star-history-20251112.png)

用聊天的方式研究台股策略。你說出想法，Claude 撰寫策略、回測、解讀結果，並在 dashboard 上即時呈現。每一個數字都由確定性的回測引擎計算，Claude 只負責討論與解讀，不自行計算。

不需要寫程式，也不需要 API key。安裝好 Claude Desktop 之後，下載一個檔案、點兩下就能開始。

*English summary at the [end of this page](#english).*

![dashboard](docs/v2/evidence/pr20/dashboard-desktop.png)

## 特色

- **兩段期間，直接看出過度擬合。** 每次回測都分成「策略開發期間」（用來設計與調整策略）與「策略執行期間」（模擬策略定稿後實際執行，不參與調整），兩段都與「買進並持有」並列比較。
- **回測前先確認。** 第一次回測前，Claude 會逐題確認標的、策略、兩段期間、資金與費用，每題都附建議，回覆「yes」即可。
- **結論有發現，也有洞察。** 定稿時，Claude 寫入一句總結與數組「發現與洞察」，涵蓋過度擬合、與買進並持有比較、盤勢（上漲段、盤整段、下跌段）與統計可信度。結論中的每個數字都會由程式驗證。
- **dashboard 即時更新。** 以圖表為主，Claude 每完成一次回測，頁面幾秒內自動更新。
- **台股資料內建。** 上市、上櫃股票與 ETF 共 2,324 檔，可以用中文名稱查詢，台股手續費與證交稅已內建。

## 安裝

選擇一種方式即可。不會用終端機的話，請選方法一。

### 方法一：Claude Desktop（不需要終端機）

1. 安裝並登入 [Claude Desktop](https://claude.ai/download)。
2. 到 [Releases 頁面](https://github.com/jason8745/llm-agent-trader/releases/latest)，下載最新的 `llm-agent-trader-x.y.z.mcpb`。
3. 點兩下下載的檔案，或把它拖進 Claude Desktop 視窗，在跳出的視窗按「安裝」。「研究資料夾」維持預設即可。
4. 開一個新對話，輸入：

   ```
   開始使用台股回測
   ```

不需要另外安裝 Python 或其他軟體，Claude Desktop 會自動準備執行環境。第一次回測時，系統會下載回測引擎需要的元件，可能需要一至數分鐘；之後每次回測只要幾秒。

### 方法二：Claude Code

已經在使用 [Claude Code](https://code.claude.com) 的話，在終端機執行：

```bash
claude plugin marketplace add jason8745/llm-agent-trader
claude plugin install llm-agent-trader@llm-agent-trader
```

接著在任何資料夾啟動 `claude`，輸入 `/llm-agent-trader:start`，或直接說「開始使用台股回測」。

需要先安裝 [uv](https://docs.astral.sh/uv/)：macOS 與 Linux 執行 `curl -LsSf https://astral.sh/uv/install.sh | sh`，Windows 在 PowerShell 執行 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`。

## 第一次使用

說「開始使用台股回測」之後，Claude 會依序：

1. **徵求同意建立研究資料夾。** 位置是「文件 › trader-research」，用來存放策略檔與回測紀錄。你同意後才會建立。
2. **確認工具可以使用。** 查詢「台積電」，確認回測工具正常。
3. **開啟 dashboard。** 瀏覽器會自動開啟；沒有開啟時，點 Claude 回覆中的網址即可。
4. **說明流程，並請你提出研究主題。** 例如：

   > 我想研究台積電的趨勢追蹤策略。請使用 2023-01-01 至 2025-12-31 的資料，設計一個均線類策略並回測，至少迭代兩次，最後告訴我結論。

   > 請以 0050 測試 RSI 超賣進場、超買出場的策略，期間為 2020-01-01 至 2025-12-31，並與買進並持有基準比較。

## 一次研究的流程

1. **確認五項研究條件。** Claude 會逐題列出，每題附建議答案，全部同意就回覆「yes」，要修改就註明題號：
   1. 標的，例如 `2330.TW 台積電`。
   2. 策略邏輯與初始參數。
   3. 策略開發期間：用來設計與調整策略。
   4. 策略執行期間：較晚的一段期間，模擬策略定稿後實際執行，以初始資金重新開始，不參與任何調整。預設為最後 12 個月。
   5. 初始資金與費用：預設新臺幣 1,000,000 元與台股手續費、證交稅。
2. **撰寫策略並回測。** Claude 撰寫策略並逐次回測，每次都寫明要驗證的假設。調整只依據策略開發期間的結果；策略執行期間的結果每次都會顯示，用來檢驗策略在沒參與調整的期間是否仍然有效。
3. **定稿。** Claude 選出定稿的版本，寫入一句總結與數組「發現與洞察」：發現是有數字的事實，洞察說明這代表什麼、原因或下一步。

完整的真實對話紀錄：[第一輪（確認研究條件）](docs/v2/evidence/pr20/claude-session-turn1.md)、[第二輪（回測與定稿）](docs/v2/evidence/pr20/claude-session-turn2.md)。

## 看懂 dashboard

- **左側：研究清單。** 依股票分組。一個「研究」是一檔股票、一個策略與兩段期間，底下列出每一次迭代。
- **中間：圖表。** 上方是迭代切換、這次的假設與四個重點數字，下面是三張同步的圖：
  - **K 線與成交量**：含買賣點、盤勢分段（上漲段紅、盤整段灰、下跌段綠）與策略執行期間起點。
  - **累積報酬率**：策略與買進並持有的比較。策略執行期間以初始資金重新開始，所以曲線接在策略開發期間的終點往下畫；策略執行期間內曲線的漲跌幅，就等於策略執行期間的報酬率。
  - **回撤**：策略從高點回落的幅度。
  - 滑鼠移到圖上會顯示當天的數值。下方抽屜可展開成交明細、已平倉交易、最深回撤、盤勢分段表與策略原始碼。
- **右側：結論。** 一句總結、兩段期間對照與過度擬合檢查、發現與洞察、各盤勢的表現。

dashboard 會跟著 Claude 的回測自動更新，不需要重新整理。之後想再打開，對 Claude 說「打開 dashboard」即可。

## 研究資料夾

所有研究都存放在同一個資料夾，預設是「文件 › trader-research」（`~/Documents/trader-research`）：

- `strategies/`：策略檔。
- `.trader/runs.db`：回測紀錄與結論。

刪除這個資料夾就會刪除所有研究。要改放其他位置：Claude Desktop 在擴充功能設定中修改「研究資料夾」；Claude Code 設定環境變數 `TRADER_WORKSPACE`。

## 常見問題

**第一次回測為什麼比較久？** 第一次會下載回測引擎需要的元件（約 50 MB），視網路狀況需要一至數分鐘，之後只要幾秒。

**dashboard 沒有自動打開？** 點 Claude 回覆中 `http://127.0.0.1:8765/` 開頭的網址。

**Claude 說「研究資料夾尚未建立」？** 這是在等你同意，回覆「好」或「同意」即可。

**如何更新？** Claude Desktop：下載新版的 `.mcpb` 再安裝一次。Claude Code：執行 `claude plugin marketplace update llm-agent-trader` 與 `claude plugin update llm-agent-trader@llm-agent-trader`，再重新啟動 Claude Code。

**如何移除？** Claude Desktop：在設定的擴充功能中移除。Claude Code：執行 `claude plugin uninstall llm-agent-trader@llm-agent-trader`。研究資料夾不會被刪除。

**支援哪些股票？** 台灣上市、上櫃股票與 ETF 的日 K 資料，來源為 Yahoo Finance。只做多，以整股計算。

**這是投資建議嗎？** 不是。回測結果只反映歷史資料，不代表未來績效。

## 數字怎麼計算

- **費用（台股）。** 手續費買賣各 0.1425%，最低新臺幣 20 元；證交稅股票 0.3%、ETF 0.1%；皆元以下捨去。
- **股利。** 價格只做分割調整，不做股利調整；現金股利於除息日入帳，所以除息造成的價格下跌不會被算成虧損。
- **成交。** 當天收盤產生訊號，隔一個交易日開盤成交。
- **兩段期間。** 策略開發期間只使用自己的資料。策略執行期間從起日當天或之後的第一個交易日開始，以初始資金、空手開始，策略可以使用之前的資料計算指標。買進並持有在兩段期間以相同方式計算，報酬率都相對於初始資金。
- **⚑ 過度擬合警示。** 策略開發期間的年化報酬率較策略執行期間高出逾 15 個百分點時顯示。
- **盤勢分段。** 依固定規則分段：價格在 12% 區間內來回達 60 個交易日以上為盤整段；其餘期間以反轉 10% 判斷轉折，漲幅達 15% 為上漲段、跌幅達 15% 為下跌段，其餘為盤整段。
- **單一格式化來源。** 工具、CLI 與 dashboard 顯示的每個數字都由 `trader.profit` 計算、`trader.fmt` 格式化，測試確保三處字串完全相同。

完整定義見 [docs/v2/design.md](docs/v2/design.md) 第 4 節。

## 策略的寫法

Claude 會替你撰寫策略，以下供想自己修改的人參考：

```python
"""ma_cross：10 日均線高於 20 日均線時持有，僅做多。"""

from trader import ta

PARAMS = {"fast": 10, "slow": 20}


def on_bar(hist, pos, p):
    fast = ta.sma(hist.close, p["fast"]).iloc[-1]
    slow = ta.sma(hist.close, p["slow"]).iloc[-1]
    return 1.0 if fast > slow else 0.0
```

- `hist`：截至當天收盤的日 K（`open, high, low, close, volume, dividend`），看不到未來的資料。
- 回傳值是目標持倉比例（0.0 至 1.0），隔一個交易日開盤成交，只有回傳值改變時才調整部位。
- `trader.ta` 提供 `sma`、`ema`、`rsi`、`macd`、`bbands`、`atr`，慣例與 TA-Lib 一致，可以互相組合，例如 `ta.ema(ta.rsi(hist.close, 14), 5)`。

## 進階：命令列

不透過 Claude 也能使用，指令作用在研究資料夾：

```bash
uvx --from git+https://github.com/jason8745/llm-agent-trader llm-agent-trader search 台積電
uvx --from git+https://github.com/jason8745/llm-agent-trader llm-agent-trader backtest ma_cross 2330.TW 2023-01-01 2024-12-31 2025-01-01 2025-12-31 --hypothesis "..."
uvx --from git+https://github.com/jason8745/llm-agent-trader llm-agent-trader ui
```

其他指令：`runs`（列出回測）、`show <編號>`（顯示一次回測）、`mcp`（啟動 MCP server）。

## 開發

```bash
git clone https://github.com/jason8745/llm-agent-trader && cd llm-agent-trader
uv sync
uv run pytest                         # TRADER_LIVE=1 會實際連線 yfinance
scripts/mutation_check.sh             # 植入已知錯誤，每一個都必須讓測試失敗
uv run python scripts/build_mcpb.py   # 產生 Claude Desktop 安裝檔 dist/*.mcpb
uv run python scripts/gen_mcp_manifest.py
uv run python scripts/build_stock_list.py
```

- 在 Claude Code 中試用本地修改：在 repo 根目錄執行 `claude --plugin-dir .`。
- 研究流程與規則只有一份：`src/trader/guide.md`，由 MCP 工具 `get_research_guide` 提供給 Claude Desktop 與 Claude Code。
- 決策紀錄：[docs/v2/decisions.tsv](docs/v2/decisions.tsv)；dashboard 的設計選項：[docs/v2/mockups/v3](docs/v2/mockups/v3)。
- v1（呼叫 LLM endpoint 的回測器）封存在 [`archive/v1`](https://github.com/jason8745/llm-agent-trader/tree/archive/v1) 分支與 `v1` tag。

## English

A Taiwan stock backtesting harness for Claude. You discuss a strategy in chat; Claude writes it, backtests it on a deterministic engine, and explains the result on a live dashboard. Every number is computed by the engine, never by the model. Each backtest has a development period for tuning and a later execution period that simulates live use, both compared with buy-and-hold, so overfitting is visible. Conclusions are stored as a verdict plus findings paired with insights, and every number in them is verified against the tool output.

Install: in Claude Desktop, download the `.mcpb` from [Releases](https://github.com/jason8745/llm-agent-trader/releases/latest) and double-click it, then say 「開始使用台股回測」. In Claude Code: `claude plugin marketplace add jason8745/llm-agent-trader` and `claude plugin install llm-agent-trader@llm-agent-trader`.

## 授權

MIT。dashboard 內含 [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) 5.2.1，採 Apache License 2.0（`src/trader/viewer/lightweight-charts.LICENSE`）。
