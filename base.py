from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Literal

OrderSide = Literal['buy','sell']
OrderType = Literal['market','limit','stop','stop_limit']
TimeInForce = Literal['day','gtc','ioc','fok','opg','cls']

@dataclass
class BrokerAccount:
    broker: str
    account_id: str
    status: str
    currency: str
    equity: float
    cash: float
    buying_power: float
    paper: bool

@dataclass
class BrokerOrder:
    broker: str
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    status: str
    filled_quantity: float = 0.0
    filled_avg_price: float | None = None
    submitted_at: str | None = None
    raw: dict[str, Any] | None = None

@dataclass
class BrokerPosition:
    broker: str
    symbol: str
    quantity: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float
    side: str

@dataclass
class SubmitOrder:
    symbol: str
    quantity: float
    side: OrderSide
    order_type: OrderType = 'market'
    time_in_force: TimeInForce = 'day'
    limit_price: float | None = None
    stop_price: float | None = None
    client_order_id: str | None = None

class BrokerAdapter:
    slug = 'base'
    label = 'Base Broker'
    paper_only = True

    def __init__(self, credentials: dict[str, str], config: dict[str, Any] | None = None):
        self.credentials = credentials
        self.config = config or {}

    def account(self) -> BrokerAccount:
        raise NotImplementedError

    def submit_order(self, order: SubmitOrder) -> BrokerOrder:
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str) -> bool:
        raise NotImplementedError

    def get_order(self, broker_order_id: str) -> BrokerOrder:
        raise NotImplementedError

    def list_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError

    def close_position(self, symbol: str) -> BrokerOrder | None:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        acct = self.account()
        return {'ok': acct.status.upper() == 'ACTIVE', 'broker': self.slug, 'paper': acct.paper, 'account': asdict(acct)}
