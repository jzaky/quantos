from __future__ import annotations
import math
from statistics import mean

def weights_by_age(ages_days:list[float],half_life_days:float)->list[float]:
    hl=max(half_life_days,1e-6); lam=math.log(2)/hl
    return [math.exp(-lam*max(0,a)) for a in ages_days]

def weighted_mean(values:list[float],weights:list[float])->float:
    if not values:return 0.0
    s=sum(weights) or 1.0
    return sum(v*w for v,w in zip(values,weights))/s

def adaptive_half_life(trade_returns:list[float],min_days:float=.25,max_days:float=30.0)->float:
    if len(trade_returns)<20:return 4.62
    m=mean(trade_returns); v=sum((x-m)**2 for x in trade_returns)
    if v<=0:return min_days
    ac=[]
    for lag in range(1,min(30,len(trade_returns)//3)+1):
        a=trade_returns[:-lag]; b=trade_returns[lag:]; ma=mean(a); mb=mean(b)
        den=(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))**.5
        rho=(sum((x-ma)*(y-mb) for x,y in zip(a,b))/den) if den else 0
        ac.append(abs(rho))
    crossing=next((i+1 for i,x in enumerate(ac) if x<.5),len(ac) or 1)
    return round(max(min_days,min(max_days,float(crossing))),3)
