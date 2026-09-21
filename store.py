from __future__ import annotations
import json, sqlite3, threading, time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'quant_os.db'
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, symbol TEXT NOT NULL,
 side TEXT NOT NULL, qty REAL NOT NULL, fill_price REAL, strategy_id TEXT NOT NULL,
 status TEXT NOT NULL, confidence REAL NOT NULL, risk_pct REAL NOT NULL,
 reason TEXT DEFAULT '', shadow_price REAL, slippage_bps REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS positions (
 symbol TEXT NOT NULL, strategy_id TEXT NOT NULL, qty REAL NOT NULL,
 avg_price REAL NOT NULL, realized_pnl REAL NOT NULL DEFAULT 0,
 updated_at REAL NOT NULL, PRIMARY KEY(symbol, strategy_id)
);
CREATE TABLE IF NOT EXISTS equity (
 ts REAL PRIMARY KEY, equity REAL NOT NULL, cash REAL NOT NULL,
 unrealized REAL NOT NULL, realized REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, type TEXT NOT NULL,
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, strategy_id TEXT NOT NULL,
 symbol TEXT NOT NULL, signal REAL NOT NULL, confidence REAL NOT NULL,
 price REAL NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL
);
'''

def connect():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _lock:
        c=connect(); c.executescript(SCHEMA); c.commit(); c.close()

def event(kind: str, payload: dict[str, Any]):
    with _lock:
        c=connect(); c.execute('INSERT INTO events(ts,type,payload) VALUES(?,?,?)',(time.time(),kind,json.dumps(payload,separators=(',',':')))); c.commit(); c.close()

def list_events(limit=100):
    c=connect(); rows=c.execute('SELECT * FROM events ORDER BY id DESC LIMIT ?',(limit,)).fetchall(); c.close()
    return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows]

def add_order(**o):
    keys=['ts','symbol','side','qty','fill_price','strategy_id','status','confidence','risk_pct','reason','shadow_price','slippage_bps']
    vals=[o.get(k) for k in keys]
    with _lock:
        c=connect(); cur=c.execute(f"INSERT INTO orders({','.join(keys)}) VALUES({','.join('?' for _ in keys)})",vals); c.commit(); oid=cur.lastrowid; c.close(); return oid

def list_orders(limit=100):
    c=connect(); rows=c.execute('SELECT * FROM orders ORDER BY id DESC LIMIT ?',(limit,)).fetchall(); c.close(); return [dict(r) for r in rows]

def get_positions():
    c=connect(); rows=c.execute('SELECT * FROM positions ORDER BY symbol,strategy_id').fetchall(); c.close(); return [dict(r) for r in rows]

def upsert_position(symbol:str,strategy_id:str,delta_qty:float,price:float):
    with _lock:
        c=connect(); row=c.execute('SELECT * FROM positions WHERE symbol=? AND strategy_id=?',(symbol,strategy_id)).fetchone()
        realized=0.0
        if row is None:
            new_qty=delta_qty; avg=price
        else:
            old_qty=float(row['qty']); old_avg=float(row['avg_price']); prev_realized=float(row['realized_pnl'])
            if old_qty == 0 or (old_qty>0)==(delta_qty>0):
                new_qty=old_qty+delta_qty
                avg=(abs(old_qty)*old_avg+abs(delta_qty)*price)/max(abs(new_qty),1e-12)
                realized=prev_realized
            else:
                close_qty=min(abs(old_qty),abs(delta_qty))
                realized=prev_realized + close_qty*(price-old_avg)*(1 if old_qty>0 else -1)
                new_qty=old_qty+delta_qty
                avg=price if new_qty and (old_qty>0)!=(new_qty>0) else old_avg
        if abs(new_qty)<1e-12:
            c.execute('DELETE FROM positions WHERE symbol=? AND strategy_id=?',(symbol,strategy_id))
        else:
            c.execute('INSERT INTO positions(symbol,strategy_id,qty,avg_price,realized_pnl,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(symbol,strategy_id) DO UPDATE SET qty=excluded.qty,avg_price=excluded.avg_price,realized_pnl=excluded.realized_pnl,updated_at=excluded.updated_at',(symbol,strategy_id,new_qty,avg,realized,time.time()))
        c.commit(); c.close()
    return {'symbol':symbol,'strategy_id':strategy_id,'qty':new_qty,'avg_price':avg,'realized_pnl':realized}

def save_equity(equity,cash,unrealized,realized):
    with _lock:
        c=connect(); c.execute('INSERT OR REPLACE INTO equity(ts,equity,cash,unrealized,realized) VALUES(?,?,?,?,?)',(time.time(),equity,cash,unrealized,realized)); c.commit(); c.close()

def equity_history(limit=500):
    c=connect(); rows=c.execute('SELECT * FROM equity ORDER BY ts DESC LIMIT ?',(limit,)).fetchall(); c.close(); return [dict(r) for r in reversed(rows)]

def add_strategy_run(strategy_id,symbol,signal,confidence,price,action,detail):
    with _lock:
        c=connect(); c.execute('INSERT INTO strategy_runs(ts,strategy_id,symbol,signal,confidence,price,action,detail) VALUES(?,?,?,?,?,?,?,?)',(time.time(),strategy_id,symbol,signal,confidence,price,action,json.dumps(detail,separators=(',',':')))); c.commit(); c.close()

def strategy_runs(limit=100):
    c=connect(); rows=c.execute('SELECT * FROM strategy_runs ORDER BY id DESC LIMIT ?',(limit,)).fetchall(); c.close();
    out=[]
    for r in rows:
        d=dict(r); d['detail']=json.loads(d['detail']); out.append(d)
    return out

def save_portfolio_state(cash:float, starting_equity:float, peak_equity:float):
    payload=json.dumps({'cash':cash,'startingEquity':starting_equity,'peakEquity':peak_equity},separators=(',',':'))
    with _lock:
        c=connect(); c.execute('CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)'); c.execute('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('portfolio',payload)); c.commit(); c.close()

def load_portfolio_state():
    c=connect(); c.execute('CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)'); row=c.execute('SELECT value FROM app_state WHERE key=?',('portfolio',)).fetchone(); c.close()
    return json.loads(row['value']) if row else None
