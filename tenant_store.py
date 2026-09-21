from __future__ import annotations
import hashlib, json, secrets, sqlite3, threading, time, uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'quant_os_saas.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock=threading.Lock()

SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS workspaces (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, plan TEXT NOT NULL DEFAULT 'developer',
 status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_api_keys (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
 key_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL, created_at REAL NOT NULL,
 revoked_at REAL, FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
);
CREATE TABLE IF NOT EXISTS broker_connections (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, adapter_slug TEXT NOT NULL,
 name TEXT NOT NULL, secret_ref TEXT NOT NULL, config_json TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, execution_enabled INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, updated_at REAL NOT NULL,
 FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
);
CREATE TABLE IF NOT EXISTS broker_orders (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, connection_id TEXT NOT NULL,
 broker_order_id TEXT, client_order_id TEXT NOT NULL, symbol TEXT NOT NULL,
 side TEXT NOT NULL, quantity REAL NOT NULL, order_type TEXT NOT NULL,
 status TEXT NOT NULL, filled_quantity REAL NOT NULL DEFAULT 0,
 filled_avg_price REAL, strategy_id TEXT, raw_json TEXT NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_positions (
 workspace_id TEXT NOT NULL, connection_id TEXT NOT NULL, symbol TEXT NOT NULL,
 quantity REAL NOT NULL, avg_entry_price REAL NOT NULL, market_value REAL NOT NULL,
 unrealized_pl REAL NOT NULL, side TEXT NOT NULL, updated_at REAL NOT NULL,
 PRIMARY KEY(workspace_id,connection_id,symbol)
);
CREATE TABLE IF NOT EXISTS tenant_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, ts REAL NOT NULL,
 type TEXT NOT NULL, payload TEXT NOT NULL
);
'''

def connect():
    c=sqlite3.connect(DB_PATH,check_same_thread=False,timeout=15); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=5000'); c.execute('PRAGMA journal_mode=WAL')
    return c

def init_db():
    with _lock:
        c=connect(); c.executescript(SCHEMA); c.commit(); c.close()

def _hash(k:str): return hashlib.sha256(k.encode()).hexdigest()

def create_workspace(name:str,plan:str='developer') -> tuple[dict[str,Any],str]:
    wid='ws_'+uuid.uuid4().hex[:20]; kid='key_'+uuid.uuid4().hex[:20]; raw='qos_'+secrets.token_urlsafe(30); now=time.time()
    with _lock:
        c=connect(); c.execute('INSERT INTO workspaces(id,name,plan,status,created_at) VALUES(?,?,?,?,?)',(wid,name,plan,'active',now)); c.execute('INSERT INTO workspace_api_keys(id,workspace_id,name,key_hash,prefix,created_at) VALUES(?,?,?,?,?,?)',(kid,wid,'bootstrap',_hash(raw),raw[:10],now)); c.commit(); c.close()
    return {'id':wid,'name':name,'plan':plan,'status':'active','created_at':now},raw

def authenticate(raw_key:str) -> dict[str,Any] | None:
    if not raw_key: return None
    migrate_production_schema()
    now=time.time(); c=connect(); row=c.execute('''SELECT w.*, k.id AS api_key_id, k.prefix AS api_key_prefix, k.role AS api_key_role FROM workspace_api_keys k JOIN workspaces w ON w.id=k.workspace_id WHERE k.key_hash=? AND k.revoked_at IS NULL AND (k.expires_at IS NULL OR k.expires_at>?) AND w.status='active' ''',(_hash(raw_key),now)).fetchone()
    if row: c.execute('UPDATE workspace_api_keys SET last_used_at=? WHERE id=?',(now,row['api_key_id'])); c.commit()
    c.close(); return dict(row) if row else None

def list_connections(workspace_id:str):
    c=connect(); rows=c.execute('SELECT * FROM broker_connections WHERE workspace_id=? ORDER BY created_at',(workspace_id,)).fetchall(); c.close();
    out=[]
    for r in rows:
        d=dict(r); d['config']=json.loads(d.pop('config_json')); d['enabled']=bool(d['enabled']); d['execution_enabled']=bool(d['execution_enabled']); out.append(d)
    return out

def get_connection(workspace_id:str,connection_id:str):
    c=connect(); r=c.execute('SELECT * FROM broker_connections WHERE workspace_id=? AND id=?',(workspace_id,connection_id)).fetchone(); c.close()
    if not r:return None
    d=dict(r); d['config']=json.loads(d.pop('config_json')); d['enabled']=bool(d['enabled']); d['execution_enabled']=bool(d['execution_enabled']); return d

def create_connection(workspace_id:str,adapter_slug:str,name:str,secret_ref:str,config:dict[str,Any],execution_enabled:bool=False):
    cid='brk_'+uuid.uuid4().hex[:20]; now=time.time()
    with _lock:
        c=connect(); c.execute('''INSERT INTO broker_connections(id,workspace_id,adapter_slug,name,secret_ref,config_json,enabled,execution_enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',(cid,workspace_id,adapter_slug,name,secret_ref,json.dumps(config,separators=(',',':')),1,int(execution_enabled),now,now)); c.commit(); c.close()
    return get_connection(workspace_id,cid)

def set_execution(workspace_id:str,connection_id:str,enabled:bool):
    with _lock:
        c=connect(); c.execute('UPDATE broker_connections SET execution_enabled=?,updated_at=? WHERE workspace_id=? AND id=?',(int(enabled),time.time(),workspace_id,connection_id)); c.commit(); c.close()
    return get_connection(workspace_id,connection_id)

def save_order(workspace_id:str,connection_id:str,order:dict[str,Any],strategy_id:str|None=None):
    now=time.time(); oid='ord_'+uuid.uuid4().hex[:20]
    with _lock:
        c=connect(); c.execute('''INSERT INTO broker_orders(id,workspace_id,connection_id,broker_order_id,client_order_id,symbol,side,quantity,order_type,status,filled_quantity,filled_avg_price,strategy_id,raw_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(oid,workspace_id,connection_id,order.get('broker_order_id'),order.get('client_order_id',''),order.get('symbol',''),order.get('side',''),float(order.get('quantity',0)),order.get('order_type',''),order.get('status',''),float(order.get('filled_quantity',0)),order.get('filled_avg_price'),strategy_id,json.dumps(order.get('raw') or {},separators=(',',':')),now,now)); c.commit(); c.close()
    return oid

def list_orders(workspace_id:str,limit:int=100):
    c=connect(); rows=c.execute('SELECT * FROM broker_orders WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?',(workspace_id,limit)).fetchall(); c.close(); return [dict(r) for r in rows]

def replace_positions(workspace_id:str,connection_id:str,positions:list[dict[str,Any]]):
    now=time.time()
    with _lock:
        c=connect(); c.execute('DELETE FROM broker_positions WHERE workspace_id=? AND connection_id=?',(workspace_id,connection_id))
        for p in positions:
            c.execute('''INSERT INTO broker_positions(workspace_id,connection_id,symbol,quantity,avg_entry_price,market_value,unrealized_pl,side,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''',(workspace_id,connection_id,p['symbol'],p['quantity'],p['avg_entry_price'],p['market_value'],p['unrealized_pl'],p['side'],now))
        c.commit(); c.close()

def list_positions(workspace_id:str):
    c=connect(); rows=c.execute('SELECT * FROM broker_positions WHERE workspace_id=? ORDER BY symbol',(workspace_id,)).fetchall(); c.close(); return [dict(r) for r in rows]

def event(workspace_id:str,kind:str,payload:dict[str,Any]):
    with _lock:
        c=connect(); c.execute('INSERT INTO tenant_events(workspace_id,ts,type,payload) VALUES(?,?,?,?)',(workspace_id,time.time(),kind,json.dumps(payload,separators=(',',':')))); c.commit(); c.close()

# --- SaaS automation configuration ---
def ensure_automation_schema():
    with _lock:
        c=connect(); c.executescript('''
        CREATE TABLE IF NOT EXISTS automation_configs (
          workspace_id TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 0, strategies_json TEXT NOT NULL,
          min_confidence REAL NOT NULL DEFAULT 0.78,
          max_order_notional REAL NOT NULL DEFAULT 1000,
          requested_risk_pct REAL NOT NULL DEFAULT 0.20,
          cooldown_seconds INTEGER NOT NULL DEFAULT 1800,
          updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS automation_state (
          workspace_id TEXT NOT NULL, strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
          last_trade_at REAL NOT NULL, PRIMARY KEY(workspace_id,strategy_id,symbol)
        );
        '''); c.commit(); c.close()

def save_automation(workspace_id:str, connection_id:str, enabled:bool, strategies:list[dict[str,Any]], min_confidence:float, max_order_notional:float, requested_risk_pct:float, cooldown_seconds:int):
    ensure_automation_schema(); now=time.time()
    with _lock:
        c=connect(); c.execute('''INSERT INTO automation_configs(workspace_id,connection_id,enabled,strategies_json,min_confidence,max_order_notional,requested_risk_pct,cooldown_seconds,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET connection_id=excluded.connection_id,enabled=excluded.enabled,strategies_json=excluded.strategies_json,min_confidence=excluded.min_confidence,max_order_notional=excluded.max_order_notional,requested_risk_pct=excluded.requested_risk_pct,cooldown_seconds=excluded.cooldown_seconds,updated_at=excluded.updated_at''',(workspace_id,connection_id,int(enabled),json.dumps(strategies,separators=(',',':')),min_confidence,max_order_notional,requested_risk_pct,cooldown_seconds,now)); c.commit(); c.close()
    return get_automation(workspace_id)

def get_automation(workspace_id:str):
    ensure_automation_schema(); c=connect(); r=c.execute('SELECT * FROM automation_configs WHERE workspace_id=?',(workspace_id,)).fetchone(); c.close()
    if not r:return None
    d=dict(r); d['enabled']=bool(d['enabled']); d['strategies']=json.loads(d.pop('strategies_json')); return d

def list_automations(enabled_only:bool=True):
    ensure_automation_schema(); c=connect(); sql='SELECT * FROM automation_configs' + (' WHERE enabled=1' if enabled_only else ''); rows=c.execute(sql).fetchall(); c.close(); out=[]
    for r in rows:
        d=dict(r); d['enabled']=bool(d['enabled']); d['strategies']=json.loads(d.pop('strategies_json')); out.append(d)
    return out

def last_automation_trade(workspace_id:str,strategy_id:str,symbol:str)->float:
    ensure_automation_schema(); c=connect(); r=c.execute('SELECT last_trade_at FROM automation_state WHERE workspace_id=? AND strategy_id=? AND symbol=?',(workspace_id,strategy_id,symbol)).fetchone(); c.close(); return float(r['last_trade_at']) if r else 0.0

def mark_automation_trade(workspace_id:str,strategy_id:str,symbol:str):
    ensure_automation_schema(); now=time.time()
    with _lock:
        c=connect(); c.execute('INSERT INTO automation_state(workspace_id,strategy_id,symbol,last_trade_at) VALUES(?,?,?,?) ON CONFLICT(workspace_id,strategy_id,symbol) DO UPDATE SET last_trade_at=excluded.last_trade_at',(workspace_id,strategy_id,symbol,now)); c.commit(); c.close()

# --- Production hardening extensions ---
def migrate_production_schema():
    """Idempotent schema upgrades for SaaS control-plane hardening."""
    with _lock:
        c=connect()
        c.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)')
        cols={r['name'] for r in c.execute('PRAGMA table_info(workspace_api_keys)').fetchall()}
        if 'last_used_at' not in cols:
            c.execute('ALTER TABLE workspace_api_keys ADD COLUMN last_used_at REAL')
        if 'expires_at' not in cols:
            c.execute('ALTER TABLE workspace_api_keys ADD COLUMN expires_at REAL')
        if 'role' not in cols:
            c.execute("ALTER TABLE workspace_api_keys ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        c.executescript('''
        CREATE TABLE IF NOT EXISTS idempotency_keys (
          workspace_id TEXT NOT NULL, idem_key TEXT NOT NULL, request_hash TEXT NOT NULL,
          response_json TEXT NOT NULL, status_code INTEGER NOT NULL, created_at REAL NOT NULL,
          PRIMARY KEY(workspace_id, idem_key)
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_events_ws_ts ON tenant_events(workspace_id, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_broker_orders_ws_created ON broker_orders(workspace_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_broker_connections_ws ON broker_connections(workspace_id);
        ''')
        c.execute('INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)',(4,time.time()))
        c.commit(); c.close()


def issue_api_key(workspace_id:str,name:str='api key',role:str='admin',expires_at:float|None=None):
    migrate_production_schema()
    kid='key_'+uuid.uuid4().hex[:20]; raw='qos_'+secrets.token_urlsafe(30); now=time.time()
    role=role if role in {'admin','trader','read_only'} else 'read_only'
    with _lock:
        c=connect(); c.execute('''INSERT INTO workspace_api_keys(id,workspace_id,name,key_hash,prefix,created_at,expires_at,role) VALUES(?,?,?,?,?,?,?,?)''',(kid,workspace_id,name[:80],_hash(raw),raw[:10],now,expires_at,role)); c.commit(); c.close()
    event(workspace_id,'api_key_created',{'key_id':kid,'name':name[:80],'prefix':raw[:10],'role':role})
    return {'id':kid,'name':name[:80],'prefix':raw[:10],'role':role,'created_at':now,'expires_at':expires_at},raw


def list_api_keys(workspace_id:str):
    migrate_production_schema(); c=connect(); rows=c.execute('''SELECT id,name,prefix,created_at,last_used_at,expires_at,role,revoked_at FROM workspace_api_keys WHERE workspace_id=? ORDER BY created_at DESC''',(workspace_id,)).fetchall(); c.close(); return [dict(r) for r in rows]


def revoke_api_key(workspace_id:str,key_id:str):
    migrate_production_schema(); now=time.time()
    with _lock:
        c=connect(); cur=c.execute('UPDATE workspace_api_keys SET revoked_at=? WHERE workspace_id=? AND id=? AND revoked_at IS NULL',(now,workspace_id,key_id)); c.commit(); c.close()
    if cur.rowcount: event(workspace_id,'api_key_revoked',{'key_id':key_id})
    return bool(cur.rowcount)


def list_events(workspace_id:str,limit:int=100):
    c=connect(); rows=c.execute('SELECT id,ts,type,payload FROM tenant_events WHERE workspace_id=? ORDER BY ts DESC LIMIT ?',(workspace_id,min(max(limit,1),500))).fetchall(); c.close()
    out=[]
    for r in rows:
        d=dict(r)
        try:d['payload']=json.loads(d['payload'])
        except Exception:pass
        out.append(d)
    return out


def get_idempotent(workspace_id:str,idem_key:str):
    migrate_production_schema(); c=connect(); r=c.execute('SELECT * FROM idempotency_keys WHERE workspace_id=? AND idem_key=?',(workspace_id,idem_key)).fetchone(); c.close()
    if not r:return None
    d=dict(r); d['response']=json.loads(d.pop('response_json')); return d


def save_idempotent(workspace_id:str,idem_key:str,request_hash:str,response:dict,status_code:int=200):
    migrate_production_schema()
    with _lock:
        c=connect(); c.execute('''INSERT OR IGNORE INTO idempotency_keys(workspace_id,idem_key,request_hash,response_json,status_code,created_at) VALUES(?,?,?,?,?,?)''',(workspace_id,idem_key,request_hash,json.dumps(response,separators=(',',':')),status_code,time.time())); c.commit(); c.close()


def database_status():
    try:
        c=connect(); v=c.execute('PRAGMA integrity_check').fetchone()[0]; c.close(); return {'ok':v=='ok','integrity':v}
    except Exception as e:
        return {'ok':False,'error':str(e)}
