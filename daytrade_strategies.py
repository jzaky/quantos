from __future__ import annotations
from statistics import mean,pstdev
from .strategies import Signal


def _clamp(x,a=-1,b=1):return max(a,min(b,x))

def _vwap(bars):
    pv=v=0.0
    for b in bars:
        vol=max(float(b.get('volume') or 0),1.0); typ=(float(b['high'])+float(b['low'])+float(b['close']))/3
        pv+=typ*vol;v+=vol
    return pv/max(v,1)

def vwap_reclaim(symbol,bars):
    if len(bars)<35:return Signal('vwap-reclaim',symbol,0,0,'HOLD','insufficient intraday bars')
    recent=bars[-40:]; vw=_vwap(recent); close=float(recent[-1]['close']); prev=float(recent[-2]['close'])
    rets=[float(recent[i]['close'])/float(recent[i-1]['close'])-1 for i in range(1,len(recent))]
    vol=pstdev(rets) or .001; dist=(close/vw-1)/vol
    crossed_up=prev<vw<=close; crossed_down=prev>vw>=close
    score=_clamp(dist/2)
    action='BUY' if crossed_up and score>0 else 'SELL' if crossed_down and score<0 else 'HOLD'
    conf=min(.93,.58+abs(score)*.32)
    return Signal('vwap-reclaim',symbol,score,conf,action,f'VWAP {vw:.2f}, standardized distance {dist:+.2f}')

def opening_range_breakout(symbol,bars,opening_bars:int=15):
    if len(bars)<opening_bars+12:return Signal('opening-range',symbol,0,0,'HOLD','insufficient intraday bars')
    # Treat first N bars in supplied session as opening range.
    session=bars[-min(len(bars),390):]
    if len(session)<opening_bars+2:return Signal('opening-range',symbol,0,0,'HOLD','insufficient session bars')
    op=session[:opening_bars]; hi=max(float(b['high']) for b in op); lo=min(float(b['low']) for b in op); last=float(session[-1]['close'])
    width=max(hi-lo,1e-9); score=_clamp((last-(hi+lo)/2)/(width/2))
    action='BUY' if last>hi else 'SELL' if last<lo else 'HOLD'
    relvol=(float(session[-1].get('volume') or 0)+1)/(mean([float(x.get('volume') or 0)+1 for x in session[-20:]]) or 1)
    conf=min(.95,.60+min(1,abs(score))*.20+min(1,relvol/2)*.15)
    return Signal('opening-range',symbol,score,conf,action,f'ORB {lo:.2f}-{hi:.2f}, relvol {relvol:.2f}x')

def relative_volume_momentum(symbol,bars):
    if len(bars)<30:return Signal('rvol-momentum',symbol,0,0,'HOLD','insufficient intraday bars')
    c=[float(b['close']) for b in bars[-30:]]; vols=[float(b.get('volume') or 0)+1 for b in bars[-30:]]
    mom=c[-1]/c[-6]-1; rv=mean(vols[-3:])/max(mean(vols[:-3]),1)
    score=_clamp(mom/.01)*min(1.0,rv/2)
    action='BUY' if score>.28 and rv>1.2 else 'SELL' if score<-.28 and rv>1.2 else 'HOLD'
    conf=min(.95,.56+abs(score)*.28+min(.12,max(0,rv-1)*.08))
    return Signal('rvol-momentum',symbol,score,conf,action,f'5-bar momentum {mom*100:+.2f}%, RVOL {rv:.2f}x')

REGISTRY={'vwap-reclaim':vwap_reclaim,'opening-range':opening_range_breakout,'rvol-momentum':relative_volume_momentum}

def run(strategy_id,symbol,bars):
    fn=REGISTRY.get(strategy_id)
    return fn(symbol,bars) if fn else Signal(strategy_id,symbol,0,0,'HOLD','unknown day strategy')
