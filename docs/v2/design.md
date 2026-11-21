# llm-agent-trader v2 設計文件

> 狀態：設計定案，待實作 · 2026-11-21
> 架構圖：[`architecture.html`](architecture.html) · 檢視器雛型：[`mockups/viewer.html`](mockups/viewer.html)

## 1. 定位

**Claude Code 是大腦，v2 是手。**

v2 是一套 code harness，將台股資料、MCP tools、回測引擎（Engine）與損益模組（Profit）串接起來。使用者與 Claude Code 討論交易策略後，由 Claude 撰寫策略程式碼，並直接在 harness 上回測。回測迴圈內不呼叫任何 LLM。

v1 的做法是由後端呼叫 LLM endpoint，在每個觸發事件上請模型做出買賣決策。v2 改為 agent 負責「撰寫策略」，引擎負責「確定性地執行」，與 WrenAI 中 LLM 產生宣告、引擎負責執行的分工一致。

## 2. v1 檢視摘要

| 問題 | 說明 | v2 處理方式 |
|---|---|---|
| `llm_strategy.py` 共 3501 行 | 指標、事件偵測、prompt、部位、進度推送、DB 寫入全部耦合在一起 | 刪除，職責改由 agent 與策略檔承擔 |
| LLM 僅是 endpoint | 無法自行查資料、修改策略、重跑回測 | 改由 Claude Code 透過 MCP 操作 |
| LLM 位於逐根 K 棒的決策迴圈 | 回測慢、成本高、結果不可重現，並有模型記憶歷史行情的洩漏風險 | 回測迴圈內不使用 LLM |
| `daily_feedback`、retrospective endpoint | 固定流程的事後分析 | 改由 agent 透過 `get_run` 分析 |

保留並移植：`backtesting/engine.py` 的撮合與績效計算概念、`utils/indicators.py`、資料抓取層、前端 lightweight-charts 圖表元件。

## 3. 決策紀錄

| # | 決策 | 定案 |
|---|---|---|
| Q1 | Agent 角色 | 策略作者兼分析師；回測迴圈內不使用 LLM |
| Q2 | 整合介面 | MCP server（stdio），同一套函式另提供 CLI |
| Q3 | Web UI | 唯讀檢視器；對話在 Claude Code 內進行 |
| Q4 | 目標使用者 | 開源使用者；已安裝 Claude Code，不需另設 LLM API key |
| Q5 | 過渡方式 | v1 封存於 `archive/v1` 分支與 `v1` tag；master 經由逐一 PR 改為 v2，每個 PR 附驗證證據 |
| Q6 | 市場範圍 | 單一標的、日 K |
| Q7 | 策略格式 | Python 檔，事件驅動 `on_bar(hist, pos, p) -> 目標持倉比例 0–1` |
| Q8 | 策略與結果存放 | 策略存放於使用者 workspace 的 `strategies/*.py`；每次 run 存入 SQLite，含策略原始碼快照與 hash |
| Q9 | 策略執行 | 每次回測開一個 subprocess，設 timeout；不另做安全沙箱 |
| Q10 | MCP tools | `search_stock`、`get_ohlcv`、`run_backtest`、`get_run`、`list_runs`；指標以 Python 函式庫 `trader.ta` 提供 |
| Q11 | 發佈 | Python 套件，以 `uvx` 執行；檢視器以靜態檔案打包，使用者不需安裝 Node |
| Q12 | 防止過擬合 | 預設依 70/30 切分樣本內（IS）與樣本外（OOS），一律附 buy & hold 基準；過擬合警示比較年化報酬率（實作時修訂，見 decisions.tsv） |
| Q13 | Skill | 以 Claude Code plugin 發佈（skill + MCP 設定） |
| Q14 | `hypothesis` | `run_backtest` 必填，說明本次驗證的假設 |
| Q15 | 檢視器頁面 | run 列表與 run 詳情；不使用 SSE；不做多 run 對比頁 |
| Q16 | 撮合規則 | 收盤產生訊號、次一交易日開盤成交；只做多；整數股；不模擬滑價 |
| Q17 | 策略參數 | 模組層 `PARAMS`，可由 `run_backtest(params=...)` 覆寫；不提供參數掃描 tool |
| Q18 | 台股代號搜尋 | `search_stock` 以內建台股清單（TWSE/TPEx）依中文名稱或代號查詢 |
| Q19 | 市場預設 | 以台股為主，任何 yfinance 代號皆可回測；台股以外的標的費用預設為 0 |
| Q20 | 漲跌配色 | 固定紅漲綠跌 |
| Q21 | 檢視器版面 | B 版（左列表、右詳情）結合 A 版的假設時間軸；左欄可切換「時間軸／排行」 |
| Q22 | 圖表 | lightweight-charts v5；K 線與權益曲線在同一張 chart 的兩個 pane；移除 recharts |
| Q23 | 數字正確性 | 所有數字由程式計算並經測試驗證；顯示格式集中於單一 formatter；LLM 不得自行計算或改寫數字 |
| Q24 | LLM 用語 | 所有解釋使用正式書面語，遵循 skill 內的術語表 |

## 4. 系統組成

```
使用者 ──討論──▶ Claude Code（+ trader plugin skill）
                   │ 撰寫 strategies/*.py
                   │ MCP（stdio）
                   ▼
           ┌──── Harness（llm-agent-trader, uvx）────────────────┐
           │ MCP server ──spawn──▶ Engine + Profit ──▶ runs.db    │
           │      │                  │ import 策略檔     ▲        │
           │      └──query───────────┼──────────────────┘        │
           │                         ▼                   Viewer ──┘ ◀── 使用者瀏覽 /runs/:id
           │                   台股資料（yfinance .TW/.TWO、股票清單、本地快取）
           └──────────────────────────────────────────────────────┘
```

### 4.1 策略契約

```python
# strategies/ma_cross.py
"""ma_cross：均線黃金交叉，僅做多。"""
from trader import ta

PARAMS = {"fast": 10, "slow": 20}

def on_bar(hist, pos, p):
    # hist：截至當日收盤（含）的歷史資料；不可能取得未來資料
    # pos：目前持倉比例
    # 回傳：目標持倉比例，範圍 0.0–1.0
    fast = ta.sma(hist.close, p["fast"]).iloc[-1]
    slow = ta.sma(hist.close, p["slow"]).iloc[-1]
    return 1.0 if fast > slow else 0.0
```

- 指標資料不足時（暖機期），由策略自行處理 NaN；引擎將非有限值或超出 0–1 的回傳值視為錯誤並終止該次 run。
- 組合指標可寫成 `trader.ta` 內的函式供所有策略共用，或寫在單一策略檔內。

### 4.2 MCP tools

| Tool | 輸入 | 輸出 |
|---|---|---|
| `search_stock` | `query`（中文名稱或代號） | 符合的代號、名稱、市場別（上市／上櫃） |
| `get_ohlcv` | `symbol, start, end` | 日 K 資料（經本地快取） |
| `run_backtest` | `strategy, symbol, start, end, hypothesis, params?, cash?, fee?` | `run_id`、績效摘要（已格式化）、檢視器網址 |
| `get_run` | `run_id` | 交易明細、每日權益、參數、原始碼快照、績效 |
| `list_runs` | `strategy?, symbol?` | run 列表與 IS／OOS／B&H 摘要 |

### 4.3 撮合與費用

- 第 t 日收盤後呼叫 `on_bar`，目標部位於第 t+1 日開盤價成交。
- 只有當 `on_bar` 回傳的目標持倉比例與前一次不同時才調整部位；比例不變時不因價格變動而再平衡，避免每日微量交易。
- 目標股數為 floor(目標比例 × 開盤時權益 ÷ 開盤價)；買進時若現金不足以支付成交金額與手續費，買進可負擔的最大股數。
- 除息日（yfinance 的 `Dividends`）以前一日收盤持股數計入現金股利；股利所得稅與二代健保補充保費不在模擬範圍內。
- 只做多，持股為整數股（允許零股，不強制以 1000 股為單位）。
- 台股預設費用（`.TW`／`.TWO`）：
  - 手續費：成交金額 × 0.1425%，買賣皆收；未滿新臺幣 20 元以 20 元計；元以下無條件捨去。
  - 證券交易稅：賣出時收取，股票 0.3%、ETF（代號 00 開頭）0.1%；元以下無條件捨去。債券 ETF 的免稅優惠不在預設範圍內，可由 `fee` 覆寫。
  - 以上費率可由 `run_backtest(fee=...)` 覆寫。
- 其他市場預設費用為 0。

### 4.4 績效定義（Profit 模組）

設回測期間共 n 個交易日，權益序列為 E[0..n-1]，切分點 s = floor(0.7 × n)。

| 指標 | 定義 |
|---|---|
| 權益 E[t] | 現金[t] + 持股數[t] × 收盤價[t] |
| 總報酬率 | E[n-1] / 初始本金 − 1 |
| IS 報酬率 | E[s-1] / 初始本金 − 1 |
| OOS 報酬率 | E[n-1] / E[s-1] − 1 |
| 最大回撤（MDD） | 區間內 min(E[t] / 區間內截至 t 的最高值 − 1)，以負值表示；IS 與總計的起始值為初始本金，OOS 的起始值為 E[s-1] |
| 交易次數 | 已平倉的完整來回次數 |
| 勝率 | 已實現損益 > 0 的平倉次數 ÷ 交易次數；交易次數為 0 時顯示「—」 |
| Buy & hold | 第 0 日開盤以相同本金與費用規則買進並持有至最後一日，依相同區間計算 |
| 年化報酬率 | (1 + 區間報酬率)^(365.25 ÷ 區間日曆天數) − 1，分別計算 IS 與 OOS |
| 過擬合警示 ⚑ | IS 年化報酬率 − OOS 年化報酬率 > 15 個百分點（IS 期間較長，直接比較總報酬率會誤判在樣本外表現更佳的策略） |

IS 與 OOS 屬於同一次連續回測，部位會跨越切分點延續，並非兩次獨立回測。報酬率以初始本金為基準，因此 (1 + IS) × (1 + OOS) = 1 + 總報酬率恆成立，且 buy & hold 第 0 日的買進手續費會反映在報酬率中。回測至少需要 3 根 K 棒。

指標慣例與 TA-Lib 一致：回看期間未滿時為 NaN；EMA 以前 n 筆的簡單平均作為種子；RSI 與 ATR 使用 Wilder 平滑；MACD 的快線 EMA 種子與慢線對齊；布林通道使用母體標準差。`tests/fixtures/talib_reference.json` 由 TA-Lib 產生，作為參考值。

### 4.5 顯示格式（單一 formatter）

| 類型 | 格式 | 範例 |
|---|---|---|
| 報酬率、回撤 | 百分比，小數 2 位，正值帶 `+` | `+12.34%`、`-6.70%` |
| 金額 | 新臺幣整數，千分位 | `1,275,227` |
| 價格 | 小數 2 位 | `564.60` |
| 股數 | 整數，千分位 | `2,031` |
| 日期 | `YYYY-MM-DD` | `2025-11-11` |

資料一律以完整精度儲存，只在顯示時捨入。檢視器、MCP 回傳的格式化摘要、CLI 共用同一套格式規則。

### 4.6 檢視器

依 [`mockups/viewer.html`](mockups/viewer.html)：

- 左欄有兩種模式：「時間軸」（預設，依策略分組，逐步顯示假設與 IS／OOS／⚑）、「排行」（表格，可依 IS 或 OOS 排序）。
- 右欄為詳情：與上一版的參數差異、IS／OOS／B&H／交易與勝率四格指標、圖表、交易明細與策略原始碼分頁。
- 圖表使用 lightweight-charts v5，上方 pane 為 K 線與買賣標記，下方 pane 為策略權益與 buy & hold；OOS 區段以底色標示。
- 紅漲綠跌。

### 4.7 Skill：研究流程與用語

研究流程：

1. **討論**：釐清交易邏輯、標的、區間；以 `search_stock` 及 `get_ohlcv` 檢視資料。
2. **撰寫策略**：寫入 `strategies/<name>.py`，檔頭 docstring 說明策略假設。
3. **回測迭代**：僅依 IS 結果調整；每次 run 填寫 `hypothesis`。
4. **定稿**：檢視一次 OOS 並對照 B&H，向使用者提供檢視器連結與結論。

數字規範：

- 回覆中出現的每個數字都必須來自 tool 的輸出，並照原格式引用。
- 不得自行心算、換算或四捨五入。需要新的衍生數字時，應擴充 Profit 模組，不由 LLM 計算。

用語規範：

- 一律使用正式書面語，不使用口語、網路用語或語助詞。
- 術語統一如下：

| 使用 | 不使用 |
|---|---|
| 樣本內／樣本外 | 訓練段、測試段 |
| 報酬率 | 賺了、獲利多少趴 |
| 最大回撤 | 最多虧、跌最深 |
| 過度擬合 | 硬凹、背答案 |
| 進場／出場 | 上車、下車 |
| 買進並持有基準 | 躺平、抱著不動 |

`hypothesis` 欄位同樣適用上述規範。

## 5. 交接（pstack）

## Goal
建立 llm-agent-trader v2：一套供 Claude Code 等 agent 使用的台股回測 harness。agent 撰寫 Python 策略，由確定性的引擎與損益模組回測，結果呈現在唯讀檢視器上。目的是讓「與 agent 討論策略 → 撰寫 → 驗證」形成快速、可重現且數字可信的迴圈。

## Done means
- 執行 `claude mcp add trader -- uvx llm-agent-trader mcp`（或安裝 plugin）後，在新的 Claude Code session 內不設定任何 LLM API key，即可完成：以 `search_stock("台積電")` 取得 `2330.TW`、撰寫策略、`run_backtest`、開啟檢視器連結。
- 相同的策略原始碼、參數、標的、區間與資料，重複回測得到逐位元相同的績效。每個 run 記錄資料指紋，資料源修訂導致無法重現時可以被偵測。
- 策略在結構上無法取得第 t 日之後的資料，且部位於第 t+1 日開盤成交。測試以「偷看未來」的策略驗證其無法得利。
- 策略發生無窮迴圈、例外或回傳非法值時，該次 run 會在 timeout 內失敗並回傳明確錯誤訊息，MCP server 持續可用。
- 數字正確性由測試保證，以下每一項都有自動化測試：
  - 每日 E[t] = 現金[t] + 持股數[t] × 收盤價[t]
  - 期末權益 − 初始本金 = 已實現損益合計 + 未實現損益（扣除費用後）
  - (1 + IS 報酬率) × (1 + OOS 報酬率) = 1 + 總報酬率
  - 每筆手續費與證交稅符合 4.3 的費率、最低收費與捨去規則
  - 以手算 golden fixture 驗證所有 4.4 指標，誤差 ≤ 1e-9
- 除權息不會被計為策略虧損：以一段含除息日的 fixture 驗證，buy & hold 的報酬率與還原權值的計算結果一致。
- `trader.ta` 的每個指標都有參考值測試；新增指標時必須一併新增參考值測試，CI 才會通過。
- 檢視器、MCP 摘要與 CLI 顯示的數字全部經過同一個 formatter，並符合 4.5 的格式。同一個 run 在三處顯示的字串完全相同，由測試驗證。
- 檢視器符合 [`mockups/viewer.html`](mockups/viewer.html) 的版面與互動：時間軸／排行切換、參數差異標籤、IS／OOS 底色、買賣標記、紅漲綠跌。
- Skill 包含研究流程、數字規範與術語表（4.7）。實際對話中，agent 的回覆數字皆可在 tool 輸出中找到原文，用語不含術語表禁用詞。
- v1 保留於 `archive/v1` 分支與 `v1` tag；master 不含 `llm/` 目錄、LLM client、SSE 與 daily feedback 程式碼。

## Premises
- 使用者在自己的機器上執行；策略程式碼由使用者自己的 agent 撰寫，信任邊界為本機，不需要安全沙箱。
- 規模為單一使用者、單一標的日 K、約數年資料；每次回測應在數秒內完成。
- 資料源為 yfinance（`.TW`／`.TWO`）及 TWSE/TPEx 公開股票清單；資料源本身可能修訂或短暫失效。
- 目標使用者以台股為主，配色、費用與搜尋皆依台股設計。
- 由 repo 作者一人維護；依賴越少越好。

## Open prototypes
- （無。檢視器版面已以 `mockups/viewer.html` 雛型確認。）

## Out of scope
- 做空、融資融券、整張交易限制、滑價模型
- 多標的投資組合、分鐘 K、期貨
- 參數掃描 tool、多 run 對比頁
- 回測迴圈內呼叫 LLM
- 檢視器內嵌聊天介面
- Sharpe、年化報酬率等進階指標（之後加入時，同樣須有 golden fixture 測試）

### 交給 pstack

```text
/pstack:poteto-mode 依 docs/v2/design.md 建立 llm-agent-trader v2：供 Claude Code 使用的台股回測 harness（MCP tools + 確定性 Engine + Profit 模組 + 唯讀檢視器），agent 撰寫 on_bar 策略並回測. done means 依 design.md 第 5 節 Done means 全部通過，特別是數字不變式與 golden fixture 測試、無 look-ahead、單一 formatter、uvx 一行安裝. keep 本機信任邊界、單一使用者單一標的日 K、yfinance 與 TWSE/TPEx 資料源、台股優先、依賴最少、master 經由 PR 改為 v2、v1 封存於 archive/v1.
```
