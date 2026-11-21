// Layout only. Every number shown as text arrives pre-formatted from trader.fmt; the single
// exception is groupDigits, which adds thousands separators to chart axis and crosshair labels.
const LC = window.LightweightCharts;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const tone = (s) => (String(s).startsWith("+") ? "up" : String(s).startsWith("-") ? "down" : "");
const FLAG = '<span class="flag" title="策略開發期間的年化報酬率較策略執行期間高出逾 15 個百分點">⚑</span>';
const REGIME = { up: "rgba(239,68,68,0.10)", down: "rgba(34,197,94,0.10)", range: "rgba(148,163,184,0.08)" };
const EXEC_BAND = "rgba(240,180,41,0.06)";

function groupDigits(value, decimals) {
  const scale = 10 ** decimals;
  const n = Math.round(Math.abs(value) * scale);
  const int = String(Math.floor(n / scale)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = decimals ? "." + String(n % scale).padStart(decimals, "0") : "";
  return (value < 0 && n ? "-" : "") + int + frac;
}

const fmtPrice = { type: "custom", minMove: 0.01, formatter: (v) => groupDigits(v, 2) };
const fmtVolume = { type: "custom", minMove: 1, formatter: (v) => groupDigits(v, 0) };
const fmtPct = { type: "custom", minMove: 0.01, formatter: (v) => groupDigits(v, 2) + "%" };

let tree = [], study = null, run = null, charts = [], openStocks = null, signature = "";
let drawerTab = "fills", drawerOpen = false;

const allRuns = () => tree.flatMap((s) => s.studies.flatMap((st) => st.runs));
const newestRun = () => allRuns().reduce((a, b) => (!a || b.id > a.id ? b : a), null);
const row = (rows, label) => rows.find((m) => m.label === label) || {};

// ---------- left: study tree ----------
function renderTree() {
  const el = $("tree");
  if (!tree.length) { el.innerHTML = '<p class="empty">尚無回測紀錄。</p>'; return; }
  if (!openStocks) openStocks = new Set(tree.map((s) => s.symbol));
  el.innerHTML = tree.map((s) => `
    <details class="stock" data-symbol="${esc(s.symbol)}" ${openStocks.has(s.symbol) ? "open" : ""}>
      <summary><span class="fold">▸</span><b>${esc(s.label)}</b><span class="cnt">${s.studies.length} 個研究</span></summary>
      ${s.studies.map((st) => `
        <section class="study" aria-current="${!!study && study.key === st.key}">
          <button class="sh" data-study="${esc(st.key)}"><span class="sname">${esc(st.strategy)}</span>
            ${st.final_run_id ? '<span class="badge done">已定稿</span>' : '<span class="badge">研究中</span>'}
            <span class="per">開發 ${esc(st.dev)}<br>執行 ${esc(st.exec)}</span></button>
          <ol class="steps">${st.runs.map((r) => `
            <li><button data-run="${r.id}" aria-current="${!!run && run.id === r.id}"><span class="dot">${r.n}</span>
              <span><span class="hyp">${esc(r.hypothesis)}</span>
              <span class="m">開發 <b class="${tone(r.dev_ret)}">${esc(r.dev_ret)}</b> · 執行 <b class="${tone(r.exec_ret)}">${esc(r.exec_ret)}</b>${r.overfit ? " " + FLAG : ""}${r.final ? ' <span class="badge done">定稿</span>' : ""}</span></span>
            </button></li>`).join("")}</ol>
        </section>`).join("")}
    </details>`).join("");
}

// ---------- center: context, highlight, charts, drawer ----------
function renderCenter() {
  const st = study, r = run, M = r.metrics;
  $("ctx").innerHTML = `
    <div class="row"><h1>${esc(st.label)}</h1><span class="sname">${esc(st.strategy)}</span>
      ${st.final_run_id ? '<span class="badge done">已定稿</span>' : '<span class="badge">研究中</span>'}
      <span class="pchip">策略開發期間 <b>${esc(st.dev)}</b></span><span class="pchip x">策略執行期間 <b>${esc(st.exec)}</b></span></div>
    <div class="seg" role="group" aria-label="切換迭代">${st.iterations.map((it) => `
      <button data-run="${it.id}" aria-pressed="${it.id === r.id}"><span class="t">第 ${it.n} 次 · ${esc(it.params)}${it.final ? ' <span class="badge done">定稿</span>' : ""}${it.overfit ? FLAG : ""}</span>
        <span class="k">開發 <b class="${tone(it.dev_ret)}">${esc(it.dev_ret)}</b></span><span class="k">執行 <b class="${tone(it.exec_ret)}">${esc(it.exec_ret)}</b></span></button>`).join("")}</div>`;
  const ret = row(M, "總報酬率"), mdd = row(M, "最大回撤"), sharpe = row(M, "Sharpe 比率（無風險利率 0）");
  $("hl").innerHTML = `
    <p class="q"><small>第 ${r.n} 次迭代的假設 · ${esc(r.diff)}</small>${esc(r.hypothesis)}</p>
    <div class="kpis">
      <div class="kpi main"><small>策略執行期間報酬率</small><div class="v ${tone(ret.exec)}">${esc(ret.exec)}</div><div class="s">買進並持有 ${esc(ret.bh_exec)}</div></div>
      <div class="kpi"><small>策略開發期間報酬率</small><div class="v ${tone(ret.dev)}">${esc(ret.dev)}</div><div class="s">買進並持有 ${esc(ret.bh_dev)}</div></div>
      <div class="kpi"><small>策略執行期間最大回撤</small><div class="v ${tone(mdd.exec)}">${esc(mdd.exec)}</div><div class="s">買進並持有 ${esc(mdd.bh_exec)}</div></div>
      <div class="kpi"><small>策略執行期間 Sharpe 比率</small><div class="v">${esc(sharpe.exec)}</div><div class="s">策略開發期間 ${esc(sharpe.dev)}</div></div>
    </div>
    ${r.overfit_note ? `<p class="note">${esc(r.overfit_note)}</p>` : ""}`;
  $("lg1").innerHTML = `<span class="up">▲ 買進</span><span class="down">▼ 賣出</span>
    <span><i class="sw" style="background:${REGIME.up}"></i>上漲段</span><span><i class="sw" style="background:${REGIME.range}"></i>盤整段</span>
    <span><i class="sw" style="background:${REGIME.down}"></i>下跌段</span><span><i class="ln xline"></i>策略執行期間起點</span>`;
  renderDrawer();
  drawCharts(r);
}

function table(head, body) {
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderDrawer() {
  const tabs = [["fills", "成交明細"], ["trips", "已平倉交易"], ["dd", "最深回撤"], ["regimes", "盤勢分段"], ["code", "策略原始碼"]];
  $("drawer").innerHTML = `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" data-tab="${k}" aria-selected="${drawerOpen && drawerTab === k}">${l}</button>`).join("")}
    <span class="sp"></span><button data-tab="toggle" aria-expanded="${drawerOpen}">${drawerOpen ? "收合 ▾" : "展開 ▴"}</button></div>
    ${drawerOpen ? `<div class="body">${drawerBody(run)}</div>` : ""}`;
}

function drawerBody(r) {
  if (drawerTab === "code") return `<pre>${esc(r.source)}</pre><p class="meta">策略原始碼 sha256：${esc(r.source_sha)}<br>資料指紋：${esc(r.data_sha)}</p>`;
  if (drawerTab === "regimes") {
    return `<p class="mu" style="margin:6px 0">${esc(r.regime_rules)}</p>` + table('<th>盤勢</th><th>期間</th><th class="n">交易日數</th><th class="n">股價漲跌幅</th><th class="n">策略報酬率</th><th class="n">策略持倉時間比例</th>',
      r.regimes.map((g) => `<tr><td><span class="rdot ${g.kind}"></span>${esc(g.label)}</td><td>${esc(g.start)} 至 ${esc(g.end)}</td><td class="n">${esc(g.bars)}</td><td class="n ${tone(g.price_change)}">${esc(g.price_change)}</td><td class="n b ${tone(g.strategy)}">${esc(g.strategy)}</td><td class="n">${esc(g.exposure)}</td></tr>`).join(""));
  }
  if (drawerTab === "dd") {
    const head = '<th>高點日期</th><th>低點日期</th><th class="n">回撤幅度</th><th>回復日期</th><th class="n">持續交易日</th>';
    const rows = (list) => list.map((d) => `<tr><td>${esc(d.peak)}</td><td>${esc(d.trough)}</td><td class="n down">${esc(d.depth)}</td><td>${esc(d.recovery)}</td><td class="n">${esc(d.bars)}</td></tr>`).join("") || '<tr><td colspan="5" class="mu">無回撤。</td></tr>';
    return `<h4>策略開發期間</h4>${table(head, rows(r.drawdowns.dev))}<h4>策略執行期間</h4>${table(head, rows(r.drawdowns.exec))}`;
  }
  if (drawerTab === "trips") {
    if (!r.trips.length) return '<p class="empty">無已平倉交易。</p>';
    return table('<th>期間</th><th>進場</th><th>出場</th><th class="n">持有交易日</th><th class="n">已實現損益</th>',
      r.trips.map((t) => `<tr><td>${esc(t.period)}</td><td>${esc(t.entry)}</td><td>${esc(t.exit)}</td><td class="n">${esc(t.held)}</td><td class="n ${t.win ? "up" : "down"}">${esc(t.pnl)}</td></tr>`).join(""));
  }
  if (!r.fills.length) return '<p class="empty">無成交。</p>';
  return table('<th>期間</th><th>日期</th><th>方向</th><th class="n">價格</th><th class="n">股數</th><th class="n">成交金額</th><th class="n">手續費與稅</th>',
    r.fills.map((f) => `<tr><td>${esc(f.period)}</td><td>${esc(f.date)}</td><td class="${f.buy ? "up" : "down"}">${esc(f.side)}</td><td class="n">${esc(f.price)}</td><td class="n">${esc(f.shares)}</td><td class="n">${esc(f.gross)}</td><td class="n">${esc(f.fees)}</td></tr>`).join(""));
}

// ---------- charts ----------
class Overlay {
  constructor({ bands = [], line = null, labels = [] }) { Object.assign(this, { bands, line, labels }); }
  attached({ chart }) { this.chart = chart; }
  paneViews() {
    return [{
      zOrder: () => "bottom",
      renderer: () => ({
        draw: (target) => target.useBitmapCoordinateSpace((s) => {
          if (!this.chart) return;
          const ts = this.chart.timeScale(), k = s.horizontalPixelRatio, ctx = s.context, h = s.bitmapSize.height;
          for (const b of this.bands) {
            const x1 = ts.timeToCoordinate(b.start), x2 = ts.timeToCoordinate(b.end);
            if (x1 === null || x2 === null) continue;
            ctx.fillStyle = b.color;
            ctx.fillRect(Math.round(x1 * k), 0, Math.max(1, Math.round((x2 - x1) * k)), h);
          }
          if (this.line) {
            const x = ts.timeToCoordinate(this.line);
            if (x !== null) {
              ctx.strokeStyle = "rgba(240,180,41,0.85)"; ctx.setLineDash([6 * k, 4 * k]); ctx.lineWidth = k;
              ctx.beginPath(); ctx.moveTo(Math.round(x * k) + 0.5, 0); ctx.lineTo(Math.round(x * k) + 0.5, h); ctx.stroke(); ctx.setLineDash([]);
            }
          }
          for (const l of this.labels) {
            const x1 = ts.timeToCoordinate(l.start), x2 = ts.timeToCoordinate(l.end);
            if (x1 === null || x2 === null || x2 - x1 < (l.min || 60)) continue;
            ctx.save();
            ctx.beginPath(); ctx.rect(x1 * k, 0, (x2 - x1 - 4) * k, 40 * k); ctx.clip();
            ctx.font = `${11 * k}px -apple-system,"PingFang TC",sans-serif`;
            ctx.fillStyle = l.color || "rgba(230,232,235,0.85)";
            ctx.fillText(l.text, (x1 + 6) * k, 14 * k);
            if (l.sub) { ctx.font = `${10.5 * k}px ui-monospace,Menlo,monospace`; ctx.fillStyle = "rgba(138,147,160,0.95)"; ctx.fillText(l.sub, (x1 + 6) * k, 28 * k); }
            ctx.restore();
          }
        }),
      }),
    }];
  }
}

function makeChart(el) {
  return LC.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#11141a" }, textColor: "#8a93a0", fontSize: 11, attributionLogo: false, panes: { separatorColor: "#252b34" } },
    grid: { vertLines: { color: "#1b2027" }, horzLines: { color: "#1b2027" } },
    rightPriceScale: { borderColor: "#252b34", minimumWidth: 86 },
    timeScale: { borderColor: "#252b34", minBarSpacing: 0.05 },
    localization: { locale: "zh-TW", dateFormat: "yyyy-MM-dd" },
    crosshair: { mode: 0 },
  });
}

const ser = (dates, values) => dates.map((t, i) => ({ time: t, value: values[i] }));

function drawCharts(r) {
  charts.forEach((c) => c.remove());
  charts = [];
  if (!LC) { $("c1").textContent = "圖表元件載入失敗。"; return; }
  const c = r.chart, x0 = c.exec_dates[0], xEnd = c.exec_dates[c.exec_dates.length - 1];
  const M = r.metrics, ret = row(M, "總報酬率"), mdd = row(M, "最大回撤");

  const price = makeChart($("c1"));
  const candles = price.addSeries(LC.CandlestickSeries, { upColor: "#ef4444", downColor: "#22c55e", borderVisible: false, wickUpColor: "#ef4444", wickDownColor: "#22c55e", priceFormat: fmtPrice });
  candles.setData(c.dates.map((t, i) => ({ time: t, open: c.open[i], high: c.high[i], low: c.low[i], close: c.close[i] })));
  candles.attachPrimitive(new Overlay({
    bands: c.regimes.map((g) => ({ start: g.start, end: g.end, color: REGIME[g.kind] })),
    line: x0,
    labels: r.regimes.map((g) => ({ start: g.start, end: g.end, text: g.label, sub: g.price_change, min: 70 })),
  }));
  LC.createSeriesMarkers(candles, c.markers.map((m) => m.side === "BUY"
    ? { time: m.date, position: "belowBar", color: "#ef4444", shape: "arrowUp" }
    : { time: m.date, position: "aboveBar", color: "#22c55e", shape: "arrowDown" }));
  const vol = price.addSeries(LC.HistogramSeries, { priceFormat: fmtVolume, priceLineVisible: false, lastValueVisible: false }, 1);
  vol.setData(c.dates.map((t, i) => ({ time: t, value: c.volume[i], color: c.close[i] >= c.open[i] ? "rgba(239,68,68,0.5)" : "rgba(34,197,94,0.5)" })));
  price.panes()[1].setHeight(64);

  const dates2 = [...c.dev_dates, ...c.exec_dates];
  const cum = makeChart($("c2"));
  const strat = cum.addSeries(LC.LineSeries, { color: "#f0b429", lineWidth: 2, priceLineVisible: false, priceFormat: fmtPct });
  strat.setData(ser(dates2, c.cum));
  cum.addSeries(LC.LineSeries, { color: "#94a3b8", lineWidth: 1.5, lineStyle: 2, priceLineVisible: false, priceFormat: fmtPct }).setData(ser(dates2, c.cum_bh));
  strat.attachPrimitive(new Overlay({
    bands: [{ start: x0, end: xEnd, color: EXEC_BAND }], line: x0,
    labels: [
      { start: c.dev_dates[0], end: c.dev_dates[c.dev_dates.length - 1], text: "策略開發期間", sub: `策略 ${ret.dev}　買進並持有 ${ret.bh_dev}` },
      { start: x0, end: xEnd, text: "策略執行期間", sub: `策略 ${ret.exec}　買進並持有 ${ret.bh_exec}`, color: "#f0b429" },
    ],
  }));

  const dd = makeChart($("c3"));
  const area = (data, strong) => {
    const a = dd.addSeries(LC.AreaSeries, { lineColor: strong ? "#22c55e" : "rgba(34,197,94,0.45)", topColor: "rgba(34,197,94,0.03)", bottomColor: strong ? "rgba(34,197,94,0.4)" : "rgba(34,197,94,0.14)", lineWidth: strong ? 1.5 : 1, priceLineVisible: false, lastValueVisible: false, priceFormat: fmtPct, invertFilledArea: true });
    a.setData(data);
    return a;
  };
  area(ser(c.dev_dates, c.dd_dev), false).attachPrimitive(new Overlay({
    bands: [{ start: x0, end: xEnd, color: EXEC_BAND }], line: x0,
    labels: [
      { start: c.dev_dates[0], end: c.dev_dates[c.dev_dates.length - 1], text: `最大回撤 ${mdd.dev}` },
      { start: x0, end: xEnd, text: `最大回撤 ${mdd.exec}`, color: "#f0b429" },
    ],
  }));
  area(ser(c.exec_dates, c.dd_exec), true);

  const mine = [price, cum, dd];
  charts = mine;
  mine.forEach((ch) => ch.subscribeCrosshairMove((p) => readout(c, p.time)));
  readout(c, null);
  // Fit after layout so each chart has its real width, then start syncing the visible range.
  requestAnimationFrame(() => {
    if (charts !== mine) return;
    mine.forEach((ch) => ch.timeScale().fitContent());
    let syncing = false;
    for (const ch of mine) {
      ch.timeScale().subscribeVisibleTimeRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        for (const other of mine) if (other !== ch) other.timeScale().setVisibleRange(range);
        syncing = false;
      });
    }
  });
}

function readout(c, time) {
  const d = time || c.dates[c.dates.length - 1];
  const i = c.dates.indexOf(d);
  $("r1").innerHTML = i < 0 ? "" : `<b>${d}</b>　開 <b>${groupDigits(c.open[i], 2)}</b>　高 <b>${groupDigits(c.high[i], 2)}</b>　低 <b>${groupDigits(c.low[i], 2)}</b>　收 <b>${groupDigits(c.close[i], 2)}</b>　量 <b>${groupDigits(c.volume[i], 0)}</b>`;
  const dates2 = [...c.dev_dates, ...c.exec_dates], j = dates2.indexOf(d);
  $("r2").innerHTML = j < 0 ? "" : `策略 <b>${groupDigits(c.cum[j], 2)}%</b>　買進並持有 <b>${groupDigits(c.cum_bh[j], 2)}%</b>`;
  const dds = [...c.dd_dev, ...c.dd_exec];
  $("r3").innerHTML = j < 0 ? "" : `回撤 <b>${groupDigits(dds[j], 2)}%</b>`;
}

// ---------- right: conclusion and scorecard ----------
function renderRight() {
  const st = study, r = run, M = r.metrics, T = r.trade_metrics, con = st.conclusion;
  const finalIt = st.iterations.find((it) => it.final);
  const ann = row(M, "年化報酬率");
  const scoreRows = [["報酬率", "總報酬率"], ["年化報酬率", "年化報酬率"], ["最大回撤", "最大回撤"], ["Sharpe 比率", "Sharpe 比率（無風險利率 0）"]]
    .map(([l, k]) => { const m = row(M, k); return `<div class="lb">${l}</div><div class="v ${tone(m.dev)}">${esc(m.dev)}<small>${esc(m.bh_dev)}</small></div><div class="v x b ${tone(m.exec)}">${esc(m.exec)}<small>${esc(m.bh_exec)}</small></div>`; }).join("");
  const trades = row(T, "交易次數");
  $("right").innerHTML = `
    <section class="card"><h3>結論${con ? `<span class="badge done">已定稿 ${esc(st.finalized_at)}</span>` : '<span class="badge">研究中</span>'}</h3>
      ${con ? `<p class="verdict">${esc(con.verdict)}</p>${finalIt && finalIt.id !== r.id ? `<p class="mu" style="margin-top:6px;font-size:12px">結論對應第 ${finalIt.n} 次迭代（定稿）。</p>` : ""}`
        : '<p class="mu">尚未定稿。Claude 定稿時會寫入一句總結與數組發現與洞察。</p>'}</section>
    <section class="card"><h3>兩段期間對照<span class="mu" style="font-weight:400">策略／買進並持有</span></h3>
      <div class="score"><div class="hd"></div><div class="hd v">策略開發期間</div><div class="hd v x">策略執行期間</div>${scoreRows}
        <div class="lb">交易次數</div><div class="v">${esc(trades.dev)}</div><div class="v x b">${esc(trades.exec)}</div></div>
      ${r.overfit
        ? `<div class="check warn"><span class="ic">⚑</span><span>${esc(r.overfit_note)}</span></div>`
        : `<div class="check"><span class="ic">✓</span><span>過度擬合檢查：策略開發期間年化報酬率 ${esc(ann.dev)}，策略執行期間 ${esc(ann.exec)}，未達警示門檻（開發期間高出逾 15 個百分點）。</span></div>`}</section>
    ${con && con.findings.length ? `<section class="card"><h3>發現與洞察</h3>${con.findings.map((f, i) => `
      <div class="fi"><div class="lab"><span class="n">${i + 1}</span>發現</div><p>${esc(f.finding)}</p><div class="ins"><b>洞察</b>${esc(f.insight)}</div></div>`).join("")}</section>` : ""}
    <section class="card"><h3>盤勢表現<span class="mu" style="font-weight:400">股價漲跌幅／策略報酬率</span></h3>
      <div class="reg">${r.regimes.map((g) => `<span><span class="rdot ${g.kind}"></span>${esc(g.label)}<small>${esc(g.start)} 至 ${esc(g.end)}</small></span>
        <span class="vals"><span class="${tone(g.price_change)}">${esc(g.price_change)}</span> / <b class="${tone(g.strategy)}">${esc(g.strategy)}</b></span>`).join("")}</div></section>
    <section class="card"><details class="more"><summary>完整績效指標與交易統計</summary>
      ${table('<th></th><th class="n">開發</th><th class="n">執行</th><th class="n">持有（開發）</th><th class="n">持有（執行）</th>', M.map((m) => `<tr><th>${esc(m.label)}</th><td class="n ${tone(m.dev)}">${esc(m.dev)}</td><td class="n b ${tone(m.exec)}">${esc(m.exec)}</td><td class="n mu">${esc(m.bh_dev)}</td><td class="n mu">${esc(m.bh_exec)}</td></tr>`).join(""))}
      ${table('<th></th><th class="n">開發</th><th class="n">執行</th>', T.map((m) => `<tr><th>${esc(m.label)}</th><td class="n ${tone(m.dev)}">${esc(m.dev)}</td><td class="n b ${tone(m.exec)}">${esc(m.exec)}</td></tr>`).join(""))}
    </details></section>`;
}

// ---------- navigation ----------
async function getJSON(url) {
  const res = await fetch(url);
  return res.ok ? res.json() : null;
}

function renderAll() {
  renderTree();
  if (!study || !run) return renderEmpty();
  renderCenter();
  renderRight();
}

async function openStudy(key, runId, push = true) {
  const st = await getJSON(`/api/studies/${encodeURIComponent(key)}`);
  if (!st) return renderEmpty();
  study = st;
  const id = runId ?? st.final_run_id ?? st.iterations[st.iterations.length - 1].id;
  run = await getJSON(`/api/runs/${id}`);
  if (push) history.pushState(null, "", runId ? `/runs/${id}` : `/studies/${key}`);
  renderAll();
}

async function openRun(id, push = true) {
  const r = await getJSON(`/api/runs/${id}`);
  if (!r) return renderEmpty();
  if (!study || study.key !== r.study_key) return openStudy(r.study_key, id, push);
  run = r;
  if (push) history.pushState(null, "", `/runs/${id}`);
  renderAll();
}

function renderEmpty() {
  charts.forEach((c) => c.remove());
  charts = [];
  $("ctx").innerHTML = "";
  $("hl").innerHTML = `<div class="empty"><p>尚無回測紀錄。</p><p>請在 Claude Code 中討論策略並執行回測；新的回測完成後，此頁面會自動顯示。</p></div>`;
  $("right").innerHTML = "";
  $("drawer").innerHTML = "";
}

function sig(t) {
  return JSON.stringify(t.map((s) => s.studies.map((st) => [st.key, st.final_run_id, st.runs.map((r) => r.id)])));
}

async function poll() {
  const t = await getJSON("/api/tree").catch(() => null);
  if (!t || sig(t) === signature) return;
  const before = newestRun();
  const following = !run || (before && run.id === before.id);
  const finalBefore = study && study.final_run_id;
  tree = t;
  signature = sig(t);
  if (openStocks) t.forEach((s) => openStocks.add(s.symbol));
  const latest = newestRun();
  const go = async (id) => {
    study = null; // reload the study so its iteration list and conclusion include the change
    await openRun(id, false);
    history.replaceState(null, "", `/runs/${id}`);
  };
  if (following && latest && (!before || latest.id !== before.id)) return go(latest.id);
  const mine = study && t.flatMap((s) => s.studies).find((st) => st.key === study.key);
  if (following && mine && mine.final_run_id && mine.final_run_id !== finalBefore) return go(mine.final_run_id);
  if (study) {
    const fresh = await getJSON(`/api/studies/${encodeURIComponent(study.key)}`);
    if (fresh) { study = fresh; renderCenter(); renderRight(); }
  }
  renderTree();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-run],[data-study],[data-tab]");
  if (!t) return;
  if (t.dataset.tab) {
    if (t.dataset.tab === "toggle") drawerOpen = !drawerOpen;
    else if (drawerOpen && drawerTab === t.dataset.tab) drawerOpen = false;
    else { drawerTab = t.dataset.tab; drawerOpen = true; }
    return renderDrawer();
  }
  if (t.dataset.study) return openStudy(t.dataset.study);
  openRun(Number(t.dataset.run));
});

document.addEventListener("toggle", (e) => {
  const d = e.target;
  if (!d.matches || !d.matches("details.stock") || !openStocks) return;
  d.open ? openStocks.add(d.dataset.symbol) : openStocks.delete(d.dataset.symbol);
}, true);

window.addEventListener("popstate", () => route(false));

async function route(push) {
  const p = location.pathname;
  let m;
  if ((m = p.match(/^\/runs\/(\d+)$/))) return openRun(Number(m[1]), push);
  if ((m = p.match(/^\/studies\/([\w-]+)$/))) return openStudy(m[1], undefined, push);
  const latest = newestRun();
  if (latest) return openRun(latest.id, push);
  renderTree();
  renderEmpty();
}

(async () => {
  const [info, t] = await Promise.all([getJSON("/api/info"), getJSON("/api/tree")]);
  $("ws").textContent = info ? info.workspace : "";
  if (info && info.legacy_runs) $("legacy").textContent = `另有 ${info.legacy_runs} 筆舊版回測未顯示（舊版以 70/30 切分，數字無法比較）`;
  tree = t || [];
  signature = sig(tree);
  await route(false);
  setInterval(poll, 2000);
})();
