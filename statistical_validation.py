from __future__ import annotations
import math
from statistics import mean,pstdev


def _norm_cdf(x:float)->float:return .5*(1+math.erf(x/math.sqrt(2)))

def deflated_sharpe_ratio(observed_sharpe:float, returns:list[float], trials:int=1)->dict:
    n=len(returns)
    if n<8:return {'dsr':0.0,'expectedMaxSharpe':0.0,'overfitPenalty':1.0}
    mu=mean(returns); sd=pstdev(returns) or 1e-12
    centered=[(x-mu)/sd for x in returns]
    skew=mean([x**3 for x in centered]); kurt=mean([x**4 for x in centered])
    # Approx expected max SR under multiple testing (extreme-value approximation).
    t=max(1,int(trials)); expected=max(0.0, math.sqrt(2*math.log(max(t,2))) - (math.log(math.log(max(t,2)))+math.log(4*math.pi))/(2*math.sqrt(2*math.log(max(t,2))))) if t>1 else 0.0
    denom=math.sqrt(max(1e-12,(1-skew*observed_sharpe+(kurt-1)*(observed_sharpe**2)/4)/(n-1)))
    z=(observed_sharpe-expected)/denom
    dsr=_norm_cdf(z)
    return {'dsr':round(dsr,4),'expectedMaxSharpe':round(expected,3),'skew':round(skew,3),'kurtosis':round(kurt,3),'trials':t,'overfitPenalty':round(1-dsr,4)}


def benjamini_hochberg(pvalues:list[float],alpha:float=.05)->dict:
    m=len(pvalues)
    if not m:return {'discoveries':[],'threshold':0.0}
    ranked=sorted(enumerate(pvalues),key=lambda x:x[1]); cutoff=-1
    for rank,(idx,p) in enumerate(ranked,1):
        if p <= alpha*rank/m:cutoff=rank
    discoveries=[idx for rank,(idx,p) in enumerate(ranked,1) if cutoff>=0 and rank<=cutoff]
    threshold=(alpha*cutoff/m) if cutoff>0 else 0.0
    return {'discoveries':discoveries,'threshold':round(threshold,6),'tests':m}


def bootstrap_probability_positive(returns:list[float],samples:int=800)->float:
    if len(returns)<5:return 0.5
    # Deterministic LCG sampling keeps smoke tests stable without numpy.
    n=len(returns); state=2463534242; positive=0
    for _ in range(samples):
        total=0.0
        for _j in range(n):
            state=(1664525*state+1013904223)&0xffffffff
            total += returns[state % n]
        positive += total/n > 0
    return positive/samples
