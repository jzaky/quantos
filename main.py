from __future__ import annotations
import asyncio, random, time
from dataclasses import dataclass, asdict
from typing import Literal
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from .production import production_guard, cors_origins, readiness_payload
from pydantic import BaseModel, Field
from .market_data import MarketDataHub
from .risk_engine import RiskGovernor
from . import store
from .strategies import run as run_strategy
from .backtest import backtest, walk_forward
from .smart_quant import evaluate_candidate, health_score, health_state
from .scout import scan as scout_scan, DAY_UNIVERSE
from .quant_research import validation_report
from . import tracking
from .api_saas import router as saas_router
from . import tenant_store
from .saas_engine import cycle_all as saas_cycle_all

app=FastAPI(title='Quant OS Broker Platform',version='0.7.0')
app.middleware('http')(production_guard)
app.add_middleware(CORSMiddleware,allow_origins=cors_origins(),allow_credentials=False,allow_methods=['GET','POST','PUT','DELETE','OPTIONS'],allow_headers=['Content-Type','X-QOS-API-Key','X-QOS-Bootstrap-Token','X-QOS-Idempotency-Key','X-Request-ID'])
app.include_router(saas_router)

@dataclass
class StrategyState:
    id:str; name:str; family:str; allocation:float; health:int; active:bool; regime:str; symbol:str

STRATEGIES=[
 StrategyState('vector-momentum','Vector Momentum','Momentum',22,94,True,'TREND','NVDA'),
 StrategyState('helix-reversion','Helix Reversion','Mean Rev',18,87,True,'RANGE','AAPL'),
 StrategyState('london-vector','London Vector','Breakout',14,82,True,'TREND','ES'),
 StrategyState('mercury-pairs','Mercury Pairs','Stat Arb',12,76,False,'RANGE','MSFT'),
 StrategyState('vol-surface','Vol Surface','Volatility',10,73,False,'VOL','BTC'),
 StrategyState('atlas-macro','Atlas Macro','Macro',8,70,False,'MACRO','GC'),
 StrategyState('cash-reserve','Cash Reserve','Defense',16,100,True,'ANY','USD'),
]
AGENTS=[
 {'id':'REGIME-01','role':'regime_classifier','confidence':.96,'verdict':'TREND_LOW_VOL'},
 {'id':'FLOW-07','role':'order_flow','confidence':.82,'verdict':'BUY_IMBALANCE'},
 {'id':'MACRO-03','role':'macro','confidence':.71,'verdict':'NEUTRAL_POSITIVE'},
 {'id':'VOL-09','role':'volatility','confidence':.88,'verdict':'EXPANSION'},
 {'id':'RISK-00','role':'risk_governor','confidence':.99,'verdict':'WITHIN_LIMITS'},
]
hub=MarketDataHub(); governor=RiskGovernor()
state={'startingEquity':100000.0,'cash':100000.0,'equity':100000.0,'dayPnl':0.0,'drawdown':0.0,'peakEquity':100000.0,'grossExposure':0.0,'regime':'TREND','latencyMs':18.4,'riskState':'SAFE','killSwitch':False,'lastUpdate':0.0,'engineRunning':True,'lastCycle':None}
watchlist=['NVDA','AAPL','MSFT','ES','BTC','GC','CL']
last_signals=[]
last_intelligence=[]

class KillSwitchBody(BaseModel): enabled:bool
class EngineBody(BaseModel): enabled:bool
class PaperOrder(BaseModel):
 symbol:str=Field(min_length=1,max_length=16); side:Literal['BUY','SELL','SHORT','COVER']; quantity:float=Field(gt=0,le=100000); strategy_id:str; confidence:float=Field(ge=0,le=1); requested_risk_pct:float=Field(gt=0,le=5)
class BacktestBody(BaseModel): strategy_id:str; symbol:str; period:str='1y'; interval:str='1d'; fee_bps:float=Field(default=2,ge=0,le=100)

def strat(sid): return next((s for s in STRATEGIES if s.id==sid),None)
def mark_positions():
    positions=store.get_positions(); unreal=0.0; gross=0.0; market_value=0.0; rendered=[]
    for p in positions:
        q=hub.quote(p['symbol']); qty=float(p['qty']); avg=float(p['avg_price']); pnl=(q.price-avg)*qty; signed_value=qty*q.price; notional=abs(signed_value); unreal+=pnl; gross+=notional; market_value+=signed_value
        rendered.append({**p,'mark':round(q.price,4),'market_value':round(signed_value,2),'unrealized_pnl':round(pnl,2),'source':q.source,'stale':q.stale})
    # Cash already reflects every fill. Portfolio equity is cash plus signed mark-to-market value
    # of open positions; adding only unrealized PnL would incorrectly drop equity by cost basis.
    eq=state['cash']+market_value
    realized=eq-state['startingEquity']-unreal
    state['equity']=eq; state['dayPnl']=eq-state['startingEquity']; state['peakEquity']=max(state['peakEquity'],eq); state['drawdown']=max(0,(state['peakEquity']-eq)/state['peakEquity']*100); state['grossExposure']=gross/max(eq,1)*100
    store.save_equity(eq,state['cash'],unreal,realized); return rendered

def snapshot():
    positions=mark_positions(); active=sum(1 for s in STRATEGIES if s.active)
    return {'equity':round(state['equity'],2),'dayPnl':round(state['dayPnl'],2),'drawdown':round(state['drawdown'],3),'grossExposure':round(state['grossExposure'],2),'regime':state['regime'],'latencyMs':round(state['latencyMs'],1),'activeStrategies':active,'riskState':'HALTED' if state['killSwitch'] else state['riskState'],'engineRunning':state['engineRunning'],'lastCycle':state['lastCycle'],'positionCount':len(positions),'mode':'PAPER/SHADOW','liveExecution':False}

def evaluate_order(o:PaperOrder,quote_age=0.0,intelligence:dict|None=None,strategy_health:float=100.0,strategy_health_state:str='NORMAL'):
    s=strat(o.strategy_id); intelligence=intelligence or {}
    return governor.evaluate(kill_switch=state['killSwitch'],strategy_active=bool(s and s.active),confidence=o.confidence,requested_risk_pct=o.requested_risk_pct,gross_exposure=state['grossExposure'],drawdown=state['drawdown'],market_data_fresh=quote_age<30,quantity=o.quantity,regime_fit=float(intelligence.get('regime_fit',1.0)),net_edge_bps=float(intelligence.get('net_edge_bps',999.0)),correlation_penalty=float(intelligence.get('correlation_penalty',0.0)),strategy_health=strategy_health,health_state=strategy_health_state)

def execute_order(o:PaperOrder, automated=False, intelligence:dict|None=None, strategy_health:float=100.0, strategy_health_state:str='NORMAL', decision_id:str|None=None):
    started=time.perf_counter(); q=hub.quote(o.symbol); age=max(0,time.time()-q.ts); decision=evaluate_order(o,age,intelligence,strategy_health,strategy_health_state)
    if not decision['approved']:
        store.add_order(ts=time.time(),symbol=o.symbol.upper(),side=o.side,qty=o.quantity,fill_price=None,strategy_id=o.strategy_id,status='BLOCKED',confidence=o.confidence,risk_pct=o.requested_risk_pct,reason=decision['reason'],shadow_price=None,slippage_bps=0)
        store.event('order_blocked',{'symbol':o.symbol.upper(),'strategy':o.strategy_id,'reason':decision['reason'],'automated':automated}); return None,decision
    qty=float(decision['resized_quantity']); slip_bps=random.uniform(-1.5,2.5); fill=q.price*(1+slip_bps/10000*(1 if o.side in ('BUY','COVER') else -1)); shadow=q.price
    signed=qty if o.side in ('BUY','COVER') else -qty
    notional=fill*qty
    state['cash']-=notional if signed>0 else -notional
    store.save_portfolio_state(state['cash'],state['startingEquity'],state['peakEquity'])
    pos=store.upsert_position(o.symbol.upper(),o.strategy_id,signed,fill)
    oid=store.add_order(ts=time.time(),symbol=o.symbol.upper(),side=o.side,qty=qty,fill_price=fill,strategy_id=o.strategy_id,status='FILLED',confidence=o.confidence,risk_pct=o.requested_risk_pct,reason='paper fill',shadow_price=shadow,slippage_bps=slip_bps)
    state['latencyMs']=max(1,(time.perf_counter()-started)*1000+random.uniform(6,18)); store.event('paper_fill',{'order_id':oid,'symbol':o.symbol.upper(),'side':o.side,'qty':qty,'fill':fill,'shadow':shadow,'slippage_bps':slip_bps,'strategy':o.strategy_id,'automated':automated});
    if decision_id: tracking.attach_execution(decision_id,slip_bps,{'orderId':oid,'fillPrice':fill,'routedQuantity':qty})
    mark_positions()
    return {'accepted':True,'mode':'PAPER','orderId':oid,'symbol':o.symbol.upper(),'side':o.side,'requestedQuantity':o.quantity,'routedQuantity':qty,'fillPrice':round(fill,6),'shadowPrice':round(shadow,6),'slippageBps':round(slip_bps,3),'position':pos,'risk':decision},decision

def _decision_label(sig, intel, hs, validation, recent_filled:bool=False):
    if sig.action not in ('BUY','SELL'): return None, ''
    if sig.confidence < .74: return 'BLOCKED_BY_CONFIDENCE', 'confidence_below_threshold'
    if intel.regime == 'CRISIS': return 'BLOCKED_BY_REGIME', 'crisis_regime'
    if 'regime_mismatch' in intel.blockers: return 'BLOCKED_BY_REGIME', 'regime_mismatch'
    if 'edge_below_cost' in intel.blockers: return 'BLOCKED_BY_COST', 'edge_below_cost'
    if 'correlation_concentration' in intel.blockers: return 'BLOCKED_BY_CORRELATION', 'correlation_concentration'
    if hs == 'QUARANTINED': return 'QUARANTINED', 'strategy_health_quarantined'
    if hs == 'SHADOW_ONLY': return 'SHADOW_ONLY', 'strategy_health_shadow_only'
    if not validation.get('eligible',False): return 'BLOCKED_BY_STAT_VALIDATION', 'statistical_validation'
    if recent_filled: return 'BLOCKED_BY_COOLDOWN', 'cooldown'
    return 'TRADED', ''

def run_engine_cycle():
    global last_signals, last_intelligence
    tracking.settle_matured(hub.quote)
    signals=[]; intel_rows=[]
    active=[s for s in STRATEGIES if s.active and s.id!='cash-reserve']
    histories={s.symbol:hub.history(s.symbol,'1y','1d') for s in active}
    regimes=[]
    for s in active:
        bars=histories[s.symbol]; sig=run_strategy(s.id,s.symbol,bars); q=hub.quote(s.symbol)
        other=[h for sym,h in histories.items() if sym!=s.symbol]
        intel=evaluate_candidate(s.id,s.symbol,sig.score,sig.confidence,bars,other)
        bt=backtest(s.id,s.symbol,bars)
        h=health_score(bt['metrics'],intel.regime_fit,execution_quality=max(.5,1-intel.correlation_penalty))
        hs=health_state(h); validation=validation_report(bt,25,intel.regime_fit,h)
        s.health=int(round(h)); s.regime=intel.regime
        regimes.append(intel.regime)
        idict=intel.as_dict(); idict.update({'health':h,'healthState':hs,'metrics':bt['metrics'],'validation':validation})
        intel_rows.append(idict)
        payload={**sig.__dict__,'price':q.price,'source':q.source,'stale':q.stale,'intelligence':idict}
        signals.append(payload)
        store.add_strategy_run(s.id,s.symbol,sig.score,sig.confidence,q.price,sig.action,{'reason':sig.reason,'source':q.source,'intelligence':idict})
        if sig.action in ('BUY','SELL'):
            recent=[x for x in store.list_orders(50) if x['strategy_id']==s.id and x['symbol']==s.symbol and x['status']=='FILLED' and time.time()-x['ts']<1800]
            decision, reason=_decision_label(sig,intel,hs,validation,bool(recent))
            decision_id=tracking.record_decision(strategy_id=s.id,symbol=s.symbol,side=sig.action,decision=decision,reference_price=q.price,
                confidence=sig.confidence,signal_score=sig.score,block_reason=reason,intelligence=idict,validation=validation,
                metadata={'source':q.source,'stale':q.stale,'signalReason':sig.reason})
            if decision=='TRADED':
                eq=max(state['equity'],1); target_notional=eq*(s.allocation/100)*.08*intel.volatility_size_multiplier
                qty=max(.0001,target_notional/max(q.price,1)); o=PaperOrder(symbol=s.symbol,side=sig.action,quantity=qty,strategy_id=s.id,confidence=sig.confidence,requested_risk_pct=.20)
                result, risk_decision=execute_order(o,automated=True,intelligence=idict,strategy_health=h,strategy_health_state=hs,decision_id=decision_id)
                if result is None:
                    # Risk governor can still veto after the statistical decision layer.
                    with store._lock:
                        c=store.connect(); c.execute("UPDATE forward_decisions SET decision='BLOCKED_BY_RISK',block_reason=? WHERE id=?",(risk_decision.get('reason','risk_governor'),decision_id)); c.commit(); c.close()
            else:
                store.event('smart_trade_blocked',{'decisionId':decision_id,'decision':decision,'strategy':s.id,'symbol':s.symbol,'blockers':intel.blockers,'health':h,'healthState':hs,'netEdgeBps':intel.net_edge_bps,'reason':reason})
    if regimes:
        state['regime']=max(set(regimes),key=regimes.count)
    last_signals=signals; last_intelligence=intel_rows
    state['lastCycle']=time.time(); state['lastUpdate']=time.time(); mark_positions()

async def saas_engine_loop():
    await asyncio.sleep(3)
    while True:
        try:
            await asyncio.to_thread(saas_cycle_all)
            await asyncio.sleep(15)
        except Exception as e:
            await asyncio.sleep(10)

async def engine_loop():
    await asyncio.sleep(1)
    while True:
        try:
            if state['engineRunning'] and not state['killSwitch']:
                await asyncio.to_thread(run_engine_cycle)
            await asyncio.sleep(15)
        except Exception as e:
            store.event('engine_error',{'error':str(e)})
            await asyncio.sleep(10)

@app.on_event('startup')
async def startup():
    store.init_db(); tenant_store.init_db(); tracking.init_tracking(); tenant_store.ensure_automation_schema(); tenant_store.migrate_production_schema()
    persisted=store.load_portfolio_state()
    if persisted:
        state['cash']=float(persisted.get('cash',state['cash'])); state['startingEquity']=float(persisted.get('startingEquity',state['startingEquity'])); state['peakEquity']=float(persisted.get('peakEquity',state['peakEquity']))
    else:
        store.save_portfolio_state(state['cash'],state['startingEquity'],state['peakEquity'])
    mark_positions(); asyncio.create_task(engine_loop()); asyncio.create_task(saas_engine_loop())

@app.get('/health')
def health(): return {'ok':True,'phase':7,'mode':'day-trader-quant+paper-shadow+saas','live_execution':False,'database':str(store.DB_PATH),'saas_database':str(tenant_store.DB_PATH),'broker_plugins':True,'smart_quant':True,'day_trader_quant':True,'forward_tracking':True,'version':'0.7.0'}

@app.get('/ready')
def ready(): return readiness_payload()
@app.get('/api/snapshot')
def get_snapshot(): return snapshot()
@app.get('/api/strategies')
def get_strategies(): return [asdict(s) for s in STRATEGIES]
@app.post('/api/strategies/{sid}/toggle')
def toggle_strategy(sid:str):
    s=strat(sid)
    if not s: raise HTTPException(404,'Strategy not found')
    s.active=not s.active; store.event('strategy_toggle',{'strategy':sid,'active':s.active}); return asdict(s)
@app.get('/api/positions')
def positions(): return mark_positions()
@app.get('/api/orders')
def orders(limit:int=Query(100,ge=1,le=1000)): return store.list_orders(limit)
@app.get('/api/events')
def events(limit:int=Query(100,ge=1,le=1000)): return store.list_events(limit)
@app.get('/api/strategy-runs')
def strategy_runs(limit:int=Query(100,ge=1,le=1000)): return store.strategy_runs(limit)
@app.get('/api/intelligence')
def intelligence(): return {'regime':state['regime'],'strategies':last_intelligence,'formulaVersion':'day-trader-quant-v2','gates':['entropy_rate','mutual_information','bayesian_edge','deflated_sharpe','change_detection','regime_fit','edge_after_costs','correlation_limit','fractional_kelly','volatility_sizing','strategy_health']}
@app.get('/api/equity')
def equity(limit:int=Query(500,ge=1,le=5000)): return store.equity_history(limit)
@app.get('/api/agents')
def agents(): return AGENTS
@app.get('/api/market/quotes')
def quotes(symbols:str='NVDA,AAPL,MSFT,ES,BTC,GC,CL'):
    out=[]
    for s in [x.strip().upper() for x in symbols.split(',') if x.strip()]:
        q=hub.quote(s); out.append(asdict(q))
    return out
@app.get('/api/market/history/{symbol}')
def history(symbol:str,period:str='3mo',interval:str='1d'): return hub.history(symbol,period,interval)
@app.post('/api/risk/kill-switch')
def kill(body:KillSwitchBody): state['killSwitch']=body.enabled; store.event('kill_switch',{'enabled':body.enabled}); return {'enabled':body.enabled,'riskState':'HALTED' if body.enabled else 'SAFE'}
@app.post('/api/engine')
def engine(body:EngineBody): state['engineRunning']=body.enabled; store.event('engine_toggle',{'enabled':body.enabled}); return {'enabled':body.enabled}
@app.post('/api/paper/orders/evaluate')
def evaluate(o:PaperOrder): return evaluate_order(o)
@app.post('/api/paper/orders/submit')
def submit(o:PaperOrder):
    result,decision=execute_order(o)
    if not result: raise HTTPException(status_code=409,detail=decision)
    return result
@app.post('/api/research/backtest')
def do_backtest(b:BacktestBody): return backtest(b.strategy_id,b.symbol.upper(),hub.history(b.symbol,b.period,b.interval),b.fee_bps)
@app.post('/api/research/walk-forward')
def do_walkforward(b:BacktestBody): return walk_forward(b.strategy_id,b.symbol.upper(),hub.history(b.symbol,b.period,b.interval))
@app.get('/api/shadow/divergence')
def shadow_divergence(limit:int=100):
    rows=[r for r in store.list_orders(limit) if r['status']=='FILLED' and r['shadow_price']]
    vals=[abs(float(r['fill_price'])-float(r['shadow_price']))/float(r['shadow_price'])*10000 for r in rows]
    return {'fills':len(rows),'meanAbsSlippageBps':round(sum(vals)/max(len(vals),1),3),'maxAbsSlippageBps':round(max(vals,default=0),3),'recent':rows[:30]}


@app.get('/api/scout')
def scout(universe: str | None = Query(default=None)):
    symbols=[x.strip().upper() for x in universe.split(',') if x.strip()] if universe else DAY_UNIVERSE
    return {'mode':'DAY_TRADING_SCOUT','interval':'5m','universe':symbols,'rankings':scout_scan(hub,symbols)}

@app.get('/api/intelligence/{strategy_id}/{symbol}')
def intelligence(strategy_id:str,symbol:str,period:str='5d',interval:str='5m',trials:int=25):
    bars=hub.history(symbol.upper(),period,interval)
    sig=run_strategy(strategy_id,symbol.upper(),bars)
    intel=evaluate_candidate(strategy_id,symbol.upper(),sig.score,sig.confidence,bars,[])
    bt=backtest(strategy_id,symbol.upper(),bars)
    h=health_score(bt['metrics'],intel.regime_fit,max(.5,1-intel.correlation_penalty))
    report=validation_report(bt,trials,intel.regime_fit,h)
    return {'signal':sig.__dict__,'intelligence':intel.as_dict(),'health':h,'healthState':health_state(h),'backtest':bt['metrics'],'validation':report}

@app.get('/api/tracking/scoreboard')
def tracking_scoreboard(): return tracking.scoreboard()

@app.get('/api/tracking/decisions')
def tracking_decisions(limit:int=Query(200,ge=1,le=2000),decision:str|None=None): return tracking.list_decisions(limit,decision)

@app.post('/api/tracking/settle')
def tracking_settle(): return tracking.settle_matured(hub.quote,1000)

@app.websocket('/ws/stream')
async def stream(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            state['lastUpdate']=time.time(); payload=await asyncio.to_thread(snapshot); payload['quotes']=await asyncio.to_thread(lambda: [asdict(hub.quote(s)) for s in watchlist]); payload['signals']=last_signals[-8:]; await ws.send_json({'type':'snapshot','payload':payload}); await asyncio.sleep(2)
    except WebSocketDisconnect: return
