from __future__ import annotations
import math
from statistics import mean,pstdev
from .strategies import run

def _metrics(rets):
    if not rets:return {'returnPct':0,'sharpe':0,'sortino':0,'calmar':0,'maxDrawdownPct':0,'winRate':0,'profitFactor':0,'expectancyPct':0,'trades':0}
    eq=1; peak=1; mdd=0
    for r in rets:
        eq*=1+r; peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
    sd=pstdev(rets) if len(rets)>1 else 0; downside=[r for r in rets if r<0]; dsd=pstdev(downside) if len(downside)>1 else 0
    ann=mean(rets)*252
    sh=(mean(rets)/sd*math.sqrt(252)) if sd else 0
    sortino=(mean(rets)/dsd*math.sqrt(252)) if dsd else 0
    wins=[r for r in rets if r>0]; losses=[-r for r in rets if r<0]
    pf=(sum(wins)/sum(losses)) if losses and sum(losses)>0 else (9.99 if wins else 0)
    expectancy=mean(rets)*100
    calmar=ann/max(mdd,1e-9)
    return {'returnPct':round((eq-1)*100,2),'sharpe':round(sh,2),'sortino':round(sortino,2),'calmar':round(calmar,2),'maxDrawdownPct':round(mdd*100,2),'winRate':round(sum(r>0 for r in rets)/len(rets)*100,1),'profitFactor':round(min(pf,9.99),2),'expectancyPct':round(expectancy,4),'trades':len(rets)}

def backtest(strategy_id,symbol,bars,fee_bps=2.0):
    position=0; rets=[]; curve=[1.0]; trades=[]
    for i in range(25,len(bars)-1):
        sig=run(strategy_id,symbol,bars[:i+1]); new=1 if sig.action=='BUY' else -1 if sig.action=='SELL' else position
        if new!=position and sig.action!='HOLD': trades.append({'ts':bars[i]['ts'],'action':sig.action,'price':bars[i]['close'],'confidence':sig.confidence})
        nxt=bars[i+1]['close']/bars[i]['close']-1; cost=(fee_bps/10000) if new!=position else 0
        r=position*nxt-cost; rets.append(r); curve.append(curve[-1]*(1+r)); position=new
    return {'strategyId':strategy_id,'symbol':symbol,'metrics':_metrics(rets),'equityCurve':[round(x,6) for x in curve[-300:]],'trades':trades[-100:]}

def walk_forward(strategy_id,symbol,bars,windows=5):
    chunk=max(35,len(bars)//windows); out=[]
    for start in range(0,len(bars)-chunk+1,chunk):
        seg=bars[max(0,start-25):start+chunk]
        if len(seg)<35:continue
        r=backtest(strategy_id,symbol,seg); out.append({'start':seg[0]['ts'],'end':seg[-1]['ts'],**r['metrics']})
    passed=sum(1 for w in out if w['returnPct']>0 and w['maxDrawdownPct']<12 and w['profitFactor']>1)
    return {'windows':out,'passed':passed,'total':len(out),'passRate':round(passed/max(len(out),1)*100,1)}
