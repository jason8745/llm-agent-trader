### Claude

第一次呼叫工具時，系統會下載回測引擎所需的套件（pandas、numpy、yfinance，約 50 MB）。依網路狀況，可能需要一至數分鐘，之後每次呼叫只需數秒。

### Tool call: `ToolSearch`

```json
{
  "query": "select:mcp__plugin_llm-agent-trader_trader__search_stock,mcp__plugin_llm-agent-trader_trader__open_dashboard",
  "max_results": 2
}
```

<details><summary>Tool result</summary>

```

```
</details>

### Tool call: `mcp__plugin_llm-agent-trader_trader__search_stock`

```json
{
  "query": "台積電"
}
```

<details><summary>Tool result</summary>

```
{"result":"| 代號 | 名稱 | 市場 | 類別 |\n|---|---|---|---|\n| 2330.TW | 台積電 | 上市 | 股票 |"}
```
</details>

### Tool call: `mcp__plugin_llm-agent-trader_trader__open_dashboard`

```json
{}
```

<details><summary>Tool result</summary>

```
{"result":"檢視器：http://127.0.0.1:8766/\n已在預設瀏覽器開啟。新的回測完成後，頁面會自動顯示，不需要重新整理。"}
```
</details>

### Claude

**1. 工具確認**

已查詢「台積電」，結果回傳 `2330.TW`（台積電，上市股票）。回測工具可以正常使用。

**2. 工作資料夾**

策略與回測紀錄都存放在目前的資料夾：

- 策略檔：`strategies/<名稱>.py`
- 回測紀錄：`.trader/runs.db`

建議每個研究主題使用一個資料夾。下次在同一個資料夾啟動 Claude Code，即可延續先前的研究。

**3. 檢視器**

檢視器已在預設瀏覽器開啟，網址為 http://127.0.0.1:8766/ 。

- 檢視器列出此資料夾的所有回測。每筆回測會顯示：
  - 本次驗證的假設
  - 樣本內、樣本外與買進並持有基準的報酬率
  - K 線與買賣點
  - 權益曲線、成交明細與策略原始碼
- 建議將檢視器放在 Claude Code 旁邊。新的回測完成後會在數秒內自動顯示，不需要重新整理頁面。
- 檢視器會隨 Claude Code 結束而停止。之後只要請我打開 dashboard，即可再次開啟。

**4. 研究流程**

1. 您描述想研究的標的、期間與交易想法。
2. 我撰寫策略檔，並在每次回測時寫明本次要驗證的假設。
3. 每次回測將資料分成兩段：
   - 前 70% 為樣本內，後 30% 為樣本外，兩段都與買進並持有基準比較。
   - 調整參數只依據樣本內的結果。
   - 樣本外的資料不參與調整，用來檢驗策略在這段期間是否仍然有效。
4. 檢視器顯示「⚑」時，代表樣本內年化報酬率比樣本外高出 15 個百分點以上，策略可能過度擬合。

**5. 請提出研究主題**

以下為範例需求：

- 我想研究台積電的趨勢追蹤策略。請使用 2023-01-01 至 2025-12-31 的資料，設計一個均線類策略並回測，至少迭代兩次，最後告訴我結論。
- 請以 0050 測試 RSI 超賣進場、超買出場的策略，期間為 2020-01-01 至 2025-12-31，並與買進並持有基準比較。
- 請比較聯發科在 2022-01-01 至 2025-12-31 期間，均線交叉與布林通道兩種策略的樣本外表現。

請問您想研究哪一個主題？請告訴我標的、期間與交易想法。

## Automated checks

- number not found in any tool result: 50
- number not found in any tool result: 70%
- number not found in any tool result: 30%
- number not found in any tool result: 15
- number not found in any tool result: 2023
- number not found in any tool result: -01
- number not found in any tool result: -01
- number not found in any tool result: 2025
- number not found in any tool result: -12
- number not found in any tool result: -31
- number not found in any tool result: 0050
- number not found in any tool result: 2020
- number not found in any tool result: -01
- number not found in any tool result: -01
- number not found in any tool result: 2025
- number not found in any tool result: -12
- number not found in any tool result: -31
- number not found in any tool result: 2022
- number not found in any tool result: -01
- number not found in any tool result: -01
- number not found in any tool result: 2025
- number not found in any tool result: -12
- number not found in any tool result: -31
