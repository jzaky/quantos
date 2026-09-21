from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from statistics import mean, pstdev


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def returns(bars: list[dict], lookback: int | None = None) -> list[float]:
    closes=[float(b['close']) for b in bars if b.get('close') not in (None,0)]
    if lookback: closes=closes[-(lookback+1):]
    return [closes[i]/closes[i-1]-1 for i in range(1,len(closes)) if closes[i-1]]


def atr_pct(bars: list[dict], n: int = 14) -> float:
    if len(bars)<2:return 0.0
    sample=bars[-(n+1):]
    trs=[]
    for i in range(1,len(sample)):
        h=float(sample[i]['high']); l=float(sample[i]['low']); pc=float(sample[i-1]['close'])
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    price=float(sample[-1]['close']) or 1.0
    return (mean(trs)/price) if trs else 0.0


def realized_vol(bars: list[dict], n: int = 20) -> float:
    r=returns(bars,n)
    return (pstdev(r)*math.sqrt(252)) if len(r)>1 else 0.0


def trend_strength(bars: list[dict], fast: int=10, slow: int=40) -> float:
    c=[float(b['close']) for b in bars]
    if len(c)<slow:return 0.0
    f=mean(c[-fast:]); s=mean(c[-slow:]); vol=max(realized_vol(bars,slow),1e-6)
    annualized_move=abs(f/s-1)*math.sqrt(252/max(fast,1))
    return clamp(annualized_move/vol,0,2)


def classify_regime(bars: list[dict]) -> dict:
    vol=realized_vol(bars,20); atr=atr_pct(bars,14); trend=trend_strength(bars)
    r=returns(bars,60)
    long_vol=(pstdev(r)*math.sqrt(252)) if len(r)>1 else vol
    vol_ratio=vol/max(long_vol,1e-6)
    if vol>0.55 or atr>0.045: regime='CRISIS'
    elif vol_ratio>1.35 or atr>0.025: regime='HIGH_VOL'
    elif trend>=0.80: regime='TREND'
    else: regime='RANGE'
    return {'regime':regime,'realizedVol':vol,'atrPct':atr,'trendStrength':trend,'volRatio':vol_ratio}


REGIME_FIT={
 'vector-momentum': {'TREND':.96,'HIGH_VOL':.72,'RANGE':.38,'CRISIS':.24},
 'helix-reversion': {'TREND':.42,'HIGH_VOL':.48,'RANGE':.94,'CRISIS':.18},
 'london-vector': {'TREND':.90,'HIGH_VOL':.82,'RANGE':.35,'CRISIS':.30},
 'vwap-reclaim': {'TREND':.72,'HIGH_VOL':.62,'RANGE':.88,'CRISIS':.20},
 'opening-range': {'TREND':.94,'HIGH_VOL':.86,'RANGE':.40,'CRISIS':.24},
 'rvol-momentum': {'TREND':.95,'HIGH_VOL':.80,'RANGE':.36,'CRISIS':.22},
}


def regime_fit(strategy_id:str, regime:str)->float:
    return REGIME_FIT.get(strategy_id,{}).get(regime,.50)


def pearson(a:list[float],b:list[float])->float:
    n=min(len(a),len(b))
    if n<5:return 0.0
    a=a[-n:]; b=b[-n:]; ma=mean(a); mb=mean(b)
    va=sum((x-ma)**2 for x in a); vb=sum((y-mb)**2 for y in b)
    if va<=0 or vb<=0:return 0.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(va*vb)


def correlation_penalty(candidate_bars:list[dict], other_histories:list[list[dict]])->float:
    cr=returns(candidate_bars,60)
    cors=[abs(pearson(cr,returns(h,60))) for h in other_histories if h]
    if not cors:return 0.0
    # only penalize correlation above 0.45; max penalty 45%
    return clamp((max(cors)-.45)/.55,0,.45)


def execution_cost_bps(bars:list[dict], fee_bps:float=2.0, spread_bps:float=2.0)->float:
    vol=realized_vol(bars,20)
    atr=atr_pct(bars,14)
    slippage=max(1.0, vol*18 + atr*120)
    return fee_bps+spread_bps+slippage


def expected_edge_bps(signal_score:float, confidence:float, bars:list[dict], horizon_days:float=1.0)->float:
    # Conservative translation: signal strength gets only a fraction of current daily volatility as expected alpha.
    vol_daily=max(realized_vol(bars,20)/math.sqrt(252),.001)
    raw=abs(signal_score)*confidence*vol_daily*10000*.28*math.sqrt(max(horizon_days,.25))
    return max(0.0,raw)


def volatility_size_multiplier(bars:list[dict], target_daily_vol:float=.0125)->float:
    daily=max(realized_vol(bars,20)/math.sqrt(252),.0025)
    return clamp(target_daily_vol/daily,.25,1.50)


def health_score(metrics:dict, regime_fit_value:float, execution_quality:float=1.0)->float:
    sharpe=max(-1.0,min(3.0,float(metrics.get('sharpe',0))))
    sharpe_score=clamp((sharpe+1)/4)
    expectancy=float(metrics.get('expectancyPct',0))
    expectancy_score=clamp((expectancy+.20)/.80)
    dd=abs(float(metrics.get('maxDrawdownPct',0)))
    drawdown_score=clamp(1-dd/20)
    pf=float(metrics.get('profitFactor',1.0))
    pf_score=clamp((pf-.7)/1.3)
    score=100*(.25*sharpe_score+.20*expectancy_score+.15*regime_fit_value+.15*clamp(execution_quality)+.10*pf_score+.15*drawdown_score)
    return round(score,1)


def health_state(score:float)->str:
    if score>=80:return 'FULL'
    if score>=60:return 'NORMAL'
    if score>=40:return 'REDUCED'
    if score>=20:return 'SHADOW_ONLY'
    return 'QUARANTINED'


@dataclass
class TradeIntelligence:
    strategy_id:str
    symbol:str
    regime:str
    regime_fit:float
    realized_vol:float
    atr_pct:float
    trend_strength:float
    expected_edge_bps:float
    estimated_cost_bps:float
    net_edge_bps:float
    correlation_penalty:float
    volatility_size_multiplier:float
    composite_score:float
    approved:bool
    blockers:list[str]

    def as_dict(self): return asdict(self)


def evaluate_candidate(strategy_id:str,symbol:str,signal_score:float,confidence:float,bars:list[dict],other_histories:list[list[dict]]|None=None,min_net_edge_bps:float=3.0)->TradeIntelligence:
    rg=classify_regime(bars); fit=regime_fit(strategy_id,rg['regime'])
    costs=execution_cost_bps(bars); edge=expected_edge_bps(signal_score,confidence,bars)
    corr=correlation_penalty(bars,other_histories or [])
    net=edge-costs
    vol_mult=volatility_size_multiplier(bars)
    composite=clamp(.30*abs(signal_score)+.20*confidence+.20*fit+.15*clamp(net/20)+.15*(1-corr))
    blockers=[]
    if fit<.45:blockers.append('regime_mismatch')
    if net<min_net_edge_bps:blockers.append('edge_below_cost')
    if corr>.35:blockers.append('correlation_concentration')
    if rg['regime']=='CRISIS':blockers.append('crisis_regime')
    return TradeIntelligence(strategy_id,symbol,rg['regime'],round(fit,3),round(rg['realizedVol'],4),round(rg['atrPct'],4),round(rg['trendStrength'],3),round(edge,2),round(costs,2),round(net,2),round(corr,3),round(vol_mult,3),round(composite,3),not blockers,blockers)
