from __future__ import annotations
import time
from dataclasses import asdict
from . import order_safety, tenant_store
from .brokers import create, SubmitOrder
from .market_data import MarketDataHub
from .risk_engine import RiskGovernor
from .secret_store import secret_store
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

class _Order:
    def __init__(self,d:dict): self.__dict__.update(d)

def _mark_blocked(track_id,reason:str):
    with tracking.store._lock:
        tc=tracking.store.connect(); tc.execute("UPDATE forward_decisions SET decision='BLOCKED_BY_RISK',block_reason=? WHERE id=?",(reason,track_id)); tc.commit(); tc.close()

def cycle_workspace(cfg:dict):
    wid=cfg['workspace_id']; conn=tenant_store.get_connection(wid,cfg['connection_id'])
    if not conn or not conn['enabled'] or not conn['execution_enabled']:
        tenant_store.event(wid,'automation_skipped',{'reason':'connection disabled','connection_id':cfg['connection_id']}); return {'workspace_id':wid,'submitted':0,'reason':'connection disabled'}
    ks=order_safety.kill_switch_status(wid)
    if ks['engaged']:
        tenant_store.event(wid,'automation_halted',{'reasons':ks['reasons']}); return {'workspace_id':wid,'submitted':0,'reason':'kill switch engaged'}
    try:
        creds=secret_store.get(conn['secret_ref']); adapter=create(conn['adapter_slug'],creds,conn['config'])
        if not adapter.paper_only:
            tenant_store.event(wid,'automation_blocked',{'reason':'live-money adapter prohibited'}); return {'workspace_id':wid,'submitted':0,'reason':'live-money adapter prohibited'}
        # Earlier orders whose outcome is unknown are resolved at the broker before anything new is sent.
        pending=order_safety.reconcile_pending(wid,conn['id'],adapter)
        if pending:
            tenant_store.event(wid,'automation_blocked',{'reason':'unreconciled orders','client_order_ids':[p['client_order_id'] for p in pending]}); return {'workspace_id':wid,'submitted':0,'reason':'unreconciled orders'}
        account=adapter.account(); positions=adapter.list_positions(); gross=_gross_exposure(positions,account.equity)
        drawdown=order_safety.observe_drawdown(wid,conn['id'],account.equity) if account.equity>0 else 100.0
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
            fresh=not quote.stale and age<order_safety.max_quote_age()
            ex=order_safety.exposure(positions,max(account.equity,1e-9),symbol,qty if sig.action=='BUY' else -qty,quote.price)
            # Sizing pass on live inputs. order_safety re-runs the same checks on fresh broker state.
            risk_decision=governor.evaluate(kill_switch=order_safety.kill_switch_status(wid)['engaged'],strategy_active=True,confidence=sig.confidence,requested_risk_pct=float(cfg['requested_risk_pct']),gross_exposure=ex['post_gross_pct'],drawdown=drawdown,market_data_fresh=fresh,quantity=qty,regime_fit=intel.regime_fit,net_edge_bps=intel.net_edge_bps,correlation_penalty=intel.correlation_penalty,strategy_health=h,health_state=hs,symbol_exposure=ex['post_symbol_pct'])
            if not risk_decision['approved']:
                _mark_blocked(track_id,risk_decision['reason'])
                tenant_store.event(wid,'automation_signal_blocked',{'tracking_id':track_id,'strategy_id':sid,'symbol':symbol,'reason':risk_decision['reason'],'decision':'BLOCKED_BY_RISK'}); continue
            qty=float(risk_decision['resized_quantity'])
            side='buy' if sig.action=='BUY' else 'sell'
            bar_ts=int(float(bars[-1]['ts'])) if bars else int(time.time()//60*60)
            intent=order_safety.OrderIntent(
                workspace_id=wid,connection_id=conn['id'],symbol=symbol,side=side,quantity=qty,
                # One order per strategy, symbol, side and signal bar: a retry of the same decision reuses the key.
                idempotency_key=f'auto:{sid}:{symbol}:{side}:{bar_ts}',source='automation',strategy_id=sid,
                model=order_safety.ModelContext(confidence=sig.confidence,requested_risk_pct=float(cfg['requested_risk_pct']),regime_fit=intel.regime_fit,
                    net_edge_bps=intel.net_edge_bps,correlation_penalty=intel.correlation_penalty,strategy_health=h,health_state=hs),
            )
            try:
                res=order_safety.submit_order(intent,adapter=adapter,connection=conn,quote_fn=hub.quote,governor=governor)
            except order_safety.OrderRejected as e:
                if e.code=='outcome_unknown':
                    tenant_store.mark_automation_trade(wid,sid,symbol)  # may have traded: honour the cooldown
                else:
                    _mark_blocked(track_id,f'{e.code}: {e.message}')
                tenant_store.event(wid,'automation_order_refused',{'tracking_id':track_id,'strategy_id':sid,'symbol':symbol,'code':e.code,'reason':e.message}); continue
            if res.get('idempotent_replay'):
                tenant_store.event(wid,'automation_duplicate_suppressed',{'tracking_id':track_id,'client_order_id':res['client_order_id']}); continue
            local_id=res['local_order_id']; tenant_store.mark_automation_trade(wid,sid,symbol); submitted+=1
            order=_Order(res['order'])
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
