### Tool call: `Skill`

```json
{
  "skill": "llm-agent-trader:trader"
}
```

<details><summary>Tool result</summary>

```
Launching skill: llm-agent-trader:trader
```
</details>

### Tool call: `ToolSearch`

```json
{
  "query": "select:mcp__plugin_llm-agent-trader_trader__search_stock",
  "max_results": 1
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

### Claude

開始回測之前，請先確認下列五項研究條件。

Q1 標的：2330.TW 台積電（上市股票）。
➡️ 建議：採用。

Q2 策略邏輯與初始參數：採用均線交叉策略，只做多。短期均線向上穿越長期均線時進場，向下穿越時出場。初始參數為 `fast = 20`、`slow = 60`。
➡️ 建議：採用。第一次回測以這組參數作為基準。後續至少再做兩次迭代，候選方向有兩個：一是調整均線期間，二是加入長期趨勢濾網（例如收盤價須高於 120 日均線）以減少盤整期間的反覆進出。每次迭代只依策略開發期間的結果調整。

Q3 策略開發期間：2023-01-01 至 2024-12-31。
➡️ 建議：採用。

Q4 策略執行期間：2025-01-01 至 2025-12-31。
➡️ 建議：以最後 12 個月作為策略執行期間。這段期間不參與任何參數調整，用來檢驗策略在未經調整的期間是否仍然有效。

Q5 初始資金與費用：初始資金為新臺幣 1,000,000 元。費用採台股預設：手續費 0.1425%（最低新臺幣 20 元），證券交易稅 0.3%。
➡️ 建議：採用。

五項全部採用建議時，回覆「yes」即可；需要修改時，請註明題號與修改內容。確認後即開始撰寫策略、回測與迭代，最後提出結論。

## Automated checks

- number not found in any tool result: 20
- number not found in any tool result: 60
- number not found in any tool result: 120
- number not found in any tool result: 2023
- number not found in any tool result: -01
- number not found in any tool result: -01
- number not found in any tool result: 2024
- number not found in any tool result: -12
- number not found in any tool result: -31
- number not found in any tool result: 2025
- number not found in any tool result: -01
- number not found in any tool result: -01
- number not found in any tool result: 2025
- number not found in any tool result: -12
- number not found in any tool result: -31
- number not found in any tool result: 12
- number not found in any tool result: 1,000,000
- number not found in any tool result: 0.1425%
- number not found in any tool result: 20
- number not found in any tool result: 0.3%
