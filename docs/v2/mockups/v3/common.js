const LC = window.LightweightCharts, M = window.MOCK;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const tone = (s) => (String(s).startsWith("+") ? "up" : String(s).startsWith("-") ? "down" : "");
const REGIME = { up: "rgba(239,68,68,0.10)", down: "rgba(34,197,94,0.10)", range: "rgba(148,163,184,0.08)" };
const FLAG = '<span class="flag">⚑</span>';
function groupDigits(value, decimals) {
  const scale = 10 ** decimals, n = Math.round(Math.abs(value) * scale);
  const int = String(Math.floor(n / scale)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (value < 0 && n ? "-" : "") + int + (decimals ? "." + String(n % scale).padStart(decimals, "0") : "");
}
const fmtPrice = { type: "custom", minMove: 0.01, formatter: (v) => groupDigits(v, 2) };
const fmtMoney = { type: "custom", minMove: 1, formatter: (v) => groupDigits(v, 0) };
const fmtPct = { type: "custom", minMove: 0.01, formatter: (v) => groupDigits(v, 2) + "%" };
function markdown(text) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return String(text).split("\n").filter((l) => l.trim()).map((l) => `<p>${inline(l.trim())}</p>`).join("");
}
class Bands {
  constructor(bands, line) { this.bands = bands; this.line = line; }
  attached({ chart }) { this.chart = chart; }
  paneViews() {
    return [{ zOrder: () => "bottom", renderer: () => ({ draw: (t) => t.useBitmapCoordinateSpace((s) => {
      const ts = this.chart.timeScale(), k = s.horizontalPixelRatio, c = s.context, h = s.bitmapSize.height;
      for (const b of this.bands) { const x1 = ts.timeToCoordinate(b.start), x2 = ts.timeToCoordinate(b.end); if (x1 === null || x2 === null) continue; c.fillStyle = b.color; c.fillRect(Math.round(x1 * k), 0, Math.max(1, Math.round((x2 - x1) * k)), h); }
      if (this.line) { const x = ts.timeToCoordinate(this.line); if (x === null) return; c.strokeStyle = "rgba(240,180,41,0.85)"; c.setLineDash([6 * k, 4 * k]); c.lineWidth = k; c.beginPath(); c.moveTo(Math.round(x * k) + 0.5, 0); c.lineTo(Math.round(x * k) + 0.5, h); c.stroke(); c.setLineDash([]); }
    }) }) }];
  }
}
function makeChart(el, extra = {}) {
  return LC.createChart(el, { autoSize: true, layout: { background: { type: "solid", color: "#11141a" }, textColor: "#8a93a0", fontSize: 11 },
    grid: { vertLines: { color: "#1b2027" }, horzLines: { color: "#1b2027" } }, rightPriceScale: { borderColor: "#252b34", minimumWidth: 86 },
    timeScale: { borderColor: "#252b34" }, localization: { locale: "zh-TW", dateFormat: "yyyy-MM-dd" }, crosshair: { mode: 0 }, ...extra });
}
const ser = (d, v) => d.map((t, i) => ({ time: t, value: v[i] }));
function drawPrice(el, c, { regimes = true, volume = true } = {}) {
  const ch = makeChart(el), x0 = c.exec_dates[0];
  const s = ch.addSeries(LC.CandlestickSeries, { upColor: "#ef4444", downColor: "#22c55e", borderVisible: false, wickUpColor: "#ef4444", wickDownColor: "#22c55e", priceFormat: fmtPrice });
  s.setData(c.dates.map((t, i) => ({ time: t, open: c.open[i], high: c.high[i], low: c.low[i], close: c.close[i] })));
  s.attachPrimitive(new Bands(regimes ? c.regimes.map((g) => ({ start: g.start, end: g.end, color: REGIME[g.kind] })) : [], x0));
  LC.createSeriesMarkers(s, c.markers.map((m) => m.side === "BUY" ? { time: m.date, position: "belowBar", color: "#ef4444", shape: "arrowUp" } : { time: m.date, position: "aboveBar", color: "#22c55e", shape: "arrowDown" }));
  if (volume) {
    s.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.26 } });
    const v = ch.addSeries(LC.HistogramSeries, { priceScaleId: "vol", priceFormat: fmtMoney, priceLineVisible: false, lastValueVisible: false });
    v.setData(c.dates.map((t, i) => ({ time: t, value: c.volume[i], color: c.close[i] >= c.open[i] ? "rgba(239,68,68,0.45)" : "rgba(34,197,94,0.45)" })));
    ch.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  }
  ch.timeScale().fitContent(); return ch;
}
function drawPnl(el, c, which = ["dev", "exec"]) {
  const ch = makeChart(el), line = (o) => ch.addSeries(LC.LineSeries, { priceLineVisible: false, lastValueVisible: false, priceFormat: fmtMoney, ...o });
  let first = null;
  for (const p of which) {
    const d = c[p + "_dates"], s = line({ color: "#f0b429", lineWidth: 2 }); s.setData(ser(d, c["pnl_" + p])); first ||= s;
    line({ color: "#64748b", lineWidth: 1, lineStyle: 2 }).setData(ser(d, c["bh_pnl_" + p]));
  }
  if (which.length === 2) first.attachPrimitive(new Bands([{ start: c.exec_dates[0], end: c.exec_dates.at(-1), color: "rgba(240,180,41,0.06)" }], c.exec_dates[0]));
  ch.timeScale().fitContent(); return ch;
}
function drawDD(el, c, which = ["dev", "exec"]) {
  const ch = makeChart(el); let first = null;
  for (const p of which) { const a = ch.addSeries(LC.AreaSeries, { lineColor: "#22c55e", topColor: "rgba(34,197,94,0.05)", bottomColor: "rgba(34,197,94,0.35)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceFormat: fmtPct, invertFilledArea: true }); a.setData(ser(c[p + "_dates"], c["dd_" + p])); first ||= a; }
  if (which.length === 2) first.attachPrimitive(new Bands([{ start: c.exec_dates[0], end: c.exec_dates.at(-1), color: "rgba(240,180,41,0.06)" }], c.exec_dates[0]));
  ch.timeScale().fitContent(); return ch;
}
function sync(charts) {
  let busy = false;
  for (const ch of charts) ch.timeScale().subscribeVisibleTimeRangeChange((r) => { if (busy || !r) return; busy = true; charts.forEach((o) => o !== ch && o.timeScale().setVisibleRange(r)); busy = false; });
}
function treeHTML(currentRun = 1) {
  return M.tree.map((s) => `<details class="stock" open><summary><span class="fold">▸</span><b>${esc(s.label)}</b><span class="cnt">${s.studies.length} 個研究</span></summary>
    ${s.studies.map((st) => `<div class="study ${st.key === "a1" ? "cur" : ""}"><div class="sh"><span class="sname">${esc(st.strategy)}</span>${st.final_run_id ? '<span class="badge done">已定稿</span>' : '<span class="badge">研究中</span>'}</div>
      <div class="per">開發 ${esc(st.dev)}<br>執行 ${esc(st.exec)}</div>
      <ol class="steps">${st.runs.map((r) => `<li class="${r.id === currentRun && st.key === "a1" ? "cur" : ""}"><span class="dot">${r.n}</span><span><span class="hyp">${esc(r.hypothesis)}</span><span class="m">開發 <b class="${tone(r.dev_ret)}">${esc(r.dev_ret)}</b> · 執行 <b class="${tone(r.exec_ret)}">${esc(r.exec_ret)}</b>${r.overfit ? " " + FLAG : ""}${r.final ? ' <span class="badge done">定稿</span>' : ""}</span></span></li>`).join("")}</ol></div>`).join("")}</details>`).join("");
}
function tableHTML(head, rows) { return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`; }
function metricsHTML(r) {
  return tableHTML('<th></th><th class="n">策略開發期間</th><th class="n">策略執行期間</th><th class="n">買進並持有（開發）</th><th class="n">買進並持有（執行）</th>',
    r.metrics.map((m) => `<tr><th>${esc(m.label)}</th><td class="n ${tone(m.dev)}">${esc(m.dev)}</td><td class="n ${tone(m.exec)} b">${esc(m.exec)}</td><td class="n mu">${esc(m.bh_dev)}</td><td class="n mu">${esc(m.bh_exec)}</td></tr>`).join(""));
}
function tradesHTML(r) {
  return tableHTML('<th></th><th class="n">策略開發期間</th><th class="n">策略執行期間</th>', r.trade_metrics.map((m) => `<tr><th>${esc(m.label)}</th><td class="n ${tone(m.dev)}">${esc(m.dev)}</td><td class="n ${tone(m.exec)} b">${esc(m.exec)}</td></tr>`).join(""));
}
function regimesHTML(r) {
  return tableHTML('<th>盤勢</th><th>期間</th><th class="n">交易日數</th><th class="n">股價漲跌幅</th><th class="n">策略報酬率</th><th class="n">策略持倉時間比例</th>',
    r.regimes.map((g) => `<tr><td><span class="rdot ${g.kind}"></span>${esc(g.label)}</td><td>${esc(g.start)} 至 ${esc(g.end)}</td><td class="n">${esc(g.bars)}</td><td class="n ${tone(g.price_change)}">${esc(g.price_change)}</td><td class="n ${tone(g.strategy)} b">${esc(g.strategy)}</td><td class="n">${esc(g.exposure)}</td></tr>`).join(""));
}
function iterHTML(st, cur = 1) {
  return tableHTML('<th class="n">#</th><th>假設</th><th>參數變化</th><th class="n">開發期間</th><th class="n">執行期間</th><th class="n">執行期間買進並持有</th><th class="n">執行期間最大回撤</th><th class="n">Sharpe</th><th class="n">交易</th><th></th>',
    st.iterations.map((it) => `<tr class="${it.id === cur ? "sel" : ""}"><td class="n">${it.n}</td><td class="wrap">${esc(it.hypothesis)}</td><td><span class="chip">${esc(it.diff)}</span></td><td class="n ${tone(it.dev_ret)}">${esc(it.dev_ret)}</td><td class="n ${tone(it.exec_ret)} b">${esc(it.exec_ret)}</td><td class="n">${esc(it.bh_exec_ret)}</td><td class="n">${esc(it.exec_mdd)}</td><td class="n">${esc(it.exec_sharpe)}</td><td class="n">${esc(it.exec_trades)}</td><td>${it.overfit ? FLAG : ""}${it.final ? '<span class="badge done">定稿</span>' : ""}</td></tr>`).join(""));
}
const legendRegimes = `<span><i class="sw" style="background:${REGIME.up}"></i>上漲段</span><span><i class="sw" style="background:${REGIME.range}"></i>盤整段</span><span><i class="sw" style="background:${REGIME.down}"></i>下跌段</span><span><i class="ln dash"></i>策略執行期間起點</span><span class="up">▲ 買進</span><span class="down">▼ 賣出</span>`;
