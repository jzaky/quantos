from __future__ import annotations
import os, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))

from app import tenant_store
from app.brokers import create, SubmitOrder
from app.saas_engine import cycle_workspace

with tempfile.TemporaryDirectory() as td:
    tenant_store.DB_PATH=Path(td)/'saas.db'
    tenant_store.init_db(); tenant_store.ensure_automation_schema()
    ws,key=tenant_store.create_workspace('Smoke Workspace')
    assert tenant_store.authenticate(key)['id']==ws['id']
    os.environ['QOS_SECRET_SMOKE_API_KEY']='smoke-key'
    os.environ['QOS_SECRET_SMOKE_API_SECRET']='smoke-secret'
    conn=tenant_store.create_connection(ws['id'],'mock_paper','Mock Broker','SMOKE',{'price':100},True)
    a=create('mock_paper',{'api_key':'smoke-key','api_secret':'smoke-secret'},{'price':100})
    assert a.health()['ok'] is True
    order=a.submit_order(SubmitOrder('AAPL',2,'buy',client_order_id='smoke-1'))
    assert order.status=='filled'
    tenant_store.replace_positions(ws['id'],conn['id'],[p.__dict__ for p in a.list_positions()])
    pos=tenant_store.list_positions(ws['id'])
    assert len(pos)==1 and pos[0]['symbol']=='AAPL' and pos[0]['quantity']==2
    cfg=tenant_store.save_automation(ws['id'],conn['id'],False,[{'strategy_id':'vector-momentum','symbol':'NVDA'}],.78,500,.20,1800)
    assert cfg['enabled'] is False
    print('PHASE3_SAAS_SMOKE_OK')
