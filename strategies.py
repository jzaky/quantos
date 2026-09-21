from __future__ import annotations
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Callable

@dataclass
class Signal:
    strategy_id:str; symbol:str; score:float; confidence:float; action:str; reason:str

def clamp(x,a=-1,b=1): return max(a,min(b,x))

def momentum(symbol,bars):
    c=[b['close'] for b in bars]
    if len(c)<25:return Signal('vector-momentum',symbol,0,0,'HOLD','insufficient data')
    fast=mean(c[-5:]); slow=mean(c[-20:]); raw=(fast/slow-1)*18
    score=clamp(raw); conf=min(.95,.55+abs(score)*.4); action='BUY' if score>.18 else 'SELL' if score<-.18 else 'HOLD'
    return Signal('vector-momentum',symbol,score,conf,action,f'5/20 momentum {raw:+.3f}')

def mean_reversion(symbol,bars):
    c=[b['close'] for b in bars]
    if len(c)<25:return Signal('helix-reversion',symbol,0,0,'HOLD','insufficient data')
    m=mean(c[-20:]); sd=pstdev(c[-20:]) or 1; z=(c[-1]-m)/sd; score=clamp(-z/2.5); conf=min(.93,.52+abs(score)*.42)
    action='BUY' if z<-1.2 else 'SELL' if z>1.2 else 'HOLD'
    return Signal('helix-reversion',symbol,score,conf,action,f'z-score {z:+.2f}')

def breakout(symbol,bars):
    if len(bars)<22:return Signal('london-vector',symbol,0,0,'HOLD','insufficient data')
    last=bars[-1]['close']; hi=max(b['high'] for b in bars[-21:-1]); lo=min(b['low'] for b in bars[-21:-1]); span=max(hi-lo,1e-9)
    score=clamp((last-(hi+lo)/2)/(span/2)); action='BUY' if last>hi else 'SELL' if last<lo else 'HOLD'; conf=.78 if action!='HOLD' else .55
    return Signal('london-vector',symbol,score,conf,action,f'20-bar channel {lo:.2f}-{hi:.2f}')

REGISTRY:dict[str,Callable]= {'vector-momentum':momentum,'helix-reversion':mean_reversion,'london-vector':breakout}
try:
    from .daytrade_strategies import REGISTRY as DAY_REGISTRY
    REGISTRY.update(DAY_REGISTRY)
except Exception:
    pass

def run(strategy_id,symbol,bars):
    fn=REGISTRY.get(strategy_id)
    return fn(symbol,bars) if fn else Signal(strategy_id,symbol,0,0,'HOLD','strategy is research-only')
