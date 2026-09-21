from __future__ import annotations
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from .base import BrokerAdapter, BrokerAccount, BrokerOrder, BrokerPosition, SubmitOrder

class AlpacaPaperAdapter(BrokerAdapter):
    slug = 'alpaca_paper'
    label = 'Alpaca Paper'
    paper_only = True

    def __init__(self, credentials: dict[str, str], config: dict[str, Any] | None = None):
        super().__init__(credentials, config)
        self.base_url = (self.config.get('base_url') or 'https://paper-api.alpaca.markets').rstrip('/')
        if self.base_url != 'https://paper-api.alpaca.markets':
            raise ValueError('AlpacaPaperAdapter is locked to the official paper endpoint')
        self.timeout = float(self.config.get('timeout', 8))

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = self.base_url + path
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header('APCA-API-KEY-ID', self.credentials['api_key'])
        req.add_header('APCA-API-SECRET-KEY', self.credentials['api_secret'])
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')
            raise RuntimeError(f'Alpaca HTTP {e.code}: {detail[:500]}') from e
        except urllib.error.URLError as e:
            raise RuntimeError(f'Alpaca connection failed: {e.reason}') from e

    @staticmethod
    def _f(value: Any, default: float = 0.0) -> float:
        try: return float(value)
        except (TypeError, ValueError): return default

    def account(self) -> BrokerAccount:
        d = self._request('GET', '/v2/account')
        return BrokerAccount(self.slug, str(d.get('id','')), str(d.get('status','')), str(d.get('currency','USD')), self._f(d.get('equity')), self._f(d.get('cash')), self._f(d.get('buying_power')), True)

    def submit_order(self, order: SubmitOrder) -> BrokerOrder:
        payload: dict[str, Any] = {
            'symbol': order.symbol.upper(), 'qty': str(order.quantity), 'side': order.side,
            'type': order.order_type, 'time_in_force': order.time_in_force,
        }
        if order.limit_price is not None: payload['limit_price'] = str(order.limit_price)
        if order.stop_price is not None: payload['stop_price'] = str(order.stop_price)
        if order.client_order_id: payload['client_order_id'] = order.client_order_id
        d = self._request('POST', '/v2/orders', payload)
        return self._normalize_order(d)

    def _normalize_order(self, d: dict[str, Any]) -> BrokerOrder:
        return BrokerOrder(
            self.slug, str(d.get('id','')), str(d.get('client_order_id','')), str(d.get('symbol','')),
            str(d.get('side','')), self._f(d.get('qty')), str(d.get('type','')), str(d.get('status','')),
            self._f(d.get('filled_qty')), self._f(d.get('filled_avg_price'), 0.0) or None,
            d.get('submitted_at'), d,
        )

    def cancel_order(self, broker_order_id: str) -> bool:
        self._request('DELETE', f'/v2/orders/{urllib.parse.quote(broker_order_id)}')
        return True

    def get_order(self, broker_order_id: str) -> BrokerOrder:
        d = self._request('GET', f'/v2/orders/{urllib.parse.quote(broker_order_id)}')
        return self._normalize_order(d)

    def list_positions(self) -> list[BrokerPosition]:
        rows = self._request('GET', '/v2/positions') or []
        return [BrokerPosition(self.slug, str(d.get('symbol','')), self._f(d.get('qty')), self._f(d.get('avg_entry_price')), self._f(d.get('market_value')), self._f(d.get('unrealized_pl')), str(d.get('side',''))) for d in rows]

    def close_position(self, symbol: str) -> BrokerOrder | None:
        d = self._request('DELETE', f'/v2/positions/{urllib.parse.quote(symbol.upper())}')
        return self._normalize_order(d) if d else None
