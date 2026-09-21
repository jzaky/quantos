from __future__ import annotations

def monte_carlo_risk(trade_returns:list[float],paths:int=1200,trades_per_path:int|None=None)->dict:
    if len(trade_returns)<8:return {'paths':0,'medianReturnPct':0,'p95MaxDrawdownPct':0,'prob10PctDrawdown':0,'prob20PctDrawdown':0,'probNegative':.5}
    n=trades_per_path or min(250,max(40,len(trade_returns))); state=0xC0FFEE
    finals=[]; dds=[]
    for _ in range(paths):
        eq=peak=1.0; mdd=0.0
        for __ in range(n):
            state=(1103515245*state+12345)&0x7fffffff
            r=trade_returns[state%len(trade_returns)]
            eq*=1+r; peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
        finals.append(eq-1); dds.append(mdd)
    finals.sort(); dds.sort()
    q=lambda xs,p: xs[min(len(xs)-1,max(0,int(p*(len(xs)-1))))]
    return {'paths':paths,'tradesPerPath':n,'medianReturnPct':round(q(finals,.5)*100,2),'p05ReturnPct':round(q(finals,.05)*100,2),'p95MaxDrawdownPct':round(q(dds,.95)*100,2),'prob10PctDrawdown':round(sum(x>=.10 for x in dds)/paths,4),'prob20PctDrawdown':round(sum(x>=.20 for x in dds)/paths,4),'probNegative':round(sum(x<0 for x in finals)/paths,4)}
