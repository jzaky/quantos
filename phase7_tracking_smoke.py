import sys, tempfile, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'backend'))
from app import store, tracking

class Q:
    def __init__(self,p): self.price=p

with tempfile.TemporaryDirectory() as td:
    store.DB_PATH=Path(td)/'tracking.db'
    store.init_db(); tracking.init_tracking()
    a=tracking.record_decision(strategy_id='opening-range',symbol='NVDA',side='BUY',decision='TRADED',reference_price=100,
        confidence=.82,signal_score=.7,intelligence={'regime':'TREND','regime_fit':.9,'expected_edge_bps':20,'estimated_cost_bps':5,'net_edge_bps':15,'health':82,'healthState':'FULL'},horizon_seconds=1)
    b=tracking.record_decision(strategy_id='opening-range',symbol='AAPL',side='BUY',decision='BLOCKED_BY_COST',reference_price=100,
        confidence=.76,signal_score=.4,intelligence={'regime':'RANGE','regime_fit':.5,'expected_edge_bps':3,'estimated_cost_bps':6,'net_edge_bps':-3,'health':70,'healthState':'NORMAL'},horizon_seconds=1)
    c=store.connect(); c.execute('UPDATE forward_decisions SET settle_after=?',(time.time()-1,)); c.commit(); c.close()
    prices={'NVDA':101,'AAPL':99}
    result=tracking.settle_matured(lambda sym:Q(prices[sym]))
    assert result['settled']==2,result
    score=tracking.scoreboard()
    assert score['totalDecisions']==2,score
    assert score['accepted']['winRate']==100.0,score
    assert score['blockedLosers']==1,score
    assert score['filterPrecision']==100.0,score
print('PHASE7_TRACKING_SMOKE_OK')
