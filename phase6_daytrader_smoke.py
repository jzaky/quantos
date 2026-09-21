import os, sys, tempfile, importlib, math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'backend'))
from app.information_theory import predictability_features, entropy_rate, direction_series
from app.bayesian_edge import posterior_edge,bayesian_fractional_kelly
from app.change_detection import edge_decay_status
from app.statistical_validation import deflated_sharpe_ratio
from app.daytrade_strategies import run as run_day
from app.scout import opportunity_score
from app.backtest import backtest
from app.quant_research import validation_report

# Alternating sequence must demonstrate why marginal Shannon entropy alone is insufficient.
prices=[100 + (i%2)*1.0 for i in range(160)]
f=predictability_features(prices)
assert f['entropyRate'] < 0.8, f
assert f['predictability'] > 0.2, f

edge=posterior_edge(60,25,.006,.004,.0003,min_effective_samples=30)
assert edge.probability_above_breakeven > .95
kelly=bayesian_fractional_kelly(edge,1.5,.9,85,.5,.05)
assert 0 <= kelly['fractionalKelly'] <= .05

# Synthetic intraday trend with volume expansion.
bars=[]; p=100.0
for i in range(240):
    drift=.00065 if i>30 else .00015
    p*=1+drift + .0008*math.sin(i/6)
    bars.append({'ts':i*300,'open':p*.9998,'high':p*1.0015,'low':p*.9988,'close':p,'volume':100000+(i%30)*5000+(200000 if i>200 else 0)})
sc=opportunity_score('TEST',bars)
assert 'information' in sc and 0 <= sc['score'] <= 100
for sid in ('vwap-reclaim','opening-range','rvol-momentum'):
    sig=run_day(sid,'TEST',bars)
    assert sig.action in {'BUY','SELL','HOLD'}
    bt=backtest(sid,'TEST',bars)
    report=validation_report(bt,10,.8,75)
    assert 'bayesian' in report and 'deflatedSharpe' in report and 'kelly' in report
print('PHASE6_DAYTRADER_SMOKE_OK')
