from __future__ import annotations
from statistics import mean, pstdev


def cusum_changes(values:list[float],threshold_sigma:float=4.0,drift_sigma:float=.25)->dict:
    if len(values)<20:return {'changed':False,'score':0.0,'index':None}
    base=values[:max(10,len(values)//3)]; mu=mean(base); sd=pstdev(base) or 1e-9
    pos=neg=0.0; best=0.0; idx=None
    k=drift_sigma*sd; h=threshold_sigma*sd
    for i,x in enumerate(values):
        pos=max(0,pos+(x-mu)-k); neg=min(0,neg+(x-mu)+k)
        score=max(pos,-neg)/h
        if score>best:best=score;idx=i
    return {'changed':best>=1.0,'score':round(best,3),'index':idx,'baselineMean':mu,'baselineStd':sd}


def page_hinkley(values:list[float],delta:float=.005,threshold:float=12.0)->dict:
    if len(values)<20:return {'changed':False,'score':0.0,'index':None}
    running=0.0; min_running=0.0; m=0.0; best=0.0; idx=None
    for i,x in enumerate(values,1):
        m += (x-m)/i
        running += x-m-delta
        min_running=min(min_running,running)
        score=running-min_running
        if score>best:best=score;idx=i-1
    return {'changed':best>threshold,'score':round(best,3),'index':idx}


def edge_decay_status(trade_returns:list[float])->dict:
    if len(trade_returns)<30:return {'status':'BOOTSTRAP','changed':False,'recentMean':0.0,'priorMean':0.0,'decayRatio':1.0}
    k=max(10,len(trade_returns)//4); prior=trade_returns[:-k]; recent=trade_returns[-k:]
    pm=mean(prior) if prior else 0.0; rm=mean(recent)
    ratio=rm/pm if abs(pm)>1e-12 else (1.0 if rm>=0 else -1.0)
    c=cusum_changes(trade_returns); status='STABLE'
    if c['changed'] and rm<pm:status='DECAYING'
    if pm>0 and rm<=0:status='BROKEN'
    return {'status':status,'changed':c['changed'],'recentMean':round(rm,6),'priorMean':round(pm,6),'decayRatio':round(ratio,3),'cusum':c}
