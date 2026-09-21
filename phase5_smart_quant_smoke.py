from __future__ import annotations
import math, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.smart_quant import classify_regime, evaluate_candidate, health_score, health_state, volatility_size_multiplier
from app.risk_engine import RiskGovernor
from app.backtest import backtest
from app.strategies import run

bars=[]; p=100.0
for i in range(220):
    # controlled uptrend with realistic noise
    ret=.0012 + math.sin(i/9)*.0015
    o=p; p=o*(1+ret); bars.append({'ts':i,'open':o,'high':max(o,p)*1.002,'low':min(o,p)*.998,'close':p,'volume':1_000_000+i*100})

sig=run('vector-momentum','TEST',bars)
intel=evaluate_candidate('vector-momentum','TEST',sig.score,max(sig.confidence,.90),bars,[])
assert classify_regime(bars)['regime'] in {'TREND','RANGE','HIGH_VOL'}
assert intel.estimated_cost_bps>0
assert intel.expected_edge_bps>=0
assert .25 <= volatility_size_multiplier(bars) <= 1.5
metrics=backtest('vector-momentum','TEST',bars)['metrics']
for k in ('sharpe','sortino','calmar','profitFactor','expectancyPct','maxDrawdownPct'): assert k in metrics
health=health_score(metrics,intel.regime_fit)
assert 0<=health<=100 and health_state(health) in {'FULL','NORMAL','REDUCED','SHADOW_ONLY','QUARANTINED'}

g=RiskGovernor()
approved=g.evaluate(kill_switch=False,strategy_active=True,confidence=.95,requested_risk_pct=.2,gross_exposure=10,drawdown=.2,market_data_fresh=True,quantity=10,regime_fit=.9,net_edge_bps=12,correlation_penalty=.1,strategy_health=85,health_state='FULL')
assert approved['approved'] is True
blocked=g.evaluate(kill_switch=False,strategy_active=True,confidence=.95,requested_risk_pct=.2,gross_exposure=10,drawdown=.2,market_data_fresh=True,quantity=10,regime_fit=.9,net_edge_bps=-1,correlation_penalty=.1,strategy_health=85,health_state='FULL')
assert blocked['approved'] is False and blocked['policy_checks']['edge_after_costs'] is False
quarantined=g.evaluate(kill_switch=False,strategy_active=True,confidence=.95,requested_risk_pct=.2,gross_exposure=10,drawdown=.2,market_data_fresh=True,quantity=10,regime_fit=.9,net_edge_bps=12,correlation_penalty=.1,strategy_health=10,health_state='QUARANTINED')
assert quarantined['approved'] is False
print('PHASE5_SMART_QUANT_SMOKE_OK')
