from fastapi.testclient import TestClient
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app import store
from backend.app.main import app, hub, state
from backend.app.market_data import Quote

with tempfile.TemporaryDirectory() as td:
    store.DB_PATH = Path(td) / "smoke.db"
    state.update({
        "startingEquity":100000.0,"cash":100000.0,"equity":100000.0,
        "dayPnl":0.0,"drawdown":0.0,"peakEquity":100000.0,
        "grossExposure":0.0,"killSwitch":False,"engineRunning":False
    })
    orig_quote = hub.quote
    def fresh_quote(symbol):
        return Quote(symbol.upper(), {"NVDA":200.0,"BTC":115000.0}.get(symbol.upper(),100.0), time.time(), "smoke-fixture", False)
    hub.quote = fresh_quote
    try:
        with TestClient(app) as c:
            assert c.get('/health').json()['phase']>=2
            s=c.get('/api/snapshot'); assert s.status_code==200
            q=c.get('/api/market/quotes?symbols=NVDA,BTC'); assert q.status_code==200 and len(q.json())==2
            bt=c.post('/api/research/backtest',json={'strategy_id':'vector-momentum','symbol':'NVDA','period':'3mo','interval':'1d','fee_bps':2}); assert bt.status_code==200 and 'metrics' in bt.json()
            order={'symbol':'NVDA','side':'BUY','quantity':1,'strategy_id':'vector-momentum','confidence':.85,'requested_risk_pct':.2}
            r=c.post('/api/paper/orders/submit',json=order); assert r.status_code==200
            assert c.get('/api/orders').json()[0]['status']=='FILLED'
            snap=c.get('/api/snapshot').json()
            assert abs(snap['equity']-100000.0) < 1.0, snap
            assert c.post('/api/risk/kill-switch',json={'enabled':True}).status_code==200
            blocked=c.post('/api/paper/orders/submit',json=order); assert blocked.status_code==409
            c.post('/api/risk/kill-switch',json={'enabled':False})
    finally:
        hub.quote = orig_quote
print('PHASE2_SMOKE_OK')
