from __future__ import annotations
import time, uuid
from .base import BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition, SubmitOrder

_STATE={}

class MockPaperAdapter(BrokerAdapter):
    slug='mock_paper'; label='Mock Paper'; paper_only=True
    def __init__(self, credentials: dict[str,str] | None=None, config=None):
        super().__init__(credentials or {'api_key':'mock','api_secret':'mock'},config)
        key=self.credentials.get('api_key','mock')
        self.state=_STATE.setdefault(key,{'orders':{},'positions':{},'cash':100000.0})
    def account(self):
        mv=sum(q*float(self.config.get('price',100.0)) for q in self.state['positions'].values()); eq=self.state['cash']+mv
        return BrokerAccount(self.slug,'mock-account','ACTIVE','USD',eq,self.state['cash'],max(eq*2,0),True)
    def submit_order(self,o:SubmitOrder):
        oid=str(uuid.uuid4()); price=float(self.config.get('price',100.0)); signed=o.quantity if o.side=='buy' else -o.quantity
        self.state['positions'][o.symbol.upper()]=self.state['positions'].get(o.symbol.upper(),0)+signed; self.state['cash']-=signed*price
        r=BrokerOrder(self.slug,oid,o.client_order_id or '',o.symbol.upper(),o.side,o.quantity,o.order_type,'filled',o.quantity,price,str(time.time()),{}); self.state['orders'][oid]=r; return r
    def cancel_order(self,broker_order_id): return broker_order_id in self.state['orders']
    def get_order(self,broker_order_id): return self.state['orders'][broker_order_id]
    def list_positions(self):
        price=float(self.config.get('price',100.0)); return [BrokerPosition(self.slug,s,q,price,q*price,0.0,'long' if q>=0 else 'short') for s,q in self.state['positions'].items() if abs(q)>1e-9]
    def close_position(self,symbol):
        q=self.state['positions'].get(symbol.upper(),0)
        if not q: return None
        return self.submit_order(SubmitOrder(symbol.upper(),abs(q),'sell' if q>0 else 'buy'))
