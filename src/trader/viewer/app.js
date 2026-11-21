// Layout only: every displayed number arrives pre-formatted from trader.fmt via the API.
const LC = window.LightweightCharts;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const tone = (s) => (s.startsWith("+") ? "up" : s.startsWith("-") ? "down" : "");
const flag = (r) => (r.s.overfit === "yes" ? ' <span class="flag" title="樣本內年化報酬率較樣本外高出逾 15 個百分點">⚑</span>' : "");

let runs = [], current = null, mode = "tl", sortKey = "out_of_sample", tab = "fills", chart = null;

const pctValue = (s) => (s === "—" ? -Infinity : parseFloat(s.replace(/[+%,]/g, "")));

function renderList() {
  document.querySelectorAll("[data-mode]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === mode));
  const lst = $("lst");
  if (!runs.length) {
    lst.innerHTML = '<p class="empty">尚無回測紀錄。</p>';
    return;
  }
  if (mode === "tl") {
    const groups = new Map();
    runs.forEach((r) => {
      const k = `${r.strategy} · ${r.symbol}`;
      groups.set(k, [...(groups.get(k) || []), r]);
    });
    lst.innerHTML = [...groups].map(([k, rs]) => `<div class="group"><h3>${esc(k)}<span>${rs.length} 次回測</span></h3><ol class="steps">${rs
      .map((r, i) => `<li><button data-r="${r.id}" aria-current="${current && r.id === current.id}">
        <span class="dot">${i + 1}</span><span><div class="hyp">${esc(r.hypothesis)}</div>
        <div class="m"><span>#${r.id}</span><span>樣本內 <b class="${tone(r.s.in_sample)}">${r.s.in_sample}</b></span>
        <span>樣本外 <b class="${tone(r.s.out_of_sample)}">${r.s.out_of_sample}</b>${flag(r)}</span><span>${esc(r.created_at)}</span></div></span></button></li>`)
      .join("")}</ol></div>`).join("");
  } else {
    const rs = [...runs].sort((a, b) => pctValue(b.s[sortKey]) - pctValue(a.s[sortKey]));
    const th = (k, label) => `<th class="n" data-k="${k}">${label}${sortKey === k ? " ▾" : ""}</th>`;
    lst.innerHTML = `<table class="rank"><thead><tr><th>#</th><th>策略</th>${th("in_sample", "樣本內")}${th("out_of_sample", "樣本外")}<th class="n">買進並持有</th><th class="n">最大回撤</th><th class="n">交易</th></tr></thead><tbody>${rs
      .map((r) => `<tr data-r="${r.id}" aria-selected="${current && r.id === current.id}"><td>${r.id}</td><td>${esc(r.strategy)}</td>
        <td class="n ${tone(r.s.in_sample)}">${r.s.in_sample}</td><td class="n ${tone(r.s.out_of_sample)}">${r.s.out_of_sample}${flag(r)}</td>
        <td class="n">${r.s.bh_out_of_sample}</td><td class="n">${r.s.mdd}</td><td class="n">${r.s.trades}</td></tr>`)
      .join("")}</tbody></table>`;
  }
}

function renderEmpty() {
  $("d").innerHTML = `<div class="empty"><p>尚無回測紀錄。</p><p>請在 Claude Code 中討論策略，並以 <code>run_backtest</code> 執行回測；新的回測完成後，此頁面會自動顯示。</p></div>`;
}

function renderDetail() {
  const r = current, s = r.s;
  const cell = (label, v, sub) => `<div><small>${label}</small><div class="v ${tone(v)}">${v}</div><div class="s">${sub}</div></div>`;
  $("d").innerHTML = `<div class="dh"><h2>${esc(r.strategy)}</h2><span>#${r.id} · ${esc(r.symbol)} · ${esc(r.created_at)}</span><span class="chip">${esc(r.diff)}</span></div>
    <p class="dhyp">${esc(r.hypothesis)}</p>
    <p class="params">參數：${esc(r.params)}</p>
    <div class="grid4">
      ${cell("樣本內報酬率", s.in_sample, `年化 ${s.in_sample_annualized}`)}
      ${cell("樣本外報酬率", s.out_of_sample, `年化 ${s.out_of_sample_annualized}`)}
      ${cell("買進並持有（樣本外）", s.bh_out_of_sample, `總報酬率 ${s.bh_total}`)}
      ${cell("交易次數 · 勝率", `${s.trades} · ${s.win_rate}`, `最大回撤 ${s.mdd}`)}
    </div>
    ${r.overfit_note ? `<p class="note">${esc(r.overfit_note)}</p>` : ""}
    <p class="sub">${esc(r.title)} · 總報酬率 ${s.total} · 期末權益 ${s.final_equity} · 樣本外區間起點 ${s.oos_start}</p>
    <div class="chart" id="chart" role="img" aria-label="K 線、買賣點與權益曲線"></div>
    <div class="legend"><span><i style="background:#f0b429"></i>策略權益</span><span><i style="background:#64748b"></i>買進並持有</span><span><i style="background:rgba(240,180,41,.35);height:8px"></i>樣本外區間</span><span class="up">▲ 買進</span><span class="down">▼ 賣出</span></div>
    <div class="tabs" role="tablist">
      <button role="tab" data-t="fills" aria-selected="${tab === "fills"}">成交明細</button>
      <button role="tab" data-t="trips" aria-selected="${tab === "trips"}">已平倉交易</button>
      <button role="tab" data-t="code" aria-selected="${tab === "code"}">策略原始碼</button>
    </div>
    ${tabBody(r)}`;
  drawChart(r);
}

function tabBody(r) {
  if (tab === "code") {
    return `<pre>${esc(r.source)}</pre><p class="meta">策略原始碼 sha256：${r.source_sha}<br>資料指紋：${r.data_sha}</p>`;
  }
  if (tab === "trips") {
    if (!r.trips.length) return '<p class="empty">無已平倉交易。</p>';
    return `<table><thead><tr><th>進場</th><th>出場</th><th class="n">持有交易日</th><th class="n">已實現損益</th></tr></thead><tbody>${r.trips
      .map((t) => `<tr><td>${t.entry}</td><td>${t.exit}</td><td class="n">${t.held}</td><td class="n ${t.win ? "up" : "down"}">${t.pnl}</td></tr>`)
      .join("")}</tbody></table>`;
  }
  if (!r.fills.length) return '<p class="empty">無成交。</p>';
  return `<table><thead><tr><th>日期</th><th>方向</th><th class="n">價格</th><th class="n">股數</th><th class="n">成交金額</th><th class="n">手續費與稅</th></tr></thead><tbody>${r.fills
    .map((f) => `<tr class="${f.oos ? "oos" : ""}"><td>${f.date}</td><td class="${f.buy ? "up" : "down"}">${f.side}</td><td class="n">${f.price}</td><td class="n">${f.shares}</td><td class="n">${f.gross}</td><td class="n">${f.fees}</td></tr>`)
    .join("")}</tbody></table>`;
}

class OutOfSampleBand {
  constructor(from) { this.from = from; this.chart = null; }
  attached({ chart }) { this.chart = chart; }
  paneViews() {
    return [{
      zOrder: () => "bottom",
      renderer: () => ({
        draw: (target) => target.useBitmapCoordinateSpace((scope) => {
          const x = this.chart && this.chart.timeScale().timeToCoordinate(this.from);
          if (x === null || x === undefined) return;
          const px = Math.max(0, Math.round(x * scope.horizontalPixelRatio));
          scope.context.fillStyle = "rgba(240,180,41,0.07)";
          scope.context.fillRect(px, 0, scope.bitmapSize.width - px, scope.bitmapSize.height);
        }),
      }),
    }];
  }
}

function drawChart(r) {
  if (chart) { chart.remove(); chart = null; }
  const el = $("chart");
  if (!LC) { el.textContent = "圖表元件載入失敗。"; return; }
  const money = { type: "price", precision: 0, minMove: 1 };
  chart = LC.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "#161a20" }, textColor: "#8a93a0", panes: { separatorColor: "#252b34" } },
    grid: { vertLines: { color: "#1d222a" }, horzLines: { color: "#1d222a" } },
    rightPriceScale: { borderColor: "#252b34" },
    timeScale: { borderColor: "#252b34" },
    localization: { locale: "zh-TW", dateFormat: "yyyy-MM-dd" },
    crosshair: { mode: 0 },
  });
  const b = r.bars, from = b.date[r.split - 1];
  const candles = chart.addSeries(LC.CandlestickSeries, { upColor: "#ef4444", downColor: "#22c55e", borderVisible: false, wickUpColor: "#ef4444", wickDownColor: "#22c55e" });
  candles.setData(b.date.map((t, i) => ({ time: t, open: b.open[i], high: b.high[i], low: b.low[i], close: b.close[i] })));
  candles.attachPrimitive(new OutOfSampleBand(from));
  LC.createSeriesMarkers(candles, r.markers.map((m) => m.side === "BUY"
    ? { time: m.date, position: "belowBar", color: "#ef4444", shape: "arrowUp" }
    : { time: m.date, position: "aboveBar", color: "#22c55e", shape: "arrowDown" }));
  const eq = chart.addSeries(LC.LineSeries, { color: "#f0b429", lineWidth: 2, priceLineVisible: false, priceFormat: money }, 1);
  eq.setData(r.equity.map((v, i) => ({ time: b.date[i], value: v })));
  eq.attachPrimitive(new OutOfSampleBand(from));
  const bh = chart.addSeries(LC.LineSeries, { color: "#64748b", lineWidth: 1, lineStyle: 2, priceLineVisible: false, priceFormat: money }, 1);
  bh.setData(r.bh_equity.map((v, i) => ({ time: b.date[i], value: v })));
  chart.panes()[1].setHeight(150);
  chart.timeScale().fitContent();
}

async function select(id, push = true) {
  const res = await fetch(`/api/runs/${id}`);
  if (!res.ok) { renderEmpty(); return; }
  current = await res.json();
  if (push) history.pushState(null, "", `/runs/${id}`);
  renderList();
  renderDetail();
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-r],[data-t],[data-k],[data-mode]");
  if (!t) return;
  if (t.dataset.mode) { mode = t.dataset.mode; return renderList(); }
  if (t.dataset.k) { sortKey = t.dataset.k; return renderList(); }
  if (t.dataset.t) { tab = t.dataset.t; return renderDetail(); }
  select(Number(t.dataset.r));
});

window.addEventListener("popstate", () => {
  const m = location.pathname.match(/^\/runs\/(\d+)$/);
  if (m) select(Number(m[1]), false);
});

// New runs appear without a reload. The view follows the newest run unless the user picked an older one.
async function poll() {
  const res = await fetch("/api/runs").catch(() => null);
  if (!res || !res.ok) return;
  const list = await res.json();
  if (list.length === runs.length) return;
  const following = !current || current.id === runs[runs.length - 1]?.id;
  runs = list;
  if (!following) return renderList();
  const id = runs[runs.length - 1].id;
  await select(id, false);
  history.replaceState(null, "", `/runs/${id}`);
}

setInterval(poll, 2000);

(async () => {
  const [info, list] = await Promise.all([fetch("/api/info").then((r) => r.json()), fetch("/api/runs").then((r) => r.json())]);
  $("ws").textContent = info.workspace;
  runs = list;
  const m = location.pathname.match(/^\/runs\/(\d+)$/);
  if (m) return select(Number(m[1]), false);
  if (runs.length) return select(runs[runs.length - 1].id, false);
  renderList();
  renderEmpty();
})();
