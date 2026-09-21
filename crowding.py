from __future__ import annotations
from statistics import mean

def crowding_score(recent_trade_returns:list[float],recent_slippage_bps:list[float]|None=None,alpha_half_life_bars:float|None=None)->dict:
    if len(recent_trade_returns)<20:return {'score':0.0,'state':'BOOTSTRAP','sizeMultiplier':1.0}
    n=max(5,len(recent_trade_returns)//4); old=recent_trade_returns[:-n] or recent_trade_returns[:n]; recent=recent_trade_returns[-n:]
    old_edge=mean(old); recent_edge=mean(recent)
    edge_decay=max(0.0,(old_edge-recent_edge)/max(abs(old_edge),1e-6)) if old_edge>0 else 0.0
    slip=mean(recent_slippage_bps or [0.0]); slip_pen=min(1.0,max(0.0,slip/12.0))
    speed_pen=0.0 if alpha_half_life_bars is None else max(0.0,min(1.0,(5-alpha_half_life_bars)/5))
    score=max(0.0,min(1.0,.60*edge_decay+.25*slip_pen+.15*speed_pen))
    state='CROWDED' if score>=.65 else 'WATCH' if score>=.35 else 'NORMAL'
    mult=.5 if state=='CROWDED' else .75 if state=='WATCH' else 1.0
    return {'score':round(score,3),'state':state,'sizeMultiplier':mult,'recentEdge':round(recent_edge,6),'priorEdge':round(old_edge,6),'meanSlippageBps':round(slip,2)}
