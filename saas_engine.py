from __future__ import annotations
import time, uuid
from dataclasses import asdict
from . import tenant_store
from .brokers import create, SubmitOrder
from .market_data import MarketDataHub
from .risk_engine import RiskGovernor
from .secrets import secret_store
from .strategies import run as run_strategy
from .smart_quant import evaluate_candidate, health_score, health_state
from .backtest import backtest
from .quant_research import validation_report
from . import tracking

hub=MarketDataHub(); governor=RiskGovernor()

DEFAULT_STRATEGIES=[
    {'strategy_id':'vector-momentum','symbol':'NVDA'},
    {'strategy_id':'helix-reversion','symbol':'AAPL'},
    {'strategy_id':'london-vector','symbol':'ES'},
    {'strategy_id':'vwap-reclaim','symbol':'SPY'},
    {'strategy_id':'opening-range','symbol':'NVDA'},
    {'strategy_id':'rvol-momentum','symbol':'AAPL'},
]

def _decision_label(sig, intel, health_state_value, validation, confidence_floor:float, stale:bool, cooldown:bool):
    if sig.action not in ('BUY','SELL'): return None, ''
    if sig.confidence < confidence_floor: return 'BLOCKED_BY_CONFIDENCE','confidence_below_threshold'
    if stale: return 'BLOCKED_BY_DATA','stale_market_data'
    if intel.regime == 'CRISIS' or 'regime_mismatch' in intel.blockers: return 'BLOCKED_BY_REGIME','regime_mismatch'
    if 'edge_below_cost' in intel.blockers: return 'BLOCKED_BY_COST','edge_below_cost'
    if 'correlation_concentration' in intel.blockers: return 'BLOCKED_BY_CORRELATION','correlation_concentration'
    if health_state_value == 'QUARANTINED': return 'QUARANTINED','strategy_health_quarantined'
    if health_state_value == 'SHADOW_ONLY': return 'SHADOW_ONLY','strategy_health_shadow_only'
    if not validation.get('eligible',False): return 'BLOCKED_BY_STAT_VALIDATION','statistical_validation'
    if cooldown: return 'BLOCKED_BY_COOLDOWN','cooldown'
    return 'TRADED',''

def _gross_exposure(positions, equity:float):
    return sum(abs(float(p.market_value)) for p in positions)/max(equity,1.0)*100.0

def cycle_workspace(cfg:dict):
    wid=cfg['workspace_id']; conn=tenant_store.get_connection(wid,cfg['connection_id'])
    if not conn or not conn['enabled'] or not conn['execution_enabled']:
        tenant_store.event(wid,'automation_skipped',{'reason':'connection disabled','connection_id':cfg['connection_id']}); return {'workspace_id':wid,'submitted':0,'reason':'connection disabled'}
    try:
        creds=secret_store.get(conn['secret_ref']); adapter=create(conn['adapter_slug'],creds,conn['config'])
        if not adapter.paper_only:
            tenant_store.event(wid,'automation_blocked',{'reason':'live-money adapter prohibited'}); return {'workspace_id':wid,'submitted':0,'reason':'live-money adapter prohibited'}
        account=adapter.account(); positions=adapter.list_positions(); gross=_gross_exposure(positions,account.equity)
    except Exception as e:
        tenant_store.event(wid,'automation_broker_error',{'error':str(e)}); return {'workspace_id':wid,'submitted':0,'error':str(e)}
    submitted=0; signals=[]
    items=(cfg.get('strategies') or DEFAULT_STRATEGIES)
    histories={}
    for i in items:
        sym=str(i.get('symbol','')).upper(); sid=str(i.get('strategy_id',''))
        if not sym: continue
        intraday=sid in {'vwap-reclaim','opening-range','rvol-momentum'}
        histories[sym]=hub.history(sym,'5d','5m') if intraday else hub.history(sym,'1y','1d')
    for item in items:
        sid=str(item.get('strategy_id','')); symbol=str(item.get('symbol','')).upper()
        if not sid or not symbol: continue
        try:
            bars=histories[symbol]; sig=run_strategy(sid,symbol,bars); quote=hub.quote(symbol); age=max(0,time.time()-quote.ts)
            other=[h for sym,h in histories.items() if sym!=symbol]
            intel=evaluate_candidate(sid,symbol,sig.score,sig.confidence,bars,other)
            bt=backtest(sid,symbol,bars); metrics=bt['metrics']; h=health_score(metrics,intel.regime_fit,max(.5,1-intel.correlation_penalty)); hs=health_state(h); validation=validation_report(bt,25,intel.regime_fit,h)
            idict={**intel.as_dict(),'health':h,'healthState':hs,'metrics':metrics,'validation':validation}
            signals.append({'strategy_id':sid,'symbol':symbol,'action':sig.action,'confidence':sig.confidence,'score':sig.score,'source':quote.source,'stale':quote.stale,'intelligence':idict})
            if sig.action not in ('BUY','SELL'): continue
            cooldown=time.time()-tenant_store.last_automation_trade(wid,sid,symbol)<int(cfg['cooldown_seconds'])
            label, block_reason=_decision_label(sig,intel,hs,validation,float(cfg['min_confidence']),bool(quote.stale or age>=30),cooldown)
            track_id=tracking.record_decision(workspace_id=wid,strategy_id=sid,symbol=symbol,side=sig.action,decision=label,reference_price=quote.price,
                confidence=sig.confidence,signal_score=sig.score,block_reason=block_reason,intelligence=idict,validation=validation,
                metadata={'connectionId':conn['id'],'adapter':conn['adapter_slug'],'source':quote.source,'stale':quote.stale})
            if label!='TRADED':
                tenant_store.event(wid,'automation_signal_blocked',{'tracking_id':track_id,'strategy_id':sid,'symbol':symbol,'reason':block_reason,'decision':label,'blockers':intel.blockers,'health':h,'healthState':hs}); continue
            kelly_frac=max(.001,float(validation['kelly']['fractionalKelly']))
            notional=min(float(cfg['max_order_notional']), max(account.equity,1)*kelly_frac)*intel.volatility_size_multiplier
            qty=max(0.000001,notional/max(quote.price,0.01))
            risk_decision=governor.evaluate(kill_switch=False,strategy_active=True,confidence=sig.confidence,requested_risk_pct=float(cfg['requested_risk_pct']),gross_exposure=gross,drawdown=0.0,market_data_fresh=True,quantity=qty,regime_fit=intel.regime_fit,net_edge_bps=intel.net_edge_bps,correlation_penalty=intel.correlation_penalty,strategy_health=h,health_state=hs)
            if not risk_decision['approved']:
                with tracking.store._lock:
                    tc=tracking.store.connect(); tc.execute("UPDATE forward_decisions SET decision='BLOCKED_BY_RISK',block_reason=? WHERE id=?",(risk_decision['reason'],track_id)); tc.commit(); tc.close()
                tenant_store.event(wid,'automation_signal_blocked',{'tracking_id':track_id,'strategy_id':sid,'symbol':symbol,'reason':risk_decision['reason'],'decision':'BLOCKED_BY_RISK'}); continue
            qty=float(risk_decision['resized_quantity'])
            order=adapter.submit_order(SubmitOrder(symbol=symbol,quantity=qty,side='buy' if sig.action=='BUY' else 'sell',order_type='market',time_in_force='day',client_order_id='qos-auto-'+uuid.uuid4().hex[:20]))
            local_id=tenant_store.save_order(wid,conn['id'],asdict(order),sid); tenant_store.mark_automation_trade(wid,sid,symbol); submitted+=1
            if order.filled_avg_price:
                direction=1 if sig.action=='BUY' else -1
                slip=(float(order.filled_avg_price)/max(quote.price,1e-12)-1)*10000*direction
                tracking.attach_execution(track_id,slip,{'localOrderId':local_id,'brokerOrderId':order.broker_order_id,'fillPrice':order.filled_avg_price})
            tenant_store.event(wid,'automation_order_submitted',{'tracking_id':track_id,'local_order_id':local_id,'broker_order_id':order.broker_order_id,'strategy_id':sid,'symbol':symbol,'confidence':sig.confidence})
        except Exception as e:
            tenant_store.event(wid,'automation_strategy_error',{'strategy_id':sid,'symbol':symbol,'error':str(e)})
    try:
        latest=adapter.list_positions(); tenant_store.replace_positions(wid,conn['id'],[asdict(p) for p in latest])
    except Exception: pass
    return {'workspace_id':wid,'submitted':submitted,'signals':signals}

def cycle_all():
    return [cycle_workspace(cfg) for cfg in tenant_store.list_automations(True)]
