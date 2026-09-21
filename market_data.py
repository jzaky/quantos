from __future__ import annotations
import json, math, random, time, urllib.parse, urllib.request
from dataclasses import dataclass
from typing import Iterable

@dataclass
class Quote:
    symbol: str
    price: float
    ts: float
    source: str
    stale: bool = False

class MarketDataHub:
    def __init__(self):
        self.cache: dict[str, Quote] = {}
        self.history_cache: dict[tuple[str,str], tuple[float,list[dict]]] = {}

    def _get_json(self,url:str,timeout=4):
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 QuantOS/0.2'})
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))

    def quote(self,symbol:str)->Quote:
        s=symbol.upper().strip()
        now=time.time()
        cached=self.cache.get(s)
        if cached and now-cached.ts<8: return cached
        try:
            if s in {'BTC','ETH','SOL'}:
                pair=s+'USDT'
                d=self._get_json('https://api.binance.com/api/v3/ticker/price?symbol='+pair)
                q=Quote(s,float(d['price']),now,'binance')
            else:
                y={'ES':'ES=F','CL':'CL=F','GC':'GC=F','NQ':'NQ=F'}.get(s,s)
                enc=urllib.parse.quote(y,safe='=')
                d=self._get_json(f'https://query1.finance.yahoo.com/v8/finance/chart/{enc}?interval=1m&range=1d')
                r=d['chart']['result'][0]
                price=float(r['meta'].get('regularMarketPrice') or r['indicators']['quote'][0]['close'][-1])
                q=Quote(s,price,now,'yahoo')
            self.cache[s]=q; return q
        except Exception:
            if cached: return Quote(s,cached.price,cached.ts,cached.source,True)
            seed=sum(map(ord,s)); rnd=random.Random(seed+int(now//60)); base={'ES':6850,'NQ':25000,'CL':66,'GC':3700,'BTC':115000,'ETH':4500,'NVDA':200,'AAPL':240,'MSFT':520}.get(s,100)
            q=Quote(s,base*(1+rnd.uniform(-.003,.003)),now,'synthetic-fallback',True); self.cache[s]=q; return q

    def history(self,symbol:str,period='3mo',interval='1d')->list[dict]:
        s=symbol.upper().strip(); key=(s,period+'|'+interval); now=time.time()
        if key in self.history_cache and now-self.history_cache[key][0]<600: return self.history_cache[key][1]
        try:
            y={'ES':'ES=F','CL':'CL=F','GC':'GC=F','NQ':'NQ=F','BTC':'BTC-USD','ETH':'ETH-USD'}.get(s,s)
            enc=urllib.parse.quote(y,safe='=-')
            d=self._get_json(f'https://query1.finance.yahoo.com/v8/finance/chart/{enc}?interval={interval}&range={period}',timeout=7)
            r=d['chart']['result'][0]; qs=r['indicators']['quote'][0]; ts=r['timestamp']
            out=[]
            for i,t in enumerate(ts):
                vals=[qs[k][i] if i<len(qs[k]) else None for k in ('open','high','low','close','volume')]
                if vals[3] is None: continue
                out.append({'ts':t,'open':vals[0] or vals[3],'high':vals[1] or vals[3],'low':vals[2] or vals[3],'close':vals[3],'volume':vals[4] or 0})
            if len(out)<20: raise ValueError('insufficient history')
            self.history_cache[key]=(now,out); return out
        except Exception:
            rnd=random.Random(sum(map(ord,s))); price=self.quote(s).price; out=[]; t=now-200*86400
            for i in range(200):
                ret=rnd.gauss(.00035,.015); o=price; c=max(.01,o*(1+ret)); hi=max(o,c)*(1+rnd.random()*.006); lo=min(o,c)*(1-rnd.random()*.006)
                out.append({'ts':t+i*86400,'open':o,'high':hi,'low':lo,'close':c,'volume':int(1e6*(.6+rnd.random()))}); price=c
            return out

    def quotes(self,symbols:Iterable[str])->dict[str,Quote]:
        return {s:self.quote(s) for s in symbols}
