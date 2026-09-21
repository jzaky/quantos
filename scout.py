from __future__ import annotations
from statistics import mean
from .information_theory import predictability_features
from .smart_quant import classify_regime, execution_cost_bps, clamp

DAY_UNIVERSE=['AAPL','MSFT','NVDA','AMD','META','AMZN','TSLA','GOOGL','NFLX','AVGO','PLTR','COIN','SPY','QQQ','IWM']

def opportunity_score(symbol:str,bars:list[dict])->dict:
    prices=[float(b['close']) for b in bars if b.get('close')]
    info=predictability_features(prices[-240:])
    rg=classify_regime(bars)
    vols=[float(b.get('volume') or 0) for b in bars[-30:]]
    rvol=(mean(vols[-3:])/max(mean(vols[:-3]),1)) if len(vols)>=10 else 1.0
    liquidity=clamp(rvol/2.0,.2,1.0)
    cost=execution_cost_bps(bars,fee_bps=0.5,spread_bps=1.5)
    cost_score=clamp(1-cost/25)
    regime_score={'TREND':.90,'RANGE':.68,'HIGH_VOL':.78,'CRISIS':.15}.get(rg['regime'],.5)
    score=100*clamp(.42*info['predictability']+.18*liquidity+.18*regime_score+.12*cost_score+.10*min(1,rg['trendStrength']))
    return {'symbol':symbol,'score':round(score,1),'information':info,'regime':rg,'relativeVolume':round(rvol,2),'estimatedCostBps':round(cost,2),'wakeExecutor':score>=52 and rg['regime']!='CRISIS'}

def scan(hub,universe:list[str]|None=None,period='5d',interval='5m')->list[dict]:
    rows=[]
    for sym in (universe or DAY_UNIVERSE):
        try: rows.append(opportunity_score(sym,hub.history(sym,period,interval)))
        except Exception as e: rows.append({'symbol':sym,'score':0,'error':str(e),'wakeExecutor':False})
    return sorted(rows,key=lambda x:x.get('score',0),reverse=True)
