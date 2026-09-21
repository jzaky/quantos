from __future__ import annotations

from dataclasses import asdict
import hashlib
import hmac
import json
import os
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import tenant_store, tracking
from .brokers import available, create, SubmitOrder
from .secrets import secret_store

router=APIRouter(prefix='/api/v1',tags=['SaaS / Broker Platform'])


class WorkspaceCreate(BaseModel):
    name:str=Field(min_length=2,max_length=80)
    plan:str=Field(default='developer',pattern='^(developer|starter|pro|agency|enterprise)$')


class ApiKeyCreate(BaseModel):
    name:str=Field(default='dashboard',min_length=2,max_length=80)
    role:str=Field(default='admin',pattern='^(admin|trader|read_only)$')
    expires_in_days:int|None=Field(default=None,ge=1,le=365)


class ConnectionCreate(BaseModel):
    adapter_slug:str
    name:str=Field(min_length=2,max_length=80)
    secret_ref:str=Field(min_length=3,max_length=80,pattern='^[A-Za-z0-9_]+$')
    config:dict=Field(default_factory=dict)
    execution_enabled:bool=False


class ExecutionToggle(BaseModel):
    enabled:bool
    confirmation:str=''


class AutomationConfig(BaseModel):
    connection_id:str
    enabled:bool=False
    strategies:list[dict]=Field(default_factory=list)
    min_confidence:float=Field(default=.78,ge=.60,le=.99)
    max_order_notional:float=Field(default=1000,gt=0,le=100000)
    requested_risk_pct:float=Field(default=.20,gt=0,le=.50)
    cooldown_seconds:int=Field(default=1800,ge=60,le=86400)


class RoutedOrder(BaseModel):
    connection_id:str
    symbol:str=Field(min_length=1,max_length=24,pattern='^[A-Za-z0-9._/-]+$')
    side:str
    quantity:float=Field(gt=0,le=1_000_000)
    order_type:str=Field(default='market',pattern='^(market|limit|stop|stop_limit)$')
    time_in_force:str=Field(default='day',pattern='^(day|gtc|ioc|fok)$')
    limit_price:float|None=Field(default=None,gt=0)
    stop_price:float|None=Field(default=None,gt=0)
    strategy_id:str|None=None


def current_workspace(x_qos_api_key:str=Header(default='',alias='X-QOS-API-Key')):
    ws=tenant_store.authenticate(x_qos_api_key)
    if not ws: raise HTTPException(401,'Invalid, expired, or missing workspace API key')
    return ws


def require_role(*roles:str):
    def dep(ws=Depends(current_workspace)):
        if ws.get('api_key_role','admin') not in roles:
            raise HTTPException(403,'API key role does not permit this action')
        return ws
    return dep


def adapter_for(ws:dict,connection_id:str):
    conn=tenant_store.get_connection(ws['id'],connection_id)
    if not conn or not conn['enabled']: raise HTTPException(404,'Broker connection not found or disabled')
    try: creds=secret_store.get(conn['secret_ref'])
    except Exception as e: raise HTTPException(424,f'Broker credentials unavailable: {e}')
    try: return conn,create(conn['adapter_slug'],creds,conn['config'])
    except Exception as e: raise HTTPException(400,str(e))


def audit(ws:dict,kind:str,payload:dict):
    tenant_store.event(ws['id'],kind,{**payload,'actor_key_prefix':ws.get('api_key_prefix'),'actor_role':ws.get('api_key_role')})


@router.get('/platform')
def platform_info():
    return {
        'product':'Quant OS','architecture':'multi-tenant broker plugin platform',
        'real_money_enabled':False,'adapters':available(),'secret_model':'external-reference',
        'api_version':'v1','release':'0.6.0','order_idempotency':True,'api_key_roles':True,
    }


@router.post('/workspaces/bootstrap')
def bootstrap(body:WorkspaceCreate,x_qos_bootstrap_token:str=Header(default='',alias='X-QOS-Bootstrap-Token')):
    expected=os.getenv('QOS_BOOTSTRAP_TOKEN','').strip()
    if not expected: raise HTTPException(503,'Workspace bootstrap is disabled until QOS_BOOTSTRAP_TOKEN is configured')
    if not hmac.compare_digest(x_qos_bootstrap_token,expected): raise HTTPException(401,'Invalid bootstrap token')
    ws,key=tenant_store.create_workspace(body.name,body.plan)
    tenant_store.migrate_production_schema()
    return {'workspace':ws,'api_key':key,'warning':'API key is shown once. Store it in a secret manager.'}


@router.get('/me')
def me(ws=Depends(current_workspace)):
    return {k:v for k,v in ws.items() if k not in {'api_key_id'}} | {'api_key_id':ws.get('api_key_id')}


@router.get('/api-keys')
def api_keys(ws=Depends(require_role('admin'))):
    return tenant_store.list_api_keys(ws['id'])


@router.post('/api-keys')
def create_api_key(body:ApiKeyCreate,ws=Depends(require_role('admin'))):
    expires=time.time()+body.expires_in_days*86400 if body.expires_in_days else None
    meta,key=tenant_store.issue_api_key(ws['id'],body.name,body.role,expires)
    return {'api_key':key,'metadata':meta,'warning':'This secret is shown once.'}


@router.delete('/api-keys/{key_id}')
def revoke_api_key(key_id:str,ws=Depends(require_role('admin'))):
    if key_id==ws.get('api_key_id'):
        raise HTTPException(409,'Create a replacement key before revoking the key used by this request')
    if not tenant_store.revoke_api_key(ws['id'],key_id): raise HTTPException(404,'API key not found')
    return {'revoked':True,'key_id':key_id}


@router.get('/audit-events')
def audit_events(limit:int=100,ws=Depends(current_workspace)):
    return tenant_store.list_events(ws['id'],limit)


@router.get('/readiness')
def tenant_readiness(ws=Depends(current_workspace)):
    conns=tenant_store.list_connections(ws['id']); automation=tenant_store.get_automation(ws['id'])
    return {
        'workspace_id':ws['id'],'database':tenant_store.database_status(),'broker_connections':len(conns),
        'paper_execution_armed':sum(1 for c in conns if c['execution_enabled']),
        'automation_enabled':bool(automation and automation.get('enabled')),
        'real_money_enabled':False,
    }


@router.get('/broker-adapters')
def broker_adapters(ws=Depends(current_workspace)): return available()


@router.get('/broker-connections')
def connections(ws=Depends(current_workspace)): return tenant_store.list_connections(ws['id'])


@router.post('/broker-connections')
def add_connection(body:ConnectionCreate,ws=Depends(require_role('admin','trader'))):
    if body.adapter_slug not in {x['slug'] for x in available()}: raise HTTPException(400,'Unknown broker adapter')
    if body.execution_enabled and body.adapter_slug not in {'mock_paper','alpaca_paper'}: raise HTTPException(400,'Only approved paper adapters can execute')
    conn=tenant_store.create_connection(ws['id'],body.adapter_slug,body.name,body.secret_ref.upper(),body.config,False)
    audit(ws,'broker_connection_created',{'connection_id':conn['id'],'adapter':body.adapter_slug})
    return conn


@router.post('/broker-connections/{connection_id}/execution')
def execution_toggle(connection_id:str,body:ExecutionToggle,ws=Depends(require_role('admin','trader'))):
    conn=tenant_store.get_connection(ws['id'],connection_id)
    if not conn: raise HTTPException(404,'Connection not found')
    if not conn['adapter_slug'].endswith('_paper'): raise HTTPException(409,'Live-money adapters are disabled in this build')
    if body.enabled and body.confirmation!='ARM PAPER': raise HTTPException(409,'Set confirmation to ARM PAPER to enable execution')
    out=tenant_store.set_execution(ws['id'],connection_id,body.enabled)
    audit(ws,'execution_toggle',{'connection_id':connection_id,'enabled':body.enabled})
    return out


@router.get('/broker-connections/{connection_id}/health')
def broker_health(connection_id:str,ws=Depends(current_workspace)):
    conn,adapter=adapter_for(ws,connection_id)
    try: return {'connection_id':conn['id'],**adapter.health()}
    except Exception as e: raise HTTPException(502,str(e))


@router.post('/broker-connections/{connection_id}/reconcile')
def reconcile(connection_id:str,ws=Depends(require_role('admin','trader'))):
    conn,adapter=adapter_for(ws,connection_id)
    try:
        positions=[asdict(p) for p in adapter.list_positions()]
        tenant_store.replace_positions(ws['id'],connection_id,positions)
        acct=asdict(adapter.account())
        audit(ws,'broker_reconcile',{'connection_id':connection_id,'positions':len(positions),'equity':acct['equity']})
        return {'account':acct,'positions':positions}
    except Exception as e: raise HTTPException(502,str(e))


@router.get('/positions')
def positions(ws=Depends(current_workspace)): return tenant_store.list_positions(ws['id'])


@router.get('/orders')
def orders(limit:int=100,ws=Depends(current_workspace)): return tenant_store.list_orders(ws['id'],min(max(limit,1),1000))


@router.post('/orders')
def submit(body:RoutedOrder,request:Request,x_qos_idempotency_key:str=Header(default='',alias='X-QOS-Idempotency-Key'),ws=Depends(require_role('admin','trader'))):
    if not x_qos_idempotency_key or len(x_qos_idempotency_key)>120:
        raise HTTPException(400,'X-QOS-Idempotency-Key is required for order submission')
    request_hash=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    prior=tenant_store.get_idempotent(ws['id'],x_qos_idempotency_key)
    if prior:
        if prior['request_hash']!=request_hash: raise HTTPException(409,'Idempotency key was already used with a different order')
        return prior['response'] | {'idempotent_replay':True}

    conn,adapter=adapter_for(ws,body.connection_id)
    if not conn['execution_enabled']: raise HTTPException(409,'Execution is disabled for this broker connection')
    if not adapter.paper_only: raise HTTPException(409,'Real-money execution is disabled in this build')
    side=body.side.lower()
    if side not in ('buy','sell'): raise HTTPException(400,'side must be buy or sell')
    if body.order_type in {'limit','stop_limit'} and not body.limit_price: raise HTTPException(400,'limit_price is required')
    if body.order_type in {'stop','stop_limit'} and not body.stop_price: raise HTTPException(400,'stop_price is required')

    client_order_id='qos-'+uuid.uuid4().hex[:24]
    try:
        order=adapter.submit_order(SubmitOrder(symbol=body.symbol.upper(),quantity=body.quantity,side=side,order_type=body.order_type,time_in_force=body.time_in_force,limit_price=body.limit_price,stop_price=body.stop_price,client_order_id=client_order_id))
        data=asdict(order)
        oid=tenant_store.save_order(ws['id'],conn['id'],data,body.strategy_id)
        response={'local_order_id':oid,'order':data,'paper':True,'request_id':getattr(request.state,'request_id',None)}
        tenant_store.save_idempotent(ws['id'],x_qos_idempotency_key,request_hash,response,200)
        audit(ws,'broker_order_submitted',{'local_order_id':oid,'broker_order_id':order.broker_order_id,'connection_id':conn['id'],'symbol':order.symbol,'side':order.side,'quantity':order.quantity})
        return response
    except HTTPException: raise
    except Exception as e: raise HTTPException(502,str(e))


@router.get('/tracking/scoreboard')
def tracking_scoreboard(ws=Depends(current_workspace)):
    return tracking.scoreboard(workspace_id=ws['id'])

@router.get('/tracking/decisions')
def tracking_decisions(limit:int=200,decision:str|None=None,ws=Depends(current_workspace)):
    return tracking.list_decisions(min(max(limit,1),2000),decision,workspace_id=ws['id'])

@router.get('/automation')
def automation_get(ws=Depends(current_workspace)):
    return tenant_store.get_automation(ws['id']) or {'enabled':False,'strategies':[]}


@router.put('/automation')
def automation_put(body:AutomationConfig,ws=Depends(require_role('admin','trader'))):
    conn=tenant_store.get_connection(ws['id'],body.connection_id)
    if not conn: raise HTTPException(404,'Connection not found')
    if body.enabled and (not conn['execution_enabled'] or not conn['adapter_slug'].endswith('_paper')):
        raise HTTPException(409,'Automation requires an execution-enabled paper broker connection')
    strategies=body.strategies or [
      {'strategy_id':'vector-momentum','symbol':'NVDA'},
      {'strategy_id':'helix-reversion','symbol':'AAPL'},
      {'strategy_id':'london-vector','symbol':'ES'},
    ]
    out=tenant_store.save_automation(ws['id'],body.connection_id,body.enabled,strategies,body.min_confidence,body.max_order_notional,body.requested_risk_pct,body.cooldown_seconds)
    audit(ws,'automation_config_updated',{'enabled':body.enabled,'connection_id':body.connection_id,'strategies':strategies})
    return out
