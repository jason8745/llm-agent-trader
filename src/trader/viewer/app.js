// Layout only. Every number shown as text arrives pre-formatted from trader.fmt; the single
// exception is groupDigits, which adds thousands separators to chart axis and crosshair labels.
const LC = window.LightweightCharts;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const tone = (s) => (String(s).startsWith("+") ? "up" : String(s).startsWith("-") ? "down" : "");
const FLAG = '<span class="flag" title="策略開發期間的年化報酬率較策略執行期間高出逾 15 個百分點">⚑</span>';
const REGIME = { up: "rgba(239,68,68,0.10)", down: "rgba(34,197,94,0.10)", range: "rgba(148,163,184,0.08)" };

function groupDigits(value, decimals) {
  const scale = 10 ** decimals;
  const n = Math.round(Math.abs(value) * scale);
  const int = String(Math.floor(n / scale)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = decimals ? "." + String(n % scale).padStart(decimals, "0") : "";
  return (value < 0 && n ? "-" : "") + int + frac;
}

let tree = [], study = null, run = null, charts = [], tab = "fills", openStocks = null, signature = "";

const allRuns = () => tree.flatMap((s) => s.studies.flatMap((st) => st.runs.map((r) => ({ ...r, key: st.key }))));
const newestRun = () => allRuns().reduce((a, b) => (!a || b.id > a.id ? b : a), null);

// ---------- tree ----------
function renderTree() {
  const el = $("tree");
  if (!tree.length) {
    el.innerHTML = '<p class="empty">尚無回測紀錄。</p>';
    return;
  }
  if (!openStocks) openStocks = new Set(tree.map((s) => s.symbol));
  el.innerHTML = tree.map((s) => `
    <details class="stock" data-symbol="${esc(s.symbol)}" ${openStocks.has(s.symbol) ? "open" : ""}>
      <summary><span class="folder">▸</span><b>${esc(s.label)}</b><span class="count">${s.studies.length} 個研究</span></summary>
      ${s.studies.map((st) => `
        <section class="study" aria-current="${study && study.key === st.key}">
          <button class="sh" data-study="${esc(st.key)}">
            <span class="sname">${esc(st.strategy)}</span>
            ${st.final_run_id ? '<span class="badge done">已定稿</span>' : '<span class="badge">研究中</span>'}
            <span class="periods">開發 ${esc(st.dev)}<br>執行 ${esc(st.exec)}</span>
          </button>
          <ol class="steps">${st.runs.map((r) => `
            <li><button data-run="${r.id}" aria-current="${run && run.id === r.id}">
              <span class="dot">${r.n}</span>
              <span class="body"><span class="hyp">${esc(r.hypothesis)}</span>
              <span class="m">開發 <b class="${tone(r.dev_ret)}">${esc(r.dev_ret)}</b> · 執行 <b class="${tone(r.exec_ret)}">${esc(r.exec_ret)}</b>${r.overfit ? " " + FLAG : ""}${r.final ? ' <span class="badge done">定稿</span>' : ""}</span></span>
            </button></li>`).join("")}
          </ol>
        </section>`).join("")}
    </details>`).join("");
}

// ---------- study page ----------
function markdown(text) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const out = [];
  let list = null;
  for (const raw of String(text).split("\n")) {
    const line = raw.trim();
    const item = line.match(/^(?:\d+\.|[-*])\s+(.*)$/);
    if (item) {
      const tag = /^\d+\./.test(line) ? "ol" : "ul";
      if (list !== tag) { if (list) out.push(`</${list}>`); out.push(`<${tag}>`); list = tag; }
      out.push(`<li>${inline(item[1])}</li>`);
      continue;
    }
    if (list) { out.push(`</${list}>`); list = null; }
    if (!line) continue;
    const h = line.match(/^#{1,4}\s+(.*)$/);
    out.push(h ? `<h4>${inline(h[1])}</h4>` : `<p>${inline(line)}</p>`);
  }
  if (list) out.push(`</${list}>`);
  return out.join("");
}

function renderStudy() {
  const st = study;
  const rows = st.iterations.map((it) => `
    <tr data-run="${it.id}" aria-selected="${run && run.id === it.id}">
      <td class="n">${it.n}</td>
      <td class="wrap">${esc(it.hypothesis)}</td>
      <td class="chipcell"><span class="chip">${esc(it.diff)}</span></td>
      <td class="n ${tone(it.dev_ret)}">${esc(it.dev_ret)}</td>
      <td class="n ${tone(it.exec_ret)} strong">${esc(it.exec_ret)}</td>
      <td class="n">${esc(it.bh_exec_ret)}</td>
      <td class="n">${esc(it.exec_mdd)}</td>
      <td class="n">${esc(it.exec_sharpe)}</td>
      <td class="n">${esc(it.exec_trades)}</td>
      <td>${it.overfit ? FLAG : ""}${it.final ? '<span class="badge done">定稿</span>' : ""}</td>
    </tr>`).join("");
  $("d").innerHTML = `
    <div class="dh"><h2>${esc(st.label)}</h2><span class="sname">${esc(st.strategy)}</span>
      ${st.final_run_id ? '<span class="badge done">已定稿</span>' : '<span class="badge">研究中</span>'}</div>
    <div class="periods-row"><span class="pchip dev">策略開發期間　${esc(st.dev)}</span><span class="pchip exec">策略執行期間　${esc(st.exec)}</span></div>
    <p class="question">${esc(st.question)}</p>
    <section class="card conclusion">
      <h3>結論分析${st.finalized_at ? `<span class="muted">　定稿於 ${esc(st.finalized_at)}</span>` : ""}</h3>
      ${st.conclusion ? markdown(st.conclusion) : '<p class="muted">尚未定稿。Claude 定稿時會在此寫入結論分析，結合各項指標與盤勢分段說明策略表現。</p>'}
    </section>
    <section class="card">
      <h3>迭代比較<span class="muted">　調整只依策略開發期間；策略執行期間用於檢驗是否過度擬合</span></h3>
      <div class="scroll"><table class="iter"><thead><tr>
        <th class="n">#</th><th>假設</th><th>參數變化</th><th class="n">開發期間報酬率</th><th class="n">執行期間報酬率</th>
        <th class="n">執行期間買進並持有</th><th class="n">執行期間最大回撤</th><th class="n">執行期間 Sharpe</th><th class="n">執行期間交易次數</th><th></th>
      </tr></thead><tbody>${rows}</tbody></table></div>
    </section>
    <div id="run"></div>`;
}

// ---------- run section ----------
function table(head, body) {
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderRun() {
  const r = run;
  const metricRows = r.metrics.map((m) => `<tr><th>${esc(m.label)}</th>
    <td class="n ${tone(m.dev)}">${esc(m.dev)}</td><td class="n ${tone(m.exec)} strong">${esc(m.exec)}</td>
    <td class="n muted">${esc(m.bh_dev)}</td><td class="n muted">${esc(m.bh_exec)}</td></tr>`).join("");
  const tradeRows = r.trade_metrics.map((m) => `<tr><th>${esc(m.label)}</th>
    <td class="n ${tone(m.dev)}">${esc(m.dev)}</td><td class="n ${tone(m.exec)} strong">${esc(m.exec)}</td></tr>`).join("");
  const regimeRows = r.regimes.map((g) => `<tr><td><span class="rdot ${g.kind}"></span>${esc(g.label)}</td>
    <td>${esc(g.start)} 至 ${esc(g.end)}</td><td class="n">${esc(g.bars)}</td>
    <td class="n ${tone(g.price_change)}">${esc(g.price_change)}</td><td class="n ${tone(g.strategy)} strong">${esc(g.strategy)}</td>
    <td class="n">${esc(g.exposure)}</td></tr>`).join("");
  $("run").innerHTML = `
    <section class="card run">
      <h3>第 ${r.n} 次迭代<span class="muted">　#${r.id} · ${esc(r.created_at)}</span><span class="chip">${esc(r.diff)}</span></h3>
      <p class="hyp-lg">${esc(r.hypothesis)}</p>
      <p class="params">參數：${esc(r.params)}</p>
      ${r.overfit_note ? `<p class="note">${esc(r.overfit_note)}</p>` : ""}
      <div class="two">
        <div><h4>績效指標</h4>${table('<th></th><th class="n">策略開發期間</th><th class="n">策略執行期間</th><th class="n">買進並持有（開發）</th><th class="n">買進並持有（執行）</th>', metricRows)}</div>
        <div><h4>交易統計</h4>${table('<th></th><th class="n">策略開發期間</th><th class="n">策略執行期間</th>', tradeRows)}</div>
      </div>
      <h4>K 線與成交量</h4>
      <div class="legend"><span class="up">▲ 買進</span><span class="down">▼ 賣出</span>
        <span><i class="sw" style="background:${REGIME.up}"></i>上漲段</span><span><i class="sw" style="background:${REGIME.range}"></i>盤整段</span>
        <span><i class="sw" style="background:${REGIME.down}"></i>下跌段</span><span><i class="ln dash"></i>策略執行期間起點</span></div>
      <div class="chart tall" id="c-price" role="img" aria-label="K 線、成交量、買賣點與盤勢分段"></div>
      <h4>策略損益（新臺幣）</h4>
      <div class="legend"><span><i class="ln" style="background:#f0b429"></i>策略</span><span><i class="ln" style="background:#64748b"></i>買進並持有</span>
        <span class="muted">兩段期間各自以初始資金計算，策略執行期間由 0 開始</span></div>
      <div class="chart" id="c-pnl" role="img" aria-label="策略與買進並持有的累積損益"></div>
      <h4>回撤</h4>
      <div class="chart short" id="c-dd" role="img" aria-label="策略自高點回落的幅度"></div>
      <h4>盤勢分段</h4>
      <p class="muted small">${esc(r.regime_rules)}</p>
      ${table('<th>盤勢</th><th>期間</th><th class="n">交易日數</th><th class="n">股價漲跌幅</th><th class="n">策略報酬率</th><th class="n">策略持倉時間比例</th>', regimeRows)}
      <div class="tabs" role="tablist">
        ${[["fills", "成交明細"], ["trips", "已平倉交易"], ["dd", "最深回撤"], ["code", "策略原始碼"]].map(([k, l]) => `<button role="tab" data-tab="${k}" aria-selected="${tab === k}">${l}</button>`).join("")}
      </div>
      <div id="tabbody">${tabBody(r)}</div>
    </section>`;
  drawCharts(r);
}

function tabBody(r) {
  if (tab === "code") return `<pre>${esc(r.source)}</pre><p class="meta">策略原始碼 sha256：${esc(r.source_sha)}<br>資料指紋：${esc(r.data_sha)}</p>`;
  if (tab === "dd") {
    const rows = (list) => list.map((d) => `<tr><td>${esc(d.peak)}</td><td>${esc(d.trough)}</td><td class="n down">${esc(d.depth)}</td><td>${esc(d.recovery)}</td><td class="n">${esc(d.bars)}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">無回撤。</td></tr>';
    const head = '<th>高點日期</th><th>低點日期</th><th class="n">回撤幅度</th><th>回復日期</th><th class="n">持續交易日</th>';
    return `<h4>策略開發期間</h4>${table(head, rows(r.drawdowns.dev))}<h4>策略執行期間</h4>${table(head, rows(r.drawdowns.exec))}`;
  }
  if (tab === "trips") {
    if (!r.trips.length) return '<p class="empty">無已平倉交易。</p>';
    return table('<th>期間</th><th>進場</th><th>出場</th><th class="n">持有交易日</th><th class="n">已實現損益</th>',
      r.trips.map((t) => `<tr><td>${esc(t.period)}</td><td>${esc(t.entry)}</td><td>${esc(t.exit)}</td><td class="n">${esc(t.held)}</td><td class="n ${t.win ? "up" : "down"}">${esc(t.pnl)}</td></tr>`).join(""));
  }
  if (!r.fills.length) return '<p class="empty">無成交。</p>';
  return table('<th>期間</th><th>日期</th><th>方向</th><th class="n">價格</th><th class="n">股數</th><th class="n">成交金額</th><th class="n">手續費與稅</th>',
    r.fills.map((f) => `<tr><td>${esc(f.period)}</td><td>${esc(f.date)}</td><td class="${f.buy ? "up" : "down"}">${esc(f.side)}</td><td class="n">${esc(f.price)}</td><td class="n">${esc(f.shares)}</td><td class="n">${esc(f.gross)}</td><td class="n">${esc(f.fees)}</td></tr>`).join(""));
}

// ---------- charts ----------
class Bands {
  constructor(bands, line) { this.bands = bands; this.line = line; this.chart = null; }
  attached({ chart }) { this.chart = chart; }
  paneViews() {
    return [{
      zOrder: () => "bottom",
      renderer: () => ({
        draw: (target) => target.useBitmapCoordinateSpace((scope) => {
          if (!this.chart) return;
          const ts = this.chart.timeScale(), k = scope.horizontalPixelRatio, ctx = scope.context, h = scope.bitmapSize.height;
          for (const b of this.bands) {
            const x1 = ts.timeToCoordinate(b.start), x2 = ts.timeToCoordinate(b.end);
            if (x1 === null || x2 === null) continue;
            ctx.fillStyle = b.color;
            ctx.fillRect(Math.round(x1 * k), 0, Math.max(1, Math.round((x2 - x1) * k)), h);
          }
          if (this.line) {
            const x = ts.timeToCoordinate(this.line);
            if (x === null) return;
            ctx.strokeStyle = "rgba(240,180,41,0.8)"; ctx.setLineDash([6 * k, 4 * k]); ctx.lineWidth = k;
            ctx.beginPath(); ctx.moveTo(Math.round(x * k) + 0.5, 0); ctx.lineTo(Math.round(x * k) + 0.5, h); ctx.stroke(); ctx.setLineDash([]);
          }
        }),
      }),
    }];
  }
}

function makeChart(el) {
  return LC.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#161a20" }, textColor: "#8a93a0" },
    grid: { vertLines: { color: "#1d222a" }, horzLines: { color: "#1d222a" } },
    rightPriceScale: { borderColor: "#252b34", minimumWidth: 92 },
    timeScale: { borderColor: "#252b34" },
    localization: { locale: "zh-TW", dateFormat: "yyyy-MM-dd" },
    crosshair: { mode: 0 },
  });
}

const fmtPrice = { type: "custom", minMove: 0.01, formatter: (v) => groupDigits(v, 2) };
const fmtMoney = { type: "custom", minMove: 1, formatter: (v) => groupDigits(v, 0) };
const fmtPct = { type: "custom", minMove: 0.01, formatter: (v) => groupDigits(v, 2) + "%" };

function drawCharts(r) {
  charts.forEach((c) => c.remove());
  charts = [];
  if (!LC) { $("c-price").textContent = "圖表元件載入失敗。"; return; }
  const c = r.chart, execStart = c.exec_dates[0];
  const series = (dates, values) => dates.map((t, i) => ({ time: t, value: values[i] }));

  const price = makeChart($("c-price"));
  const candles = price.addSeries(LC.CandlestickSeries, { upColor: "#ef4444", downColor: "#22c55e", borderVisible: false, wickUpColor: "#ef4444", wickDownColor: "#22c55e", priceFormat: fmtPrice });
  candles.setData(c.dates.map((t, i) => ({ time: t, open: c.open[i], high: c.high[i], low: c.low[i], close: c.close[i] })));
  candles.attachPrimitive(new Bands(c.regimes.map((g) => ({ start: g.start, end: g.end, color: REGIME[g.kind] })), execStart));
  candles.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.26 } });
  LC.createSeriesMarkers(candles, c.markers.map((m) => m.side === "BUY"
    ? { time: m.date, position: "belowBar", color: "#ef4444", shape: "arrowUp" }
    : { time: m.date, position: "aboveBar", color: "#22c55e", shape: "arrowDown" }));
  const vol = price.addSeries(LC.HistogramSeries, { priceScaleId: "vol", priceFormat: fmtMoney, priceLineVisible: false, lastValueVisible: false });
  vol.setData(c.dates.map((t, i) => ({ time: t, value: c.volume[i], color: c.close[i] >= c.open[i] ? "rgba(239,68,68,0.45)" : "rgba(34,197,94,0.45)" })));
  price.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

  const pnl = makeChart($("c-pnl"));
  const band = [{ start: execStart, end: c.exec_dates[c.exec_dates.length - 1], color: "rgba(240,180,41,0.06)" }];
  const line = (opts) => pnl.addSeries(LC.LineSeries, { priceLineVisible: false, lastValueVisible: false, priceFormat: fmtMoney, ...opts });
  const s1 = line({ color: "#f0b429", lineWidth: 2 }); s1.setData(series(c.dev_dates, c.pnl_dev));
  line({ color: "#f0b429", lineWidth: 2 }).setData(series(c.exec_dates, c.pnl_exec));
  line({ color: "#64748b", lineWidth: 1, lineStyle: 2 }).setData(series(c.dev_dates, c.bh_pnl_dev));
  line({ color: "#64748b", lineWidth: 1, lineStyle: 2 }).setData(series(c.exec_dates, c.bh_pnl_exec));
  s1.attachPrimitive(new Bands(band, execStart));

  const dd = makeChart($("c-dd"));
  const area = (data) => { const a = dd.addSeries(LC.AreaSeries, { lineColor: "#22c55e", topColor: "rgba(34,197,94,0.05)", bottomColor: "rgba(34,197,94,0.35)", lineWidth: 1, priceLineVisible: false, lastValueVisible: false, priceFormat: fmtPct, invertFilledArea: true }); a.setData(data); return a; };
  area(series(c.dev_dates, c.dd_dev)).attachPrimitive(new Bands(band, execStart));
  area(series(c.exec_dates, c.dd_exec));

  charts = [price, pnl, dd];
  let syncing = false;
  for (const ch of charts) {
    ch.timeScale().subscribeVisibleTimeRangeChange((range) => {
      if (syncing || !range) return;
      syncing = true;
      for (const other of charts) if (other !== ch) other.timeScale().setVisibleRange(range);
      syncing = false;
    });
  }
  price.timeScale().fitContent();
}

// ---------- navigation ----------
async function getJSON(url) {
  const res = await fetch(url);
  return res.ok ? res.json() : null;
}

async function openStudy(key, runId, push = true) {
  const st = await getJSON(`/api/studies/${encodeURIComponent(key)}`);
  if (!st) return renderEmpty();
  study = st;
  const id = runId ?? st.final_run_id ?? st.iterations[st.iterations.length - 1].id;
  run = await getJSON(`/api/runs/${id}`);
  if (push) history.pushState(null, "", runId ? `/runs/${id}` : `/studies/${key}`);
  renderTree();
  renderStudy();
  if (run) renderRun();
}

async function openRun(id, push = true) {
  const r = await getJSON(`/api/runs/${id}`);
  if (!r) return renderEmpty();
  if (!study || study.key !== r.study_key) return openStudy(r.study_key, id, push);
  run = r;
  if (push) history.pushState(null, "", `/runs/${id}`);
  renderTree();
  renderStudy();
  renderRun();
}

function renderEmpty() {
  $("d").innerHTML = `<div class="empty"><p>尚無回測紀錄。</p><p>請在 Claude Code 中討論策略並執行回測；新的回測完成後，此頁面會自動顯示。</p></div>`;
}

function sig(t) {
  return JSON.stringify(t.map((s) => s.studies.map((st) => [st.key, st.final_run_id, st.runs.map((r) => r.id)])));
}

async function poll() {
  const t = await getJSON("/api/tree").catch(() => null);
  if (!t || sig(t) === signature) return;
  const before = newestRun();
  const following = !run || (before && run.id === before.id);
  tree = t; signature = sig(t);
  t.forEach((s) => openStocks && openStocks.add(s.symbol));
  const latest = newestRun();
  if (following && latest && (!before || latest.id !== before.id)) {
    await openRun(latest.id, false);
    history.replaceState(null, "", `/runs/${latest.id}`);
    return;
  }
  if (study) {
    const fresh = await getJSON(`/api/studies/${encodeURIComponent(study.key)}`);
    if (fresh) { study = fresh; renderStudy(); if (run) renderRun(); }
  }
  renderTree();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-run],[data-study],[data-tab]");
  if (!t) return;
  if (t.dataset.tab) { tab = t.dataset.tab; $("tabbody").innerHTML = tabBody(run); document.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab)); return; }
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
