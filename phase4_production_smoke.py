from __future__ import annotations
import os, sys, tempfile
from pathlib import Path
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.app import tenant_store, store
from backend.app.main import app, state

with tempfile.TemporaryDirectory() as td:
    tenant_store.DB_PATH=Path(td)/'saas.db'
    store.DB_PATH=Path(td)/'core.db'
    os.environ['QOS_BOOTSTRAP_TOKEN']='phase4-bootstrap'
    os.environ['QOS_SECRET_SMOKE_API_KEY']='phase4-broker-key'
    os.environ['QOS_SECRET_SMOKE_API_SECRET']='phase4-broker-secret'
    state['engineRunning']=False
    with TestClient(app) as c:
        h=c.get('/health'); assert h.status_code==200 and h.json()['phase']>=4
        assert c.get('/ready').status_code==200
        boot=c.post('/api/v1/workspaces/bootstrap',headers={'X-QOS-Bootstrap-Token':'phase4-bootstrap'},json={'name':'Production Smoke','plan':'developer'})
        assert boot.status_code==200,boot.text
        key=boot.json()['api_key']; headers={'X-QOS-API-Key':key}
        me=c.get('/api/v1/me',headers=headers); assert me.status_code==200 and me.json()['api_key_role']=='admin'
        created=c.post('/api/v1/api-keys',headers=headers,json={'name':'read-only smoke','role':'read_only','expires_in_days':30}); assert created.status_code==200
        assert created.json()['metadata']['role']=='read_only'
        conn=c.post('/api/v1/broker-connections',headers=headers,json={'adapter_slug':'mock_paper','name':'Mock Paper','secret_ref':'SMOKE','config':{'price':125.5}}); assert conn.status_code==200,conn.text
        cid=conn.json()['id']
        arm=c.post(f'/api/v1/broker-connections/{cid}/execution',headers=headers,json={'enabled':True,'confirmation':'ARM PAPER'}); assert arm.status_code==200,arm.text
        order={'connection_id':cid,'symbol':'AAPL','side':'buy','quantity':2,'order_type':'market','time_in_force':'day','strategy_id':'vector-momentum'}
        oh={**headers,'X-QOS-Idempotency-Key':'smoke-order-001'}
        first=c.post('/api/v1/orders',headers=oh,json=order); assert first.status_code==200,first.text
        replay=c.post('/api/v1/orders',headers=oh,json=order); assert replay.status_code==200 and replay.json()['idempotent_replay'] is True
        reconcile=c.post(f'/api/v1/broker-connections/{cid}/reconcile',headers=headers); assert reconcile.status_code==200,reconcile.text
        assert any(p['symbol']=='AAPL' for p in reconcile.json()['positions'])
        audit=c.get('/api/v1/audit-events?limit=20',headers=headers); assert audit.status_code==200 and len(audit.json())>=3
        ready=c.get('/api/v1/readiness',headers=headers); assert ready.status_code==200 and ready.json()['database']['ok'] is True
        print('PHASE4_PRODUCTION_SMOKE_OK')
