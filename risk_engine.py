from __future__ import annotations
from dataclasses import dataclass

@dataclass
class Limits:
    max_order_risk_pct: float=.50
    max_gross_exposure_pct: float=75.0
    max_drawdown_pct: float=3.0
    min_confidence: float=.60
    max_symbol_exposure_pct: float=12.0
    min_regime_fit: float=.45
    min_net_edge_bps: float=3.0
    max_correlation_penalty: float=.35
    min_strategy_health: float=40.0

class RiskGovernor:
    def __init__(self,limits:Limits|None=None): self.limits=limits or Limits()
    def evaluate(self, *, kill_switch, strategy_active, confidence, requested_risk_pct, gross_exposure, drawdown, market_data_fresh, quantity, regime_fit=1.0, net_edge_bps=999.0, correlation_penalty=0.0, strategy_health=100.0, health_state='NORMAL'):
        checks={
          'kill_switch_clear':not kill_switch,'strategy_active':strategy_active,
          'confidence_floor':confidence>=self.limits.min_confidence,
          'risk_budget':requested_risk_pct<=self.limits.max_order_risk_pct,
          'gross_exposure':gross_exposure<self.limits.max_gross_exposure_pct,
          'drawdown_limit':drawdown<self.limits.max_drawdown_pct,
          'market_data_fresh':market_data_fresh,
          'regime_fit':regime_fit>=self.limits.min_regime_fit,
          'edge_after_costs':net_edge_bps>=self.limits.min_net_edge_bps,
          'correlation_limit':correlation_penalty<=self.limits.max_correlation_penalty,
          'strategy_health':strategy_health>=self.limits.min_strategy_health and health_state not in {'SHADOW_ONLY','QUARANTINED'},
        }
        if not all(checks.values()): return {'approved':False,'reason':'Blocked by: '+', '.join(k for k,v in checks.items() if not v),'resized_quantity':None,'policy_checks':checks}
        factor=1.0
        if gross_exposure>60: factor*=.70
        if confidence<.72: factor*=.75
        if regime_fit<.65: factor*=.70
        factor*=max(.50,1-correlation_penalty)
        if health_state=='REDUCED': factor*=.50
        return {'approved':True,'reason':'Smart risk envelope passed','resized_quantity':round(quantity*factor,8),'policy_checks':checks,'size_factor':round(factor,4)}
