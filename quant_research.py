from __future__ import annotations
import math
from statistics import mean
from .bayesian_edge import posterior_edge,bayesian_fractional_kelly
from .change_detection import edge_decay_status
from .statistical_validation import deflated_sharpe_ratio, bootstrap_probability_positive
from .alpha_analysis import forward_returns,alpha_half_life
from .memory_decay import adaptive_half_life
from .crowding import crowding_score
from .risk_simulator import monte_carlo_risk

def trade_returns_from_backtest(bt:dict)->list[float]:
    curve=bt.get('equityCurve') or []
    return [curve[i]/curve[i-1]-1 for i in range(1,len(curve)) if curve[i-1]]

def validation_report(bt:dict,trials:int=25,regime_fit:float=.7,health:float=60)->dict:
    rs=trade_returns_from_backtest(bt)
    wins=[r for r in rs if r>0]; losses=[-r for r in rs if r<0]
    avgw=mean(wins) if wins else .001; avgl=mean(losses) if losses else .001
    edge=posterior_edge(len(wins),len(losses),avgw,avgl,costs=.0002,min_effective_samples=30)
    payout=avgw/max(avgl,1e-9)
    kelly=bayesian_fractional_kelly(edge,payout,regime_fit,health,.5,.05)
    dsr=deflated_sharpe_ratio(float(bt.get('metrics',{}).get('sharpe',0)),rs,trials)
    decay=edge_decay_status(rs)
    memory_hl=adaptive_half_life(rs)
    crowd=crowding_score(rs)
    mc=monte_carlo_risk(rs,600)
    eligible=bool(edge.trusted and dsr['dsr']>=.8 and decay['status'] not in {'BROKEN','DECAYING'} and crowd['state']!='CROWDED' and mc['prob20PctDrawdown']<.20)
    return {'bayesian':edge.as_dict(),'kelly':kelly,'deflatedSharpe':dsr,'bootstrapPositiveProbability':round(bootstrap_probability_positive(rs),4),'edgeDecay':decay,'adaptiveMemoryHalfLife':memory_hl,'crowding':crowd,'monteCarloRisk':mc,'eligible':eligible}
