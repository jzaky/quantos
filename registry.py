from __future__ import annotations
from .base import BrokerAdapter
from .alpaca import AlpacaPaperAdapter
from .mock import MockPaperAdapter

_REGISTRY: dict[str, type[BrokerAdapter]] = {}

def register(adapter_cls: type[BrokerAdapter]):
    _REGISTRY[adapter_cls.slug] = adapter_cls
    return adapter_cls

def available():
    return [{'slug':k,'label':v.label,'paper_only':v.paper_only} for k,v in sorted(_REGISTRY.items())]

def create(slug: str, credentials: dict[str,str], config: dict | None=None) -> BrokerAdapter:
    cls=_REGISTRY.get(slug)
    if not cls: raise KeyError(f'Unknown broker adapter: {slug}')
    return cls(credentials,config or {})

register(AlpacaPaperAdapter)
register(MockPaperAdapter)
