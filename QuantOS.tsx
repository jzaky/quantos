"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  AlarmClock,
  BarChart3,
  Bell,
  Bot,
  BrainCircuit,
  CandlestickChart,
  ChevronDown,
  CircleGauge,
  Command,
  Crosshair,
  Database,
  FlaskConical,
  Gauge,
  Grid2X2,
  Hexagon,
  Layers3,
  LockKeyhole,
  Network,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Search,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  WalletCards,
  Waves,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

type Section =
  | "command"
  | "strategies"
  | "agents"
  | "execution"
  | "risk"
  | "research"
  | "shadow"
  | "brokers"
  | "daytrade"
  | "tracking";

type Strategy = {
  id?: string;
  name: string;
  family: string;
  pnl: number;
  sharpe: number;
  health: number;
  allocation: number;
  regime: string;
  active: boolean;
  healthState?: string;
  netEdgeBps?: number;
  regimeFit?: number;
  volSize?: number;
  correlationPenalty?: number;
};

type Snapshot = {
  equity: number;
  dayPnl: number;
  drawdown: number;
  grossExposure: number;
  regime: string;
  latencyMs: number;
  activeStrategies: number;
  riskState: string;
  engineRunning?: boolean;
  mode?: string;
  positionCount?: number;
};

const nav: { id: Section; label: string; icon: typeof Grid2X2 }[] = [
  { id: "command", label: "Command", icon: Grid2X2 },
  { id: "daytrade", label: "Day Trader", icon: CandlestickChart },
  { id: "tracking", label: "Forward Test", icon: Database },
  { id: "strategies", label: "Strategy Lab", icon: BrainCircuit },
  { id: "agents", label: "Agent Mesh", icon: Bot },
  { id: "execution", label: "Execution", icon: Crosshair },
  { id: "brokers", label: "Broker Cloud", icon: Network },
  { id: "risk", label: "Risk Command", icon: ShieldCheck },
  { id: "research", label: "Research Lab", icon: FlaskConical },
  { id: "shadow", label: "Shadow Replay", icon: Layers3 },
];

const initialStrategies: Strategy[] = [
  { id: "vector-momentum", name: "Vector Momentum", family: "Momentum", pnl: 8421, sharpe: 2.18, health: 94, allocation: 18, regime: "TREND", active: true },
  { id: "mercury-pairs", name: "Mercury Pairs", family: "Stat Arb", pnl: 6118, sharpe: 1.91, health: 89, allocation: 14, regime: "RANGE", active: true },
  { id: "london-vector", name: "London Vector", family: "Breakout", pnl: 3954, sharpe: 1.63, health: 82, allocation: 11, regime: "TREND", active: true },
  { id: "helix-reversion", name: "Helix Reversion", family: "Mean Rev", pnl: 5226, sharpe: 1.76, health: 87, allocation: 16, regime: "RANGE", active: true },
  { id: "vol-surface", name: "Vol Surface", family: "Volatility", pnl: 4677, sharpe: 1.51, health: 78, allocation: 12, regime: "VOL", active: true },
  { id: "atlas-macro", name: "Atlas Macro", family: "Macro", pnl: 2610, sharpe: 1.22, health: 71, allocation: 8, regime: "MACRO", active: true },
  { id: "neural-footprint", name: "Neural Footprint", family: "ML Flow", pnl: -386, sharpe: 0.44, health: 43, allocation: 4, regime: "WATCH", active: false },
  { id: "cash-reserve", name: "Cash Reserve", family: "Defense", pnl: 0, sharpe: 0, health: 100, allocation: 17, regime: "ANY", active: true },
];

const agents = [
  { name: "REGIME-01", role: "Regime classifier", confidence: 96, verdict: "TREND / LOW VOL", status: "streaming" },
  { name: "FLOW-07", role: "Order-flow analyst", confidence: 82, verdict: "BUY IMBALANCE", status: "streaming" },
  { name: "MACRO-03", role: "Macro context", confidence: 71, verdict: "NEUTRAL +", status: "streaming" },
  { name: "VOL-09", role: "Volatility surface", confidence: 88, verdict: "EXPANSION", status: "streaming" },
  { name: "RISK-00", role: "Independent governor", confidence: 99, verdict: "WITHIN LIMITS", status: "locked" },
];

const positions = [
  { symbol: "ES", side: "LONG", qty: "3", avg: "6,842.25", mark: "6,851.75", pnl: "+$1,425", strategy: "Vector Momentum" },
  { symbol: "NVDA", side: "LONG", qty: "180", avg: "$196.22", mark: "$197.14", pnl: "+$166", strategy: "London Vector" },
  { symbol: "BTC", side: "LONG", qty: "0.42", avg: "$114,380", mark: "$114,922", pnl: "+$228", strategy: "Vol Surface" },
  { symbol: "CL", side: "SHORT", qty: "2", avg: "$66.08", mark: "$65.94", pnl: "+$280", strategy: "Atlas Macro" },
  { symbol: "MSFT/AAPL", side: "PAIR", qty: "1.2x", avg: "z 2.31", mark: "z 1.86", pnl: "+$412", strategy: "Mercury Pairs" },
];

const executions = [
  { time: "11:57:44.208", symbol: "ES", side: "BUY", size: "1", price: "6850.25", slip: "+0.25", state: "FILLED" },
  { time: "11:57:32.992", symbol: "NVDA", side: "BUY", size: "60", price: "197.02", slip: "+0.01", state: "FILLED" },
  { time: "11:56:58.461", symbol: "BTC", side: "BUY", size: "0.12", price: "114,886", slip: "+$7", state: "FILLED" },
  { time: "11:56:31.128", symbol: "CL", side: "SELL", size: "1", price: "65.99", slip: "0.00", state: "FILLED" },
  { time: "11:55:46.772", symbol: "AMD", side: "BUY", size: "90", price: "—", slip: "—", state: "BLOCKED" },
];

const baseEquity = [
  100, 103, 102, 106, 107, 112, 110, 115, 119, 117, 121, 120, 126, 128, 125, 130, 133, 132, 138, 136, 141, 145, 143, 149, 152, 151, 157, 160, 159, 166, 169, 168, 173, 178, 176, 181, 184, 189, 187, 193, 198, 196, 202, 208, 205, 214, 218, 221,
];

const fmtMoney = (value: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);

function MiniLine({ values, className = "" }: { values: number[]; className?: string }) {
  const width = 500;
  const height = 160;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - ((v - min) / Math.max(1, max - min)) * (height - 18) - 9;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg className={`spark-svg ${className}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id="areaGlow" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity=".28" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
        <filter id="glowLine">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <polygon points={`0,${height} ${points} ${width},${height}`} fill="url(#areaGlow)" />
      <motion.polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.25"
        vectorEffect="non-scaling-stroke"
        filter="url(#glowLine)"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 1.2, ease: "easeOut" }}
      />
    </svg>
  );
}

function HealthRing({ value }: { value: number }) {
  const circumference = 2 * Math.PI * 18;
  const dash = circumference * (value / 100);
  return (
    <div className="health-ring" title={`Health ${value}%`}>
      <svg viewBox="0 0 44 44">
        <circle cx="22" cy="22" r="18" className="ring-track" />
        <motion.circle
          cx="22"
          cy="22"
          r="18"
          className="ring-value"
          strokeDasharray={`${dash} ${circumference - dash}`}
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.8 }}
        />
      </svg>
      <span>{value}</span>
    </div>
  );
}

function Metric({ label, value, delta, icon: Icon }: { label: string; value: string; delta?: string; icon: typeof Activity }) {
  return (
    <motion.div className="metric-card glass" whileHover={{ y: -3, scale: 1.008 }} transition={{ type: "spring", stiffness: 380, damping: 28 }}>
      <div className="metric-head"><span>{label}</span><Icon size={15} /></div>
      <div className="metric-value">{value}</div>
      {delta && <div className={`metric-delta ${delta.startsWith("-") ? "neg" : "pos"}`}>{delta}</div>}
      <div className="metric-scan" />
    </motion.div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return <span className="kbd">{children}</span>;
}

function Overview({ snapshot, strategies }: { snapshot: Snapshot; strategies: Strategy[] }) {
  const active = strategies.filter((s) => s.active);
  return (
    <motion.div className="view-grid" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
      <section className="hero-panel glass span-8">
        <div className="panel-title-row">
          <div>
            <div className="eyebrow">PORTFOLIO EQUITY · LIVE</div>
            <div className="hero-equity">{fmtMoney(snapshot.equity)}</div>
            <div className="hero-sub"><span className="positive">+{fmtMoney(snapshot.dayPnl)}</span><span>today</span><span className="dot-sep" /> <span>+18.42% YTD</span></div>
          </div>
          <div className="hero-actions">
            <button className="seg active">1D</button><button className="seg">1W</button><button className="seg">1M</button><button className="seg">YTD</button>
          </div>
        </div>
        <div className="equity-chart-wrap">
          <div className="chart-grid" />
          <MiniLine values={baseEquity} className="equity-line" />
          <div className="chart-cursor"><span>11:57</span></div>
          <div className="chart-event event-a"><Zap size={11} /><span>BUY ES</span></div>
          <div className="chart-event event-b"><ShieldCheck size={11} /><span>RISK PASS</span></div>
        </div>
        <div className="chart-footer">
          <span>09:30</span><span>10:00</span><span>10:30</span><span>11:00</span><span>11:30</span><span>NOW</span>
        </div>
      </section>

      <section className="glass span-4 regime-panel">
        <div className="panel-title-row compact"><div><div className="eyebrow">MARKET REGIME</div><h3>Adaptive State</h3></div><Radio size={17} className="live-icon" /></div>
        <div className="regime-orbit">
          <div className="orbit orbit-1" /><div className="orbit orbit-2" />
          <motion.div className="regime-core" animate={{ boxShadow: ["0 0 18px rgba(65,231,255,.15)", "0 0 45px rgba(65,231,255,.35)", "0 0 18px rgba(65,231,255,.15)"] }} transition={{ repeat: Infinity, duration: 3.2 }}>
            <span>{snapshot.regime}</span><strong>96%</strong><small>confidence</small>
          </motion.div>
          <span className="orbit-label l1">VOL 22%</span><span className="orbit-label l2">MOM +0.71</span><span className="orbit-label l3">LIQ HIGH</span>
        </div>
        <div className="regime-stats"><div><span>Vol state</span><b>Compressed</b></div><div><span>Trend</span><b className="positive">Persistent</b></div><div><span>Correlation</span><b>0.34</b></div></div>
      </section>

      <section className="glass span-7">
        <div className="panel-title-row compact"><div><div className="eyebrow">STRATEGY MATRIX</div><h3>Capital intelligence</h3></div><button className="ghost-btn">Open lab <ChevronDown size={14} /></button></div>
        <div className="strategy-strip">
          {active.slice(0, 6).map((s, i) => (
            <motion.div className="strategy-mini" key={s.name} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .05 }}>
              <HealthRing value={s.health} />
              <div className="strategy-mini-main"><b>{s.name}</b><span>{s.family} · {s.regime}</span></div>
              <div className="strategy-mini-tail"><strong>{s.allocation}%</strong><span className={s.pnl >= 0 ? "positive" : "negative"}>{s.pnl >= 0 ? "+" : ""}{fmtMoney(s.pnl)}</span></div>
            </motion.div>
          ))}
        </div>
      </section>

      <section className="glass span-5 agent-consensus">
        <div className="panel-title-row compact"><div><div className="eyebrow">AGENT CONSENSUS</div><h3>Decision mesh</h3></div><Network size={17} /></div>
        <div className="consensus-wrap">
          <div className="consensus-score"><span>LONG</span><strong>78</strong><small>/100 consensus</small></div>
          <div className="consensus-bars">
            {[88, 72, 64, 91, 97].map((n, i) => <div key={i} className="consensus-row"><span>{agents[i].name}</span><div><motion.i initial={{ width: 0 }} animate={{ width: `${n}%` }} transition={{ duration: .7, delay: i * .08 }} /></div><b>{n}</b></div>)}
          </div>
        </div>
      </section>

      <section className="glass span-8">
        <div className="panel-title-row compact"><div><div className="eyebrow">LIVE POSITIONS</div><h3>Portfolio book</h3></div><div className="status-pill"><span className="pulse-dot" /> {positions.length} OPEN</div></div>
        <div className="data-table positions-table">
          <div className="table-row table-head"><span>Instrument</span><span>Side</span><span>Size</span><span>Avg</span><span>Mark</span><span>P&L</span><span>Strategy</span></div>
          {positions.map((p) => <motion.div className="table-row" key={p.symbol} whileHover={{ x: 3 }}><b>{p.symbol}</b><span className={`side ${p.side === "SHORT" ? "short" : "long"}`}>{p.side}</span><span>{p.qty}</span><span>{p.avg}</span><span>{p.mark}</span><strong className="positive">{p.pnl}</strong><span className="muted">{p.strategy}</span></motion.div>)}
        </div>
      </section>

      <section className="glass span-4 risk-summary">
        <div className="panel-title-row compact"><div><div className="eyebrow">RISK GOVERNOR</div><h3>Independent guard</h3></div><ShieldCheck size={18} className="safe-icon" /></div>
        <div className="risk-hero"><div className="risk-shield"><ShieldCheck size={34} /><span>SAFE</span></div><div><strong>All controls nominal</strong><span>12 / 12 policies passing</span></div></div>
        <div className="risk-bars"><div><span>Daily loss</span><b>18%</b><i><em style={{ width: "18%" }} /></i></div><div><span>Gross exposure</span><b>{snapshot.grossExposure.toFixed(0)}%</b><i><em style={{ width: `${snapshot.grossExposure}%` }} /></i></div><div><span>Correlation</span><b>34%</b><i><em style={{ width: "34%" }} /></i></div></div>
        <div className="risk-foot"><span>Hard limit engine</span><b>LOCKED</b></div>
      </section>
    </motion.div>
  );
}

function StrategyLab({ strategies, setStrategies }: { strategies: Strategy[]; setStrategies: React.Dispatch<React.SetStateAction<Strategy[]>> }) {
  const [selected, setSelected] = useState(strategies[0].name);
  const current = strategies.find((s) => s.name === selected) ?? strategies[0];
  const toggle = (name: string) => setStrategies((prev) => prev.map((s) => s.name === name ? { ...s, active: !s.active } : s));
  return (
    <motion.div className="lab-layout" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      <section className="glass strategy-list-panel">
        <div className="panel-title-row compact"><div><div className="eyebrow">STRATEGY REGISTRY</div><h3>Autonomous capital stack</h3></div><button className="icon-btn"><RefreshCw size={15} /></button></div>
        <div className="strategy-search"><Search size={14} /><input placeholder="Search strategies..." /></div>
        <div className="strategy-list">
          {strategies.map((s) => <button key={s.name} onClick={() => setSelected(s.name)} className={`strategy-row ${selected === s.name ? "selected" : ""}`}>
            <HealthRing value={s.health} /><span className="strategy-label"><b>{s.name}</b><small>{s.family} · {s.regime}</small></span><span className="strategy-alloc">{s.allocation}%</span><span className={`toggle ${s.active ? "on" : ""}`} onClick={(e) => { e.stopPropagation(); toggle(s.name); }}><i /></span>
          </button>)}
        </div>
      </section>
      <section className="glass strategy-detail-panel">
        <div className="strategy-detail-head"><div><div className="eyebrow">STRATEGY DETAIL</div><h2>{current.name}</h2><p>{current.family} strategy · adaptive regime gating · paper/shadow eligible</p></div><div className={`big-status ${current.active ? "active" : "paused"}`}>{current.active ? <Play size={13} /> : <Pause size={13} />}{current.active ? "ACTIVE" : "PAUSED"}</div></div>
        <div className="detail-metrics"><Metric label="Sharpe" value={current.sharpe.toFixed(2)} icon={BarChart3} /><Metric label="Health" value={`${current.health}%`} icon={Activity} /><Metric label="Allocation" value={`${current.allocation}%`} icon={WalletCards} /><Metric label="Net P&L" value={fmtMoney(current.pnl)} icon={TrendingUp} /></div>
        <div className="strategy-chart-card"><div className="panel-title-row compact"><div><div className="eyebrow">WALK-FORWARD EQUITY</div><h3>Out-of-sample validation</h3></div><div className="quality-chip">PASS · 8/10 windows</div></div><div className="large-chart"><div className="chart-grid" /><MiniLine values={baseEquity.map((v, i) => v + Math.sin(i / 2) * 10)} className="equity-line" /></div></div>
        <div className="strategy-lower-grid">
          <div className="inner-card"><div className="eyebrow">REGIME FIT</div><div className="fit-grid"><span className="fit good">TREND <b>94</b></span><span className="fit mid">RANGE <b>62</b></span><span className="fit good">LOW VOL <b>88</b></span><span className="fit bad">CRISIS <b>21</b></span></div></div>
          <div className="inner-card"><div className="eyebrow">DEGRADATION WATCH</div><div className="degradation"><span className="safe-icon"><ShieldCheck size={22} /></span><div><b>No material decay</b><small>Live vs shadow divergence 0.18 sigma</small></div></div></div>
          <div className="inner-card"><div className="eyebrow">SMART QUANT GATE</div><div className="mini-kpis"><span>State <b>{current.healthState || "NORMAL"}</b></span><span>Net edge <b>{current.netEdgeBps != null ? `${current.netEdgeBps.toFixed(1)} bps` : "—"}</b></span><span>Regime fit <b>{current.regimeFit != null ? `${Math.round(current.regimeFit*100)}%` : "—"}</b></span><span>Vol size <b>{current.volSize != null ? `${current.volSize.toFixed(2)}x` : "—"}</b></span><span>Corr penalty <b>{current.correlationPenalty != null ? `${Math.round(current.correlationPenalty*100)}%` : "—"}</b></span></div></div>
        </div>
      </section>
    </motion.div>
  );
}

function DayTrader() {
  const [rows,setRows]=useState<any[]>([]); const [busy,setBusy]=useState(false); const [selected,setSelected]=useState<any>(null);
  const apiUrl = process.env.NEXT_PUBLIC_QUANT_API_URL?.trim() || ((typeof window !== "undefined" && window.location.hostname === "localhost") ? "http://localhost:8000" : "");
  const scan=async()=>{ if(!apiUrl)return; setBusy(true); try{const r=await fetch(`${apiUrl}/api/scout`); const j=await r.json(); setRows(j.rankings||[]); setSelected((j.rankings||[])[0]||null);}finally{setBusy(false)} };
  useEffect(()=>{scan()},[]);
  const display=rows.length?rows:[
    {symbol:"NVDA",score:78.4,wakeExecutor:true,relativeVolume:1.8,estimatedCostBps:4.9,regime:{regime:"TREND"},information:{entropyRate:.71,mutualInformationLag1:.09,hurst:.61,predictability:.42}},
    {symbol:"SPY",score:64.1,wakeExecutor:true,relativeVolume:1.3,estimatedCostBps:3.2,regime:{regime:"RANGE"},information:{entropyRate:.82,mutualInformationLag1:.04,hurst:.48,predictability:.28}},
    {symbol:"AAPL",score:49.7,wakeExecutor:false,relativeVolume:.9,estimatedCostBps:4.2,regime:{regime:"RANGE"},information:{entropyRate:.91,mutualInformationLag1:.01,hurst:.51,predictability:.11}},
  ];
  const focus=selected||display[0];
  return <motion.div className="view-grid" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0}}>
    <section className="glass span-12 research-hero"><div><div className="eyebrow">INTRADAY SCOUT · INFORMATION THEORY</div><h2>Scan broadly. Execute narrowly.</h2><p>Ranks liquid stocks using entropy rate, mutual information, Hurst/variance-ratio structure, regime fit, liquidity and modeled trading cost before the Executor wakes.</p></div><button className="primary-btn" onClick={scan}><RefreshCw size={16}/>{busy?"SCANNING...":"RUN LIVE SCAN"}</button></section>
    <section className="glass span-8"><div className="panel-title-row compact"><div><div className="eyebrow">OPPORTUNITY SPECTRUM</div><h3>Day-trading universe</h3></div><div className="status-pill"><span className="pulse-dot"/> {display.filter((x:any)=>x.wakeExecutor).length} EXECUTOR CANDIDATES</div></div>
      <div className="execution-tape">{display.slice(0,12).map((r:any,i:number)=><motion.button style={{width:"100%",textAlign:"left",background:"transparent",border:0,color:"inherit"}} className="execution-row" key={r.symbol} onClick={()=>setSelected(r)} initial={{opacity:0,x:-10}} animate={{opacity:1,x:0}} transition={{delay:i*.035}}><b>{r.symbol}</b><span>{r.regime?.regime||"—"}</span><span className={r.wakeExecutor?"positive":"muted"}>{r.score?.toFixed?.(1)||r.score}</span><span>Hᵣ {(r.information?.entropyRate??1).toFixed(3)}</span><span>MI {(r.information?.mutualInformationLag1??0).toFixed(3)}</span><span>RVOL {(r.relativeVolume??1).toFixed(2)}x</span><span>{r.estimatedCostBps?.toFixed?.(1)||r.estimatedCostBps} bps</span><span className={`exec-state ${r.wakeExecutor?"filled":"blocked"}`}>{r.wakeExecutor?"WAKE":"PASS"}</span></motion.button>)}</div>
    </section>
    <section className="glass span-4"><div className="panel-title-row compact"><div><div className="eyebrow">SCOUT FOCUS</div><h3>{focus?.symbol||"—"}</h3></div><BrainCircuit size={17}/></div><div className="shadow-metrics"><span>Opportunity score <b>{focus?.score?.toFixed?.(1)||focus?.score||"—"}</b></span><span>Predictability <b>{focus?Math.round((focus.information?.predictability||0)*100)+"%":"—"}</b></span><span>Entropy rate <b>{focus?.information?.entropyRate?.toFixed?.(3)||"—"}</b></span><span>Hurst <b>{focus?.information?.hurst?.toFixed?.(3)||"—"}</b></span><span>Mutual information <b>{focus?.information?.mutualInformationLag1?.toFixed?.(3)||"—"}</b></span><span>Mode <b className={focus?.wakeExecutor?"positive":""}>{focus?.wakeExecutor?"EXECUTOR READY":"OBSERVE"}</b></span></div><div className="safety-banner"><ShieldCheck size={16}/><div><b>Signal is not a trade</b><span>Bayesian edge, overfit, cost, regime, correlation and risk gates still must pass.</span></div></div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">EXECUTOR GATE CHAIN</div><h3>Structure → edge → validation → sizing → execution</h3></div></div><div className="pipeline"><div className="pipe-step active"><Waves size={18}/><span>Entropy / MI</span><small>structure</small></div><i>→</i><div className="pipe-step active"><BrainCircuit size={18}/><span>Bayesian probe</span><small>P(edge &gt; BE)</small></div><i>→</i><div className="pipe-step active"><FlaskConical size={18}/><span>Deflated Sharpe</span><small>overfit defense</small></div><i>→</i><div className="pipe-step active"><CircleGauge size={18}/><span>Fractional Kelly</span><small>uncertainty sized</small></div><i>→</i><div className="pipe-step active"><ShieldCheck size={18}/><span>Risk governor</span><small>final authority</small></div></div></section>
  </motion.div>;
}

function ForwardTest() {
  const [score,setScore]=useState<any>(null); const [rows,setRows]=useState<any[]>([]); const [busy,setBusy]=useState(false);
  const apiUrl = process.env.NEXT_PUBLIC_QUANT_API_URL?.trim() || ((typeof window !== "undefined" && window.location.hostname === "localhost") ? "http://localhost:8000" : "");
  const load=async()=>{ if(!apiUrl)return; setBusy(true); try{const [a,b]=await Promise.all([fetch(`${apiUrl}/api/tracking/scoreboard`).then(r=>r.json()),fetch(`${apiUrl}/api/tracking/decisions?limit=80`).then(r=>r.json())]); setScore(a); setRows(b||[]);}finally{setBusy(false)} };
  useEffect(()=>{load(); const t=setInterval(load,10000); return()=>clearInterval(t)},[]);
  const s=score||{totalDecisions:0,settledDecisions:0,pendingDecisions:0,accepted:{winRate:null,avgNetBps:null,profitFactor:null},blocked:{winRate:null,avgNetBps:null},blockedWinners:0,blockedLosers:0,filterPrecision:0,byDecision:{},byStrategy:{}};
  const fmt=(v:any,suffix="")=>v==null?"—":`${Number(v).toFixed(2)}${suffix}`;
  return <motion.div className="view-grid" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0}}>
    <section className="glass span-12 research-hero"><div><div className="eyebrow">FORWARD-TEST LEDGER · SELF AUDITING</div><h2>Track every decision — including the trades we refuse.</h2><p>Every candidate gets a fixed-horizon shadow outcome so the engine can prove whether regime, cost, health and statistical gates are helping or blocking good trades.</p></div><button className="primary-btn" onClick={load}><RefreshCw size={16}/>{busy?"REFRESHING...":"REFRESH LEDGER"}</button></section>
    <section className="glass span-4"><div className="eyebrow">DECISIONS</div><div className="hero-equity">{s.totalDecisions}</div><div className="hero-sub"><span>{s.settledDecisions} settled</span><span className="dot-sep"/><span>{s.pendingDecisions} pending</span></div></section>
    <section className="glass span-4"><div className="eyebrow">TRADED SIGNALS</div><div className="hero-equity">{fmt(s.accepted?.winRate,"%")}</div><div className="hero-sub"><span>forward win rate</span><span className="dot-sep"/><span>{fmt(s.accepted?.avgNetBps," bps avg")}</span></div></section>
    <section className="glass span-4"><div className="eyebrow">FILTER PRECISION</div><div className="hero-equity">{fmt(s.filterPrecision,"%")}</div><div className="hero-sub"><span className="positive">{s.blockedLosers} losers avoided</span><span className="dot-sep"/><span className="neg">{s.blockedWinners} winners blocked</span></div></section>
    <section className="glass span-8"><div className="panel-title-row compact"><div><div className="eyebrow">DECISION TAPE</div><h3>What the machine did — and what happened next</h3></div><div className="status-pill"><span className="pulse-dot"/> {s.settledDecisions} OUTCOMES</div></div>
      <div className="execution-tape">{rows.slice(0,16).map((r:any)=><div className="execution-row" key={r.id}><b>{r.symbol}</b><span>{r.strategy_id}</span><span>{r.side}</span><span>{r.regime||"—"}</span><span>{r.decision}</span><span className={(r.net_forward_bps??0)>=0?"positive":"neg"}>{r.net_forward_bps==null?"PENDING":`${Number(r.net_forward_bps).toFixed(1)} bps`}</span><span className={`exec-state ${r.decision==="TRADED"?"filled":"blocked"}`}>{r.decision==="TRADED"?"TRADED":"FILTERED"}</span></div>)}</div>
    </section>
    <section className="glass span-4"><div className="panel-title-row compact"><div><div className="eyebrow">FILTER ATTRIBUTION</div><h3>Did the gates earn their keep?</h3></div><ShieldCheck size={17}/></div><div className="shadow-metrics">{Object.entries(s.byDecision||{}).slice(0,9).map(([k,v]:any)=><span key={k}>{k.replaceAll("_"," ")} <b className={(v.avgNetBps??0)>=0?"positive":"neg"}>{v.settled?`${Number(v.avgNetBps).toFixed(1)} bps`:`${v.count} pending`}</b></span>)}</div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">STRATEGY FORWARD SCOREBOARD</div><h3>Live evidence, not backtest reputation</h3></div></div><div className="strategy-strip">{Object.entries(s.byStrategy||{}).map(([k,v]:any)=><div className="strategy-tile" key={k}><div><b>{k}</b><small>{v.settled}/{v.count} settled</small></div><strong className={(v.avgNetBps??0)>=0?"positive":"neg"}>{v.avgNetBps==null?"—":`${Number(v.avgNetBps).toFixed(1)} bps`}</strong><span>Win {v.winRate==null?"—":`${Number(v.winRate).toFixed(1)}%`} · PF {v.profitFactor==null?"—":Number(v.profitFactor).toFixed(2)}</span></div>)}</div></section>
  </motion.div>;
}

function AgentMesh() {
  return <motion.div className="view-grid" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
    <section className="glass span-8 mesh-canvas"><div className="panel-title-row compact"><div><div className="eyebrow">AGENT MESH</div><h3>Autonomous decision network</h3></div><div className="status-pill"><span className="pulse-dot" /> 5 AGENTS LIVE</div></div>
      <div className="mesh-stage">
        <div className="mesh-center"><BrainCircuit size={32} /><b>CONSENSUS</b><span>LONG 78</span></div>
        {agents.map((a, i) => <motion.div className={`mesh-node node-${i + 1}`} key={a.name} initial={{ opacity: 0, scale: .8 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: i * .1 }}><span className="node-pulse" /><Bot size={18} /><b>{a.name}</b><small>{a.confidence}%</small></motion.div>)}
        <svg className="mesh-lines" viewBox="0 0 800 430"><line x1="400" y1="210" x2="125" y2="90"/><line x1="400" y1="210" x2="675" y2="90"/><line x1="400" y1="210" x2="120" y2="335"/><line x1="400" y1="210" x2="680" y2="335"/><line x1="400" y1="210" x2="400" y2="48"/></svg>
      </div>
    </section>
    <section className="glass span-4"><div className="panel-title-row compact"><div><div className="eyebrow">DECISION STREAM</div><h3>Structured conclusions</h3></div><TerminalSquare size={17} /></div><div className="agent-feed">{agents.map((a, i) => <motion.div className="agent-feed-item" key={a.name} initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .08 }}><div className="agent-feed-top"><b>{a.name}</b><span>{a.confidence}% conf</span></div><p>{a.verdict}</p><small>{a.role}</small></motion.div>)}</div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">LATEST TRADE PROPOSAL</div><h3>NVDA long · structured agent packet</h3></div><div className="quality-chip">RISK REVIEWED</div></div><div className="proposal-grid"><div><span>Direction</span><b className="positive">LONG</b></div><div><span>Confidence</span><b>0.82</b></div><div><span>Horizon</span><b>2–6h</b></div><div><span>Regime fit</span><b>0.91</b></div><div><span>Proposed risk</span><b>0.32%</b></div><div><span>Governor</span><b className="positive">PASS</b></div></div><div className="reason-chain"><span>Momentum acceleration</span><i>→</i><span>Volume confirmation</span><i>→</i><span>Regime alignment</span><i>→</i><span>Risk envelope pass</span><i>→</i><strong>EXECUTABLE</strong></div></section>
  </motion.div>;
}

function Execution() {
  return <motion.div className="view-grid" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
    <section className="glass span-8"><div className="panel-title-row compact"><div><div className="eyebrow">EXECUTION BLOTTER</div><h3>Real-time order lifecycle</h3></div><div className="status-pill"><span className="pulse-dot" /> PAPER ROUTER LIVE</div></div><div className="execution-tape">{executions.map((e, i) => <motion.div className={`execution-row ${e.state === "BLOCKED" ? "blocked" : ""}`} key={e.time} initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * .07 }}><span className="mono muted">{e.time}</span><b>{e.symbol}</b><span className={`side ${e.side === "SELL" ? "short" : "long"}`}>{e.side}</span><span>{e.size}</span><span className="mono">{e.price}</span><span className="mono muted">slip {e.slip}</span><span className={`exec-state ${e.state.toLowerCase()}`}>{e.state}</span></motion.div>)}</div></section>
    <section className="glass span-4 latency-card"><div className="panel-title-row compact"><div><div className="eyebrow">ROUTER TELEMETRY</div><h3>Execution path</h3></div><Gauge size={17} /></div><div className="latency-orb"><motion.div animate={{ scale: [1, 1.08, 1], opacity: [.8, 1, .8] }} transition={{ repeat: Infinity, duration: 2 }}><strong>18.4</strong><span>ms</span><small>median RTT</small></motion.div></div><div className="telemetry-list"><span>Gateway <b className="positive">CONNECTED</b></span><span>Market data <b>12 ms</b></span><span>Order ack <b>18 ms</b></span><span>Fill confirm <b>24 ms</b></span></div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">ORDER PIPELINE</div><h3>Proposal → risk → router → fill → reconcile</h3></div></div><div className="pipeline"><div className="pipe-step active"><Bot size={18}/><span>Agent proposal</span><small>0.82 confidence</small></div><i>→</i><div className="pipe-step active"><ShieldCheck size={18}/><span>Risk governor</span><small>12/12 pass</small></div><i>→</i><div className="pipe-step active"><Crosshair size={18}/><span>Smart router</span><small>venue selected</small></div><i>→</i><div className="pipe-step active"><Zap size={18}/><span>Fill</span><small>18 ms ack</small></div><i>→</i><div className="pipe-step active"><Database size={18}/><span>Reconcile</span><small>matched</small></div></div></section>
  </motion.div>;
}


function BrokerCloud() {
  const [apiKey, setApiKey] = useState("");
  const [workspace, setWorkspace] = useState<any>(null);
  const [connections, setConnections] = useState<any[]>([]);
  const [readiness, setReadiness] = useState<any>(null);
  const [automation, setAutomation] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [status, setStatus] = useState("SESSION LOCKED");
  const [secretRef, setSecretRef] = useState("ALPACA_MAIN");
  const [busy, setBusy] = useState(false);
  const apiUrl = process.env.NEXT_PUBLIC_QUANT_API_URL?.trim() || ((typeof window !== "undefined" && window.location.hostname === "localhost") ? "http://localhost:8000" : "");

  useEffect(() => {
    if (typeof window !== "undefined") setApiKey(sessionStorage.getItem("qos_api_key") || "");
  }, []);

  const headers = () => ({ "Content-Type":"application/json", "X-QOS-API-Key":apiKey });
  const authedFetch = async (path:string, init:RequestInit={}) => {
    const r=await fetch(`${apiUrl}${path}`,{...init,headers:{...headers(),...(init.headers||{})}});
    if(!r.ok){ let detail="Request failed"; try{ const j=await r.json(); detail=j.detail||detail; }catch{} throw new Error(detail); }
    return r.status===204?null:r.json();
  };

  const refresh = async () => {
    if (!apiUrl || !apiKey) return;
    setBusy(true);
    try {
      const [me, conns, ready, auto, audit] = await Promise.all([
        authedFetch("/api/v1/me"), authedFetch("/api/v1/broker-connections"), authedFetch("/api/v1/readiness"), authedFetch("/api/v1/automation"), authedFetch("/api/v1/audit-events?limit=6")
      ]);
      setWorkspace(me); setConnections(conns); setReadiness(ready); setAutomation(auto); setEvents(audit); setStatus("CONTROL PLANE ONLINE");
    } catch (e:any) { setStatus(e?.message?.toUpperCase?.() || "AUTH / BACKEND ERROR"); }
    finally { setBusy(false); }
  };

  useEffect(() => { if(apiKey) refresh(); }, [apiKey]);

  const connectWorkspace = async () => {
    if(typeof window!=="undefined") sessionStorage.setItem("qos_api_key",apiKey);
    await refresh();
  };
  const disconnect = () => {
    if(typeof window!=="undefined") sessionStorage.removeItem("qos_api_key");
    setApiKey(""); setWorkspace(null); setConnections([]); setReadiness(null); setAutomation(null); setEvents([]); setStatus("SESSION LOCKED");
  };
  const addAlpaca = async () => {
    if(!apiUrl || !apiKey) return;
    setBusy(true);
    try { await authedFetch("/api/v1/broker-connections",{method:"POST",body:JSON.stringify({adapter_slug:"alpaca_paper",name:"Alpaca Paper",secret_ref:secretRef,config:{},execution_enabled:false})}); setStatus("ALPACA PAPER INSTALLED"); await refresh(); }
    catch(e:any){ setStatus(e.message.toUpperCase()); } finally{ setBusy(false); }
  };
  const toggleExecution = async (id:string, enabled:boolean) => {
    setBusy(true);
    try { await authedFetch(`/api/v1/broker-connections/${id}/execution`,{method:"POST",body:JSON.stringify({enabled,confirmation:enabled?"ARM PAPER":""})}); setStatus(enabled?"PAPER EXECUTION ARMED":"EXECUTION DISARMED"); await refresh(); }
    catch(e:any){ setStatus(e.message.toUpperCase()); } finally{ setBusy(false); }
  };
  const health = async (id:string) => {
    setBusy(true); try { await authedFetch(`/api/v1/broker-connections/${id}/health`); setStatus("BROKER HEALTHY"); await refresh(); } catch(e:any){ setStatus(e.message.toUpperCase()); } finally{ setBusy(false); }
  };
  const reconcile = async (id:string) => {
    setBusy(true); try { await authedFetch(`/api/v1/broker-connections/${id}/reconcile`,{method:"POST"}); setStatus("BROKER RECONCILED"); await refresh(); } catch(e:any){ setStatus(e.message.toUpperCase()); } finally{ setBusy(false); }
  };

  const armed=connections.filter(c=>c.execution_enabled).length;
  const readySteps=[
    {label:"Workspace session",ok:!!workspace,detail:workspace?.name||"Authenticate API key"},
    {label:"Broker installed",ok:connections.length>0,detail:connections.length?`${connections.length} connector${connections.length===1?"":"s"}`:"Add a paper broker"},
    {label:"Paper router armed",ok:armed>0,detail:armed?`${armed} execution route active`:"Explicit arm required"},
    {label:"Automation policy",ok:!!automation?.enabled,detail:automation?.enabled?"Autonomous cycle enabled":"Optional until validation"},
  ];
  const readinessPct=Math.round((readySteps.filter(x=>x.ok).length/readySteps.length)*100);

  return <motion.div className="view-grid broker-cloud-view" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-8}}>
    <section className="glass span-12 broker-cloud-hero">
      <div className="broker-hero-copy"><div className="eyebrow">BROKER CLOUD · MULTI-TENANT CONTROL PLANE</div><h2>Connect capital infrastructure without coupling strategy code.</h2><p>One normalized execution layer for every workspace. Broker credentials remain server-side, paper routing requires an explicit arm, and every control-plane change lands in the audit stream.</p><div className="broker-status-line"><span className={`pulse-dot ${workspace?"":"muted-dot"}`}/><b>{status}</b><span>·</span><span>REAL-MONEY ROUTING HARD DISABLED</span></div></div>
      <div className="readiness-orb"><motion.div animate={{rotate:360}} transition={{duration:24,repeat:Infinity,ease:"linear"}} className="readiness-ring"/><strong>{readinessPct}%</strong><span>workspace ready</span></div>
    </section>

    <section className="glass span-4 broker-session-card">
      <div className="panel-title-row compact"><div><div className="eyebrow">01 · WORKSPACE SESSION</div><h3>{workspace?.name || "Authenticate workspace"}</h3></div><LockKeyhole size={18}/></div>
      {!workspace?<><div className="broker-auth-box"><input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="qos_..."/><button disabled={busy||!apiKey} onClick={connectWorkspace}>{busy?"CONNECTING…":"OPEN SESSION"}</button></div><small className="helper">Session-only storage. The key is cleared when this browser tab session ends.</small></>:<div className="workspace-identity"><div><span>Workspace</span><b>{workspace.name}</b></div><div><span>Plan</span><b>{workspace.plan}</b></div><div><span>Role</span><b>{workspace.api_key_role||"admin"}</b></div><button onClick={disconnect}>LOCK SESSION</button></div>}
    </section>

    <section className="glass span-8 readiness-card">
      <div className="panel-title-row compact"><div><div className="eyebrow">LAUNCH READINESS</div><h3>Workspace activation path</h3></div><div className="quality-chip">{readiness?.database?.ok===false?"DB CHECK FAILED":"PAPER SAFE"}</div></div>
      <div className="readiness-steps">{readySteps.map((step,i)=><div className={`readiness-step ${step.ok?"done":""}`} key={step.label}><div className="step-number">{step.ok?<ShieldCheck size={14}/>:String(i+1).padStart(2,"0")}</div><div><b>{step.label}</b><span>{step.detail}</span></div><strong>{step.ok?"READY":"PENDING"}</strong></div>)}</div>
    </section>

    <section className="glass span-5">
      <div className="panel-title-row compact"><div><div className="eyebrow">02 · INSTALL CONNECTOR</div><h3>Alpaca Paper</h3></div><Network size={18}/></div>
      <div className="connector-install"><label>Secret reference<span>Credentials stay on the backend</span></label><input value={secretRef} onChange={e=>setSecretRef(e.target.value.toUpperCase())} placeholder="ALPACA_MAIN"/><button disabled={!workspace||busy} onClick={addAlpaca}><Network size={14}/> INSTALL PAPER ADAPTER</button></div>
      <small className="helper">Server expects QOS_SECRET_{secretRef}_API_KEY and QOS_SECRET_{secretRef}_API_SECRET.</small>
    </section>

    <section className="glass span-7">
      <div className="panel-title-row compact"><div><div className="eyebrow">03 · EXECUTION ROUTES</div><h3>Installed broker adapters</h3></div><button className="icon-btn" disabled={busy} onClick={refresh}><RefreshCw size={15}/></button></div>
      <div className="connector-grid polished">{connections.length?connections.map(c=><motion.div className={`connector-card ${c.execution_enabled?"armed":""}`} key={c.id} whileHover={{y:-2}}><div className="connector-brand"><div className="connector-icon"><Network size={18}/></div><div><b>{c.name}</b><small>{c.adapter_slug}</small></div><span className={c.execution_enabled?"armed-chip":"monitor-chip"}>{c.execution_enabled?"ARMED":"MONITOR"}</span></div><div className="connector-meta"><span>Secret ref<b>{c.secret_ref}</b></span><span>Mode<b>PAPER ONLY</b></span></div><div className="connector-actions"><button onClick={()=>health(c.id)}>HEALTH</button><button onClick={()=>reconcile(c.id)}>RECONCILE</button><button className={c.execution_enabled?"danger-lite":"arm-action"} onClick={()=>toggleExecution(c.id,!c.execution_enabled)}>{c.execution_enabled?"DISARM":"ARM PAPER"}</button></div></motion.div>):<div className="empty-connector"><Network size={20}/><b>No execution route installed</b><span>Add Alpaca Paper to begin broker-connected shadow/paper operation.</span></div>}</div>
    </section>

    <section className="glass span-7">
      <div className="panel-title-row compact"><div><div className="eyebrow">CONTROL-PLANE AUDIT</div><h3>Latest workspace activity</h3></div><Database size={17}/></div>
      <div className="audit-stream">{events.length?events.map((e:any)=><div className="audit-event" key={e.id}><span className="audit-node"/><div><b>{String(e.type).replaceAll("_"," ")}</b><small>{new Date(e.ts*1000).toLocaleTimeString()} · immutable workspace event</small></div><code>#{e.id}</code></div>):<div className="audit-empty">Workspace events will appear here after authentication.</div>}</div>
    </section>

    <section className="glass span-5">
      <div className="panel-title-row compact"><div><div className="eyebrow">AUTONOMY ENVELOPE</div><h3>{automation?.enabled?"Autonomous paper loop active":"Automation staged"}</h3></div><Radio size={17} className={automation?.enabled?"live-icon":""}/></div>
      <div className="automation-summary"><div><span>Policy</span><b className={automation?.enabled?"positive":""}>{automation?.enabled?"ENABLED":"DISABLED"}</b></div><div><span>Min confidence</span><b>{automation?.min_confidence?`${Math.round(automation.min_confidence*100)}%`:"78% default"}</b></div><div><span>Order ceiling</span><b>{automation?.max_order_notional?fmtMoney(automation.max_order_notional):"$1,000"}</b></div><div><span>Cooldown</span><b>{automation?.cooldown_seconds?`${Math.round(automation.cooldown_seconds/60)} min`:"30 min"}</b></div></div>
      <div className="safety-banner"><ShieldCheck size={16}/><div><b>Capital boundary intact</b><span>No live-money adapter can be armed in this release.</span></div></div>
    </section>

    <section className="glass span-12 plugin-contract-card"><div className="panel-title-row compact"><div><div className="eyebrow">BROKER PLUGIN CONTRACT</div><h3>Normalized strategy → policy → adapter → reconcile</h3></div></div><div className="pipeline"><div className="pipe-step active"><BrainCircuit size={18}/><span>Strategy</span><small>normalized signal</small></div><i>→</i><div className="pipe-step active"><ShieldCheck size={18}/><span>Risk</span><small>tenant envelope</small></div><i>→</i><div className="pipe-step active"><Network size={18}/><span>Adapter</span><small>broker-specific I/O</small></div><i>→</i><div className="pipe-step active"><Database size={18}/><span>Reconcile</span><small>tenant ledger</small></div></div></section>
  </motion.div>;
}

function RiskView({ killSwitch, setKillSwitch }: { killSwitch: boolean; setKillSwitch: (v: boolean) => void }) {
  const rules = [
    ["Daily loss limit", "$3,500", "$642", 18], ["Gross exposure", "75%", "48%", 64], ["Single strategy", "22%", "18%", 82], ["Single name", "12%", "7.4%", 62], ["Correlation cluster", "0.70", "0.34", 49], ["Slippage deviation", "2.0σ", "0.18σ", 9],
  ];
  return <motion.div className="view-grid" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
    <section className={`glass span-12 master-risk ${killSwitch ? "tripped" : ""}`}><div className="master-risk-copy"><div className="eyebrow">MASTER SYSTEM CONTROL</div><h2>{killSwitch ? "TRADING HALTED" : "Risk governor armed"}</h2><p>{killSwitch ? "All new order generation and routing are blocked. Position monitoring remains online." : "Independent hard limits are active. No agent or strategy can bypass the governor."}</p></div><button className={`kill-button ${killSwitch ? "restore" : ""}`} onClick={() => setKillSwitch(!killSwitch)}>{killSwitch ? <Play size={18}/> : <ShieldAlert size={18}/>}<span>{killSwitch ? "RESTORE PAPER ROUTER" : "MASTER KILL SWITCH"}</span></button></section>
    <section className="glass span-8"><div className="panel-title-row compact"><div><div className="eyebrow">POLICY MATRIX</div><h3>Hard risk envelopes</h3></div><LockKeyhole size={17}/></div><div className="policy-grid">{rules.map(([name, limit, current, usage]) => <div className="policy-row" key={name as string}><div><b>{name}</b><span>limit {limit}</span></div><strong>{current}</strong><div className="policy-bar"><motion.i initial={{ width: 0 }} animate={{ width: `${usage}%` }} /></div><span className="policy-pass"><ShieldCheck size={13}/> PASS</span></div>)}</div></section>
    <section className="glass span-4"><div className="panel-title-row compact"><div><div className="eyebrow">CIRCUIT BREAKERS</div><h3>Automatic defense</h3></div><TriangleAlert size={17}/></div><div className="breaker-list"><span><i className="breaker-dot safe"/>Stale market data<b>ARMED</b></span><span><i className="breaker-dot safe"/>Broker disconnect<b>ARMED</b></span><span><i className="breaker-dot safe"/>Abnormal slippage<b>ARMED</b></span><span><i className="breaker-dot safe"/>Drawdown spike<b>ARMED</b></span><span><i className="breaker-dot safe"/>Duplicate orders<b>ARMED</b></span><span><i className="breaker-dot safe"/>Volatility shock<b>ARMED</b></span></div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">RISK EVENT LOG</div><h3>Recent interventions</h3></div></div><div className="incident-grid"><div className="incident"><span className="incident-time">11:55:46</span><TriangleAlert size={16}/><div><b>AMD order blocked</b><small>Single-name exposure would exceed configured envelope.</small></div><strong>BLOCKED</strong></div><div className="incident"><span className="incident-time">10:41:18</span><ShieldCheck size={16}/><div><b>Vector Momentum resized</b><small>Volatility-adjusted size reduced by 14% before routing.</small></div><strong className="positive">RESIZED</strong></div></div></section>
  </motion.div>;
}

function Research() {
  return <motion.div className="view-grid" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
    <section className="glass span-12 research-hero"><div><div className="eyebrow">AUTONOMOUS RESEARCH FACTORY</div><h2>Research → validate → stress → promote</h2><p>Every candidate strategy must survive out-of-sample, transaction-cost, and stress testing before it can reach paper allocation.</p></div><button className="primary-btn"><FlaskConical size={16}/> RUN RESEARCH CYCLE</button></section>
    <section className="glass span-7"><div className="panel-title-row compact"><div><div className="eyebrow">EXPERIMENT QUEUE</div><h3>Automated validation runs</h3></div><div className="status-pill"><span className="pulse-dot"/> 3 RUNNING</div></div><div className="experiment-list">{[["Pairs half-life sweep","WALK FORWARD",72],["Volatility gate v4","MONTE CARLO",48],["London breakout costs","SLIPPAGE",91],["Neural footprint ablation","RESEARCH",33]].map((e) => <div className="experiment" key={e[0] as string}><div><b>{e[0]}</b><span>{e[1]}</span></div><div className="experiment-progress"><motion.i initial={{width:0}} animate={{width:`${e[2]}%`}}/></div><strong>{e[2]}%</strong></div>)}</div></section>
    <section className="glass span-5"><div className="panel-title-row compact"><div><div className="eyebrow">PROMOTION GATE</div><h3>Production eligibility</h3></div><ShieldCheck size={17}/></div><div className="gate-stack"><div className="gate done"><ShieldCheck/>Data integrity<span>PASS</span></div><div className="gate done"><ShieldCheck/>Walk-forward<span>PASS</span></div><div className="gate done"><ShieldCheck/>Cost sensitivity<span>PASS</span></div><div className="gate running"><RefreshCw/>Monte Carlo<span>RUNNING</span></div><div className="gate"><LockKeyhole/>Shadow period<span>LOCKED</span></div></div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">PARAMETER LANDSCAPE</div><h3>Robustness surface</h3></div></div><div className="heatmap">{Array.from({length: 120}).map((_, i) => <motion.i key={i} initial={{opacity:0}} animate={{opacity:.25 + ((i * 37) % 70)/100}} transition={{delay:(i%20)*.01}} style={{"--heat": `${40 + ((i * 29) % 160)}` } as React.CSSProperties}/>)}</div><div className="heatmap-labels"><span>slower / wider</span><b>STABLE PLATEAU</b><span>faster / tighter</span></div></section>
  </motion.div>;
}

function Shadow() {
  return <motion.div className="view-grid" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
    <section className="glass span-12 replay-head"><div><div className="eyebrow">SHADOW EXECUTION REPLAY</div><h2>Live behavior vs expected model</h2></div><div className="replay-controls"><button className="icon-btn"><Play size={15}/></button><span>11:42:18</span><div className="replay-track"><i style={{width:"61%"}}/><em style={{left:"61%"}}/></div><span>12:00:00</span></div></section>
    <section className="glass span-8"><div className="panel-title-row compact"><div><div className="eyebrow">EXECUTION DIVERGENCE</div><h3>Model vs shadow</h3></div><div className="quality-chip">0.18σ · NORMAL</div></div><div className="dual-chart"><div className="chart-grid"/><MiniLine values={baseEquity} className="equity-line"/><MiniLine values={baseEquity.map((v,i)=>v + Math.sin(i*.7)*3 - 3)} className="shadow-line"/></div><div className="legend"><span><i className="legend-live"/>Expected model</span><span><i className="legend-shadow"/>Shadow execution</span></div></section>
    <section className="glass span-4"><div className="panel-title-row compact"><div><div className="eyebrow">QUALITY DELTA</div><h3>Execution realism</h3></div></div><div className="shadow-metrics"><span>Expected P&L <b>$2,418</b></span><span>Shadow P&L <b>$2,372</b></span><span>Execution delta <b className="negative">-$46</b></span><span>Median slippage <b>0.7 bps</b></span><span>Fill ratio <b className="positive">99.2%</b></span><span>Decision drift <b>0.18σ</b></span></div></section>
    <section className="glass span-12"><div className="panel-title-row compact"><div><div className="eyebrow">FORENSIC TIMELINE</div><h3>Trade decision chain</h3></div></div><div className="timeline"><div className="timeline-event"><span>11:42:18.112</span><Bot/><b>Signal generated</b><small>Vector Momentum · ES long 0.86</small></div><div className="timeline-event"><span>11:42:18.119</span><ShieldCheck/><b>Risk approved</b><small>Size reduced 3 → 2 contracts</small></div><div className="timeline-event"><span>11:42:18.127</span><Crosshair/><b>Order routed</b><small>Paper venue · marketable limit</small></div><div className="timeline-event"><span>11:42:18.145</span><Zap/><b>Filled</b><small>18 ms acknowledgment · +0.25 tick</small></div></div></section>
  </motion.div>;
}

export default function QuantOS() {
  const [section, setSection] = useState<Section>("command");
  const [strategies, setStrategies] = useState(initialStrategies);
  const [killSwitch, setKillSwitch] = useState(false);
  const [palette, setPalette] = useState(false);
  const [connected, setConnected] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot>({ equity: 100000, dayPnl: 0, drawdown: 0, grossExposure: 0, regime: "TREND", latencyMs: 18.4, activeStrategies: 4, riskState: "SAFE", engineRunning: true, mode: "PAPER/SHADOW", positionCount: 0 });
  const localTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); }
      if (e.key === "Escape") setPalette(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  useEffect(() => {
    let ws: WebSocket | null = null;
    const startFallback = () => {
      if (localTimer.current) return;
      localTimer.current = setInterval(() => {
        setSnapshot((s) => {
          const nudge = (Math.random() - .42) * 34;
          const equity = Math.max(100000, s.equity + nudge);
          return { ...s, equity, dayPnl: s.dayPnl + nudge, latencyMs: Math.max(8, Math.min(38, s.latencyMs + (Math.random() - .5) * 2.2)) };
        });
      }, 1250);
    };
    const apiUrl = process.env.NEXT_PUBLIC_QUANT_API_URL?.trim() || ((typeof window !== "undefined" && window.location.hostname === "localhost") ? "http://localhost:8000" : "");
    if (apiUrl) {
      fetch(`${apiUrl}/api/snapshot`).then(r => r.ok ? r.json() : null).then(d => d && setSnapshot(d)).catch(() => {});
      Promise.all([fetch(`${apiUrl}/api/strategies`).then(r => r.ok ? r.json() : []), fetch(`${apiUrl}/api/intelligence`).then(r => r.ok ? r.json() : {strategies:[]})]).then(([rows,intel]) => { if (rows?.length) { const byId=new Map((intel?.strategies||[]).map((x:any)=>[x.strategy_id,x])); setStrategies(rows.map((x:any) => { const q:any=byId.get(x.id)||{}; return { ...x, pnl: 0, sharpe:q.metrics?.sharpe||0, health:q.health??x.health, healthState:q.healthState, netEdgeBps:q.net_edge_bps, regimeFit:q.regime_fit, volSize:q.volatility_size_multiplier, correlationPenalty:q.correlation_penalty }; })); } }).catch(() => {});
    }
    const streamUrl = process.env.NEXT_PUBLIC_QUANT_WS_URL?.trim() || ((typeof window !== "undefined" && window.location.hostname === "localhost") ? "ws://localhost:8000/ws/stream" : "");
    if (streamUrl) {
      try {
        ws = new WebSocket(streamUrl);
        ws.onopen = () => { setConnected(true); if (localTimer.current) { clearInterval(localTimer.current); localTimer.current = null; } };
        ws.onmessage = (event) => {
          try { const data = JSON.parse(event.data); if (data.type === "snapshot") setSnapshot(data.payload); } catch { /* ignore demo noise */ }
        };
        ws.onerror = () => { setConnected(false); startFallback(); };
        ws.onclose = () => { setConnected(false); startFallback(); };
      } catch { startFallback(); }
    } else {
      startFallback();
    }
    const connectTimeout = setTimeout(() => { if (!connected) startFallback(); }, 900);
    return () => { clearTimeout(connectTimeout); ws?.close(); if (localTimer.current) clearInterval(localTimer.current); localTimer.current = null; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const metrics = useMemo(() => [
    { label: "Day P&L", value: `+${fmtMoney(snapshot.dayPnl)}`, delta: "+1.22%", icon: TrendingUp },
    { label: "Max drawdown", value: `${snapshot.drawdown.toFixed(2)}%`, delta: "+0.08% buffer", icon: TrendingDown },
    { label: "Gross exposure", value: `${snapshot.grossExposure.toFixed(0)}%`, delta: "+27% headroom", icon: CircleGauge },
    { label: "Router latency", value: `${snapshot.latencyMs.toFixed(1)} ms`, delta: "+ healthy", icon: Zap },
  ], [snapshot]);

  const setKillSwitchRemote = (v: boolean) => {
    setKillSwitch(v);
    const apiUrl = process.env.NEXT_PUBLIC_QUANT_API_URL?.trim() || ((typeof window !== "undefined" && window.location.hostname === "localhost") ? "http://localhost:8000" : "");
    if (apiUrl) fetch(`${apiUrl}/api/risk/kill-switch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: v }) }).catch(() => {});
  };

  const renderView = () => {
    switch (section) {
      case "daytrade": return <DayTrader />;
      case "tracking": return <ForwardTest />;
      case "strategies": return <StrategyLab strategies={strategies} setStrategies={setStrategies} />;
      case "agents": return <AgentMesh />;
      case "execution": return <Execution />;
      case "brokers": return <BrokerCloud />;
      case "risk": return <RiskView killSwitch={killSwitch} setKillSwitch={setKillSwitchRemote} />;
      case "research": return <Research />;
      case "shadow": return <Shadow />;
      default: return <Overview snapshot={snapshot} strategies={strategies} />;
    }
  };

  return (
    <div className={`quant-shell ${killSwitch ? "system-halted" : ""}`}>
      <div className="ambient"><div className="aurora a1"/><div className="aurora a2"/><div className="noise"/></div>
      <aside className="sidebar">
        <div className="brand"><motion.div className="brand-mark" animate={{ rotate: [0, 360] }} transition={{ repeat: Infinity, duration: 28, ease: "linear" }}><Hexagon size={30}/><span>Q</span></motion.div><div><b>QUANT OS</b><small>Autonomous Command</small></div></div>
        <nav>{nav.map((item) => { const Icon = item.icon; return <button key={item.id} onClick={() => setSection(item.id)} className={section === item.id ? "active" : ""}><Icon size={17}/><span>{item.label}</span>{item.id === "risk" && <i className="nav-safe"/>}</button>; })}</nav>
        <div className="sidebar-spacer"/>
        <div className="system-stack"><div className="system-line"><span>DATA BUS</span><b><i className="tiny-dot"/> LIVE</b></div><div className="system-line"><span>RISK CORE</span><b><i className="tiny-dot"/> LOCKED</b></div><div className="system-line"><span>MODE</span><b>DAY TRADER QUANT V2</b></div></div>
        <button className="settings-btn"><Settings2 size={16}/><span>System settings</span></button>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar-left"><div className={`autonomy-badge ${killSwitch ? "halted" : ""}`}><span className="pulse-dot"/>{killSwitch ? "AUTONOMY HALTED" : "AUTONOMOUS MODE ACTIVE"}</div><div className="environment"><span>{snapshot.mode || "PAPER / SHADOW"}</span><ChevronDown size={13}/></div></div>
          <div className="topbar-right"><div className="connection-status"><Radio size={13}/><span>{connected ? "BACKEND STREAM" : "LOCAL SIM"}</span></div><button className="command-button" onClick={() => setPalette(true)}><Search size={14}/><span>Command</span><Kbd>⌘ K</Kbd></button><button className="icon-btn notification"><Bell size={16}/><i/></button><div className="account-chip"><span>QX</span><div><b>Quant Operator</b><small>Admin</small></div></div></div>
        </header>

        <div className="content-head"><div><div className="breadcrumb">SYSTEM / <span>{nav.find(n => n.id === section)?.label.toUpperCase()}</span></div><h1>{nav.find(n => n.id === section)?.label}</h1></div><div className="market-clock"><AlarmClock size={15}/><div><b>11:58:07</b><span>NEW YORK · MARKET OPEN</span></div></div></div>

        {section === "command" && <div className="metrics-grid">{metrics.map((m) => <Metric key={m.label} {...m} />)}</div>}

        <AnimatePresence mode="wait">{renderView()}</AnimatePresence>

        <footer className="statusbar"><span><i className="tiny-dot"/> SYSTEM NOMINAL</span><span>EVENT BUS <b>2.4K/s</b></span><span>MARKET FEEDS <b>6/6</b></span><span>STRATEGIES <b>{strategies.filter(s=>s.active).length}/{strategies.length}</b></span><span>RISK POLICIES <b>12/12</b></span><span className="version">QUANT OS v0.7 · FORWARD-TRACKED DAY-TRADER BETA</span></footer>
      </main>

      <AnimatePresence>
        {palette && <motion.div className="palette-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={() => setPalette(false)}><motion.div className="palette" initial={{ opacity: 0, scale: .96, y: -16 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .98 }} onMouseDown={(e)=>e.stopPropagation()}><div className="palette-search"><Command size={17}/><input autoFocus placeholder="Jump to a module or run a system command..."/><Kbd>ESC</Kbd></div><div className="palette-group"><span>NAVIGATE</span>{nav.map((n)=>{const Icon=n.icon; return <button key={n.id} onClick={()=>{setSection(n.id);setPalette(false)}}><Icon size={15}/>{n.label}<small>Open module</small></button>})}</div><div className="palette-group"><span>SYSTEM</span><button onClick={()=>{setKillSwitchRemote(true);setPalette(false)}}><ShieldAlert size={15}/>Trigger master kill switch<small>Paper router only</small></button></div></motion.div></motion.div>}
      </AnimatePresence>

      <AnimatePresence>
        {killSwitch && <motion.div className="halt-strip" initial={{ y: -60 }} animate={{ y: 0 }} exit={{ y: -60 }}><ShieldAlert size={16}/><b>MASTER HALT ACTIVE</b><span>New orders are blocked. Monitoring and reconciliation remain online.</span><button onClick={()=>setKillSwitchRemote(false)}>RESTORE PAPER MODE <X size={13}/></button></motion.div>}
      </AnimatePresence>
    </div>
  );
}
