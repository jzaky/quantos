from __future__ import annotations
import math
from dataclasses import dataclass, asdict


def clamp(x, lo=0.0, hi=1.0): return max(lo,min(hi,x))


def _betacf(a: float, b: float, x: float) -> float:
    # Numerical Recipes continued fraction for incomplete beta.
    MAXIT=200; EPS=3e-12; FPMIN=1e-300
    qab=a+b; qap=a+1.0; qam=a-1.0
    c=1.0; d=1.0-qab*x/qap
    if abs(d)<FPMIN:d=FPMIN
    d=1.0/d; h=d
    for m in range(1,MAXIT+1):
        m2=2*m
        aa=m*(b-m)*x/((qam+m2)*(a+m2)); d=1.0+aa*d
        if abs(d)<FPMIN:d=FPMIN
        c=1.0+aa/c
        if abs(c)<FPMIN:c=FPMIN
        d=1.0/d; h*=d*c
        aa=-(a+m)*(qab+m)*x/((a+m2)*(qap+m2)); d=1.0+aa*d
        if abs(d)<FPMIN:d=FPMIN
        c=1.0+aa/c
        if abs(c)<FPMIN:c=FPMIN
        d=1.0/d; delta=d*c; h*=delta
        if abs(delta-1.0)<EPS:break
    return h


def beta_cdf(x: float, a: float, b: float) -> float:
    if x<=0:return 0.0
    if x>=1:return 1.0
    bt=math.exp(math.lgamma(a+b)-math.lgamma(a)-math.lgamma(b)+a*math.log(x)+b*math.log(1-x))
    if x < (a+1)/(a+b+2): return bt*_betacf(a,b,x)/a
    return 1-bt*_betacf(b,a,1-x)/b


def beta_ppf(p:float,a:float,b:float)->float:
    lo,hi=0.0,1.0
    for _ in range(70):
        mid=(lo+hi)/2
        if beta_cdf(mid,a,b)<p:lo=mid
        else:hi=mid
    return (lo+hi)/2


def breakeven_probability(avg_win:float, avg_loss:float, costs:float=0.0)->float:
    w=max(avg_win-costs,1e-12); l=max(avg_loss+costs,1e-12)
    return clamp(l/(w+l))

@dataclass
class BayesianEdge:
    alpha:float; beta:float; posterior_mean:float; ci_low:float; ci_high:float
    breakeven_probability:float; probability_above_breakeven:float
    sample_size:float; trusted:bool
    def as_dict(self):return asdict(self)


def posterior_edge(wins:float,losses:float,avg_win:float,avg_loss:float,costs:float=0.0,prior_alpha:float=1.0,prior_beta:float=1.0,min_effective_samples:float=30.0,confidence_threshold:float=.95)->BayesianEdge:
    a=prior_alpha+max(0,wins); b=prior_beta+max(0,losses)
    be=breakeven_probability(avg_win,avg_loss,costs)
    p=1-beta_cdf(be,a,b)
    n=max(0,wins)+max(0,losses)
    return BayesianEdge(a,b,a/(a+b),beta_ppf(.025,a,b),beta_ppf(.975,a,b),be,p,n,n>=min_effective_samples and p>=confidence_threshold)


def bayesian_fractional_kelly(edge:BayesianEdge,payout_ratio:float,regime_fit:float,health_score:float,fraction:float=.5,max_fraction:float=.10)->dict:
    b=max(payout_ratio,1e-9)
    # Use a conservative posterior quantile, not the posterior mean.
    p=edge.ci_low; q=1-p
    raw=max(0.0,(b*p-q)/b)
    confidence=clamp((edge.probability_above_breakeven-.5)/.5)
    adjusted=raw*clamp(regime_fit)*clamp(health_score/100)*confidence*fraction
    return {'rawKelly':round(raw,6),'confidenceMultiplier':round(confidence,4),'fractionalKelly':round(min(max_fraction,adjusted),6),'posteriorPUsed':round(p,4)}
