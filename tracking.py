from __future__ import annotations
import json, os, sqlite3, time, uuid
from dataclasses import dataclass
from typing import Any, Callable
from . import store

DEFAULT_HORIZON_SECONDS = int(os.getenv('QOS_TRACKING_HORIZON_SECONDS','1800'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS forward_decisions (
 id TEXT PRIMARY KEY,
 workspace_id TEXT NOT NULL DEFAULT '',
 ts REAL NOT NULL,
 settle_after REAL NOT NULL,
 settled_at REAL,
 strategy_id TEXT NOT NULL,
 symbol TEXT NOT NULL,
 side TEXT NOT NULL,
 decision TEXT NOT NULL,
 block_reason TEXT NOT NULL DEFAULT '',
 reference_price REAL NOT NULL,
 settle_price REAL,
 forward_return_bps REAL,
 net_forward_bps REAL,
 confidence REAL NOT NULL DEFAULT 0,
 signal_score REAL NOT NULL DEFAULT 0,
 regime TEXT NOT NULL DEFAULT '',
 regime_fit REAL NOT NULL DEFAULT 0,
 expected_edge_bps REAL NOT NULL DEFAULT 0,
 estimated_cost_bps REAL NOT NULL DEFAULT 0,
 net_edge_bps REAL NOT NULL DEFAULT 0,
 correlation_penalty REAL NOT NULL DEFAULT 0,
 volatility_size_multiplier REAL NOT NULL DEFAULT 1,
 health REAL NOT NULL DEFAULT 0,
 health_state TEXT NOT NULL DEFAULT '',
 bayes_probability REAL,
 deflated_sharpe REAL,
 entropy_rate REAL,
 mutual_information REAL,
 hurst REAL,
 rvol REAL,
 actual_slippage_bps REAL,
 metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_forward_decisions_ts ON forward_decisions(ts DESC);
CREATE INDEX IF NOT EXISTS idx_forward_decisions_strategy ON forward_decisions(strategy_id, symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_forward_decisions_decision ON forward_decisions(decision, settled_at);
CREATE INDEX IF NOT EXISTS idx_forward_decisions_workspace ON forward_decisions(workspace_id, ts DESC);
'''

def init_tracking():
    with store._lock:
        c=store.connect(); c.executescript(SCHEMA); c.commit(); c.close()

def _nested(d:dict, path:list[str], default=None):
    cur=d
    for k in path:
        if not isinstance(cur,dict) or k not in cur:return default
        cur=cur[k]
    return cur

def record_decision(*, strategy_id:str, symbol:str, side:str, decision:str, reference_price:float,
                    confidence:float=0, signal_score:float=0, block_reason:str='', intelligence:dict|None=None,
                    validation:dict|None=None, metadata:dict|None=None, workspace_id:str='', horizon_seconds:int|None=None)->str:
    init_tracking(); now=time.time(); intel=intelligence or {}; val=validation or {}; meta=metadata or {}
    did='dec_'+uuid.uuid4().hex[:22]
    horizon=max(1,int(horizon_seconds or DEFAULT_HORIZON_SECONDS))
    info=_nested(val,['informationTheory'],{}) or _nested(val,['structure'],{}) or {}
    bayes=_nested(val,['bayesian'],{}) or _nested(val,['edge'],{}) or {}
    dsr=_nested(val,['deflatedSharpe'],{}) or _nested(val,['overfit'],{}) or {}
    values=(did,workspace_id,now,now+horizon,None,strategy_id,symbol.upper(),side.upper(),decision,block_reason,
            float(reference_price),None,None,None,float(confidence),float(signal_score),str(intel.get('regime','')),
            float(intel.get('regime_fit',intel.get('regimeFit',0)) or 0),float(intel.get('expected_edge_bps',intel.get('expectedEdgeBps',0)) or 0),
            float(intel.get('estimated_cost_bps',intel.get('estimatedCostBps',0)) or 0),float(intel.get('net_edge_bps',intel.get('netEdgeBps',0)) or 0),
            float(intel.get('correlation_penalty',intel.get('correlationPenalty',0)) or 0),float(intel.get('volatility_size_multiplier',intel.get('volatilitySizeMultiplier',1)) or 1),
            float(intel.get('health',0) or 0),str(intel.get('healthState','')), _to_float(bayes.get('probabilityEdgeAboveBreakeven',bayes.get('probability',None))),
            _to_float(dsr.get('dsr',None)), _to_float(info.get('entropyRate',intel.get('entropyRate',None))),
            _to_float(info.get('mutualInformation',intel.get('mutualInformation',None))), _to_float(info.get('hurst',intel.get('hurst',None))),
            _to_float(meta.get('rvol',intel.get('rvol',None))), None, json.dumps(meta,separators=(',',':')))
    with store._lock:
        c=store.connect(); c.execute('''INSERT INTO forward_decisions(
        id,workspace_id,ts,settle_after,settled_at,strategy_id,symbol,side,decision,block_reason,reference_price,settle_price,
        forward_return_bps,net_forward_bps,confidence,signal_score,regime,regime_fit,expected_edge_bps,estimated_cost_bps,net_edge_bps,
        correlation_penalty,volatility_size_multiplier,health,health_state,bayes_probability,deflated_sharpe,entropy_rate,mutual_information,hurst,rvol,actual_slippage_bps,metadata_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',values); c.commit(); c.close()
    return did

def _to_float(v):
    try:return float(v) if v is not None else None
    except Exception:return None

def attach_execution(decision_id:str, slippage_bps:float|None=None, metadata:dict|None=None):
    init_tracking()
    with store._lock:
        c=store.connect(); row=c.execute('SELECT metadata_json FROM forward_decisions WHERE id=?',(decision_id,)).fetchone()
        if not row: c.close(); return False
        meta=json.loads(row['metadata_json'] or '{}'); meta.update(metadata or {})
        c.execute('UPDATE forward_decisions SET actual_slippage_bps=?,metadata_json=? WHERE id=?',(slippage_bps,json.dumps(meta,separators=(',',':')),decision_id)); c.commit(); c.close()
    return True

def settle_matured(quote_fn:Callable[[str],Any], limit:int=250)->dict:
    init_tracking(); now=time.time(); c=store.connect(); rows=c.execute('''SELECT * FROM forward_decisions WHERE settled_at IS NULL AND settle_after<=? ORDER BY settle_after LIMIT ?''',(now,limit)).fetchall(); c.close()
    settled=0; failed=0
    for r in rows:
        try:
            q=quote_fn(r['symbol']); price=float(q.price if hasattr(q,'price') else q['price']); ref=float(r['reference_price'])
            direction=1 if str(r['side']).upper() in {'BUY','COVER'} else -1
            gross=(price/ref-1)*10000*direction
            net=gross-float(r['estimated_cost_bps'] or 0)
            with store._lock:
                c=store.connect(); c.execute('''UPDATE forward_decisions SET settled_at=?,settle_price=?,forward_return_bps=?,net_forward_bps=? WHERE id=?''',(now,price,gross,net,r['id'])); c.commit(); c.close()
            settled+=1
        except Exception:
            failed+=1
    return {'settled':settled,'failed':failed,'pending':max(0,len(rows)-settled)}

def list_decisions(limit:int=200, decision:str|None=None, workspace_id:str=''):
    init_tracking(); c=store.connect(); args=[]; where=[]
    if workspace_id: where.append('workspace_id=?'); args.append(workspace_id)
    if decision: where.append('decision=?'); args.append(decision)
    sql='SELECT * FROM forward_decisions' + ((' WHERE '+' AND '.join(where)) if where else '') + ' ORDER BY ts DESC LIMIT ?'; args.append(min(max(limit,1),2000))
    rows=c.execute(sql,args).fetchall(); c.close(); out=[]
    for r in rows:
        d=dict(r)
        try:d['metadata']=json.loads(d.pop('metadata_json'))
        except Exception:d['metadata']={}
        out.append(d)
    return out

def _agg(rows:list[dict])->dict:
    settled=[r for r in rows if r.get('net_forward_bps') is not None]
    if not settled:return {'count':len(rows),'settled':0,'winRate':None,'avgNetBps':None,'totalNetBps':0,'profitFactor':None}
    vals=[float(r['net_forward_bps']) for r in settled]; pos=[v for v in vals if v>0]; neg=[v for v in vals if v<0]
    pf=(sum(pos)/abs(sum(neg))) if neg else (999.0 if pos else 0.0)
    return {'count':len(rows),'settled':len(settled),'winRate':round(100*len(pos)/len(vals),2),'avgNetBps':round(sum(vals)/len(vals),3),'totalNetBps':round(sum(vals),3),'profitFactor':round(pf,3)}

def scoreboard(workspace_id:str='')->dict:
    rows=list_decisions(2000,workspace_id=workspace_id)
    settled=[r for r in rows if r.get('net_forward_bps') is not None]
    by_decision={}
    for key in sorted({r['decision'] for r in rows}): by_decision[key]=_agg([r for r in rows if r['decision']==key])
    by_strategy={}
    for key in sorted({r['strategy_id'] for r in rows}): by_strategy[key]=_agg([r for r in rows if r['strategy_id']==key])
    by_symbol={}
    for key in sorted({r['symbol'] for r in rows}): by_symbol[key]=_agg([r for r in rows if r['symbol']==key])
    by_regime={}
    for key in sorted({r['regime'] for r in rows if r.get('regime')}): by_regime[key]=_agg([r for r in rows if r.get('regime')==key])
    accepted=[r for r in rows if r['decision']=='TRADED']; blocked=[r for r in rows if r['decision']!='TRADED']
    false_blocks=[r for r in blocked if r.get('net_forward_bps') is not None and float(r['net_forward_bps'])>0]
    saved_blocks=[r for r in blocked if r.get('net_forward_bps') is not None and float(r['net_forward_bps'])<0]
    return {
        'horizonSeconds':DEFAULT_HORIZON_SECONDS,
        'totalDecisions':len(rows),'settledDecisions':len(settled),'pendingDecisions':len(rows)-len(settled),
        'accepted':_agg(accepted),'blocked':_agg(blocked),'all':_agg(rows),
        'blockedWinners':len(false_blocks),'blockedLosers':len(saved_blocks),
        'filterPrecision': round(100*len(saved_blocks)/max(1,len(saved_blocks)+len(false_blocks)),2),
        'byDecision':by_decision,'byStrategy':by_strategy,'bySymbol':by_symbol,'byRegime':by_regime,
    }
