from __future__ import annotations
from statistics import mean


def forward_returns(prices:list[float], signal_indices:list[int], directions:list[int], horizons:list[int]|None=None)->dict:
    horizons=horizons or [1,2,5,10,20]
    out={h:[] for h in horizons}
    for idx,d in zip(signal_indices,directions):
        for h in horizons:
            if idx+h < len(prices) and prices[idx]>0:
                out[h].append(d*(prices[idx+h]/prices[idx]-1))
    means={h:(mean(v) if v else 0.0) for h,v in out.items()}
    return {'means':{str(h):round(v*10000,3) for h,v in means.items()},'samples':{str(h):len(out[h]) for h in horizons}}


def alpha_half_life(profile:dict)->dict:
    means={int(k):float(v) for k,v in profile.get('means',{}).items()}
    if not means:return {'halfLifeBars':None,'peakBps':0.0}
    hs=sorted(means); peak=max(abs(means[h]) for h in hs)
    if peak<=0:return {'halfLifeBars':None,'peakBps':0.0}
    half=peak/2
    half_h=None
    for h in hs:
        if abs(means[h])<=half:
            half_h=h;break
    return {'halfLifeBars':half_h,'peakBps':round(peak,3)}
