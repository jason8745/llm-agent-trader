// ponytail: fake data for UI mockups only. Real viewer reads runs.db via FastAPI.
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}

const bars=(()=>{const r=mulberry32(5);let p=580,d=new Date('2025-01-02T00:00:00Z');const out=[];
  while(out.length<300){const wd=d.getUTCDay();if(wd%6){const o=p*(1+(r()-.5)*.012),c=o*(1+(r()-.47)*.03);
    out.push({t:d.toISOString().slice(0,10),o,h:Math.max(o,c)*(1+r()*.01),l:Math.min(o,c)*(1-r()*.01),c});p=c}
    d.setUTCDate(d.getUTCDate()+1)}return out})();
const SPLIT=Math.floor(bars.length*.7);
const bh=bars.map(b=>1e6*b.c/bars[0].c);

function sma(i,n){if(i<n-1)return null;let s=0;for(let k=i-n+1;k<=i;k++)s+=bars[k].c;return s/n}
// signal on close i, fill at open i+1; TW fee 0.1425% each side + 0.3% sell tax
function backtest(fast,slow){let cash=1e6,sh=0,want=0;const trades=[],eq=[];
  for(let i=0;i<bars.length;i++){const b=bars[i];
    if(want&&!sh){sh=Math.floor(cash/(b.o*1.001425));cash-=sh*b.o*1.001425;trades.push({side:'BUY',t:b.t,px:b.o,sh,i})}
    else if(!want&&sh){const v=sh*b.o*(1-.001425-.003),buy=trades[trades.length-1];cash+=v;
      trades.push({side:'SELL',t:b.t,px:b.o,sh,i,pnl:v-buy.sh*buy.px*1.001425,days:i-buy.i});sh=0}
    eq.push(cash+sh*b.c);
    const f=sma(i,fast),s=sma(i,slow);want=f!=null&&s!=null&&f>s?1:0}
  return{trades,eq}}
function seg(eq,a,b){let peak=-Infinity,mdd=0;for(let i=a;i<=b;i++){peak=Math.max(peak,eq[i]);mdd=Math.min(mdd,eq[i]/peak-1)}return{ret:eq[b]/eq[a]-1,mdd}}

const RUNS=[
  {id:'r01',strategy:'ma_cross',p:{fast:10,slow:20},at:'11-20 10:12',hyp:'Baseline：10/20 SMA 黃金交叉，只做多。'},
  {id:'r02',strategy:'ma_cross',p:{fast:5,slow:20},at:'11-20 10:31',hyp:'快線改 5 日，預期更早抓到趨勢起點，交易次數變多。'},
  {id:'r03',strategy:'ma_cross',p:{fast:10,slow:50},at:'11-20 10:48',hyp:'慢線拉到 50 日，過濾盤整期的來回洗。'},
  {id:'r04',strategy:'ma_cross',p:{fast:20,slow:60},at:'11-20 11:05',hyp:'再拉長：更少、更長的持有。看 IS 的提升在 OOS 撐不撐得住。'},
  {id:'r05',strategy:'trend_pullback',p:{fast:8,slow:30},at:'11-21 09:40',hyp:'在 30 日上升趨勢內，回檔到 8 日線附近買進。'},
  {id:'r06',strategy:'trend_pullback',p:{fast:12,slow:40},at:'11-21 10:02',hyp:'放寬區間；報告前最後一次看 OOS。'},
].map(r=>{const{trades,eq}=backtest(r.p.fast,r.p.slow),n=bars.length-1;
  return{...r,symbol:'2330.TW',name:'台積電',trades,eq,is:seg(eq,0,SPLIT),oos:seg(eq,SPLIT,n),bhIs:seg(bh,0,SPLIT),bhOos:seg(bh,SPLIT,n),
    nTrades:trades.filter(t=>t.side==='SELL').length,
    win:(()=>{const s=trades.filter(t=>t.side==='SELL');return s.length?s.filter(t=>t.pnl>0).length/s.length:0})()}});

const pct=v=>(v>=0?'+':'')+(v*100).toFixed(1)+'%';
const money=v=>Math.round(v).toLocaleString('en-US');
// Taiwan convention: red = up, green = down
const tone=v=>v>=0?'up':'down';
const overfit=r=>r.is.ret-r.oos.ret>0.15;

function source(r){return `"""${r.strategy} — ${r.hyp}"""
from trader import ta

PARAMS = {"fast": ${r.p.fast}, "slow": ${r.p.slow}}

def on_bar(hist, pos, p):
    fast = ta.sma(hist.close, p["fast"]).iloc[-1]
    slow = ta.sma(hist.close, p["slow"]).iloc[-1]
    return 1.0 if fast > slow else 0.0
`}

// th: {up, dn, eq, bh, grid, text, oos, font}
function chartSVG(run,th,{W=960,H=440}={}){
  const ph=Math.round(H*.6),eTop=ph+28,eh=H-eTop-8,n=bars.length,x=i=>8+i*(W-16)/n,bw=Math.max(1,(W-16)/n*.6);
  const lo=Math.min(...bars.map(b=>b.l)),hi=Math.max(...bars.map(b=>b.h)),y=v=>20+(hi-v)/(hi-lo)*(ph-28);
  const ev=[...run.eq,...bh],emin=Math.min(...ev),emax=Math.max(...ev),ye=v=>eTop+(emax-v)/(emax-emin)*eh;
  const f=`font-family="${th.font}" font-size="11" fill="${th.text}"`;
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${run.symbol} price with trades, equity vs buy and hold">`;
  s+=`<rect x="${x(SPLIT)}" y="0" width="${W-8-x(SPLIT)}" height="${H}" fill="${th.oos}"/>`;
  s+=`<line x1="${x(SPLIT)}" x2="${x(SPLIT)}" y1="0" y2="${H}" stroke="${th.text}" stroke-dasharray="3,3" opacity=".6"/>`;
  s+=`<text x="${x(SPLIT)-6}" y="12" text-anchor="end" ${f}>IN-SAMPLE</text><text x="${x(SPLIT)+6}" y="12" ${f}>OUT-OF-SAMPLE</text>`;
  s+=`<line x1="8" x2="${W-8}" y1="${ph+12}" y2="${ph+12}" stroke="${th.grid}"/>`;
  bars.forEach((b,i)=>{const c=b.c>=b.o?th.up:th.dn;
    s+=`<line x1="${x(i)}" x2="${x(i)}" y1="${y(b.h)}" y2="${y(b.l)}" stroke="${c}"/><rect x="${x(i)-bw/2}" y="${y(Math.max(b.o,b.c))}" width="${bw}" height="${Math.max(1,Math.abs(y(b.o)-y(b.c)))}" fill="${c}"/>`});
  run.trades.forEach(t=>{const b=bars[t.i],X=x(t.i);
    s+=t.side==='BUY'?`<path d="M${X},${y(b.l)+4} l-5,9 h10z" fill="${th.buy||th.up}" stroke="${th.bg||'#fff'}" stroke-width=".8"/>`
                     :`<path d="M${X},${y(b.h)-4} l-5,-9 h10z" fill="${th.sell||th.dn}" stroke="${th.bg||'#fff'}" stroke-width=".8"/>`});
  const line=(arr,c,d)=>`<polyline fill="none" stroke="${c}" stroke-width="1.6" ${d?'stroke-dasharray="4,3"':''} points="${arr.map((v,i)=>`${x(i).toFixed(1)},${ye(v).toFixed(1)}`).join(' ')}"/>`;
  s+=line(bh,th.bh,true)+line(run.eq,th.eq,false);
  s+=`<text x="12" y="${eTop+4}" ${f}><tspan fill="${th.eq}">━ strategy</tspan>  <tspan fill="${th.bh}">┅ buy &amp; hold</tspan></text>`;
  return s+'</svg>'}

function sparkSVG(run,th,W=240,H=56){const all=[...run.eq,...bh],mn=Math.min(...all),mx=Math.max(...all),n=bars.length;
  const p=a=>a.map((v,i)=>`${(i*W/(n-1)).toFixed(1)},${(4+(mx-v)/(mx-mn)*(H-8)).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" preserveAspectRatio="none" aria-hidden="true">
  <rect x="${SPLIT*W/(n-1)}" width="${W}" height="${H}" fill="${th.oos}"/>
  <polyline points="${p(bh)}" fill="none" stroke="${th.bh}" stroke-width="1.2" stroke-dasharray="3,2" vector-effect="non-scaling-stroke"/>
  <polyline points="${p(run.eq)}" fill="none" stroke="${th.eq}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`}

function tradesTable(run){return `<table class="trades"><thead><tr><th>日期</th><th>方向</th><th class="n">價格</th><th class="n">股數</th><th class="n">損益</th><th class="n">持有</th></tr></thead><tbody>${
  run.trades.map(t=>`<tr class="${t.i>=SPLIT?'oos':''}"><td>${t.t}</td><td class="${t.side==='BUY'?'up':'down'}">${t.side}</td><td class="n">${t.px.toFixed(1)}</td><td class="n">${money(t.sh)}</td><td class="n ${t.pnl!=null?tone(t.pnl):''}">${t.pnl!=null?money(t.pnl):''}</td><td class="n">${t.days!=null?t.days+'d':''}</td></tr>`).join('')}</tbody></table>`}

const esc=s=>s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
