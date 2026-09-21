from __future__ import annotations
import math
from collections import Counter, defaultdict
from itertools import permutations
from statistics import mean


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def direction_series(prices: list[float], deadband: float = 0.0) -> list[int]:
    out: list[int] = []
    for a, b in zip(prices, prices[1:]):
        d = b - a
        if abs(d) <= deadband:
            out.append(0)
        else:
            out.append(1 if d > 0 else -1)
    return out


def shannon_entropy(values: list[int | str], normalize: bool = True) -> float:
    if not values:
        return 0.0
    counts = Counter(values)
    n = len(values)
    h = -sum((c / n) * math.log2(c / n) for c in counts.values())
    if not normalize or len(counts) <= 1:
        return h
    return h / math.log2(len(counts))


def conditional_entropy(values: list[int | str], order: int = 1) -> float:
    """H(X_t | X_{t-order:t-1}), normalized to [0,1] for binary-ish symbols."""
    if len(values) <= order + 1:
        return 1.0
    contexts: dict[tuple, list] = defaultdict(list)
    for i in range(order, len(values)):
        contexts[tuple(values[i-order:i])].append(values[i])
    total = sum(len(v) for v in contexts.values())
    if not total:
        return 1.0
    h = sum((len(v) / total) * shannon_entropy(v, normalize=True) for v in contexts.values())
    return clamp(h)


def entropy_rate(values: list[int | str], max_order: int = 3) -> float:
    if len(values) < 12:
        return 1.0
    orders = range(1, min(max_order, max(1, len(values)//10)) + 1)
    estimates = [conditional_entropy(values, o) for o in orders]
    # Conservative: use the last estimate but shrink toward 1 when data is sparse.
    e = estimates[-1]
    support = min(1.0, len(values) / (40 * (2 ** list(orders)[-1])))
    return clamp(support * e + (1-support) * 1.0)


def mutual_information_lag(values: list[int | str], lag: int = 1) -> float:
    if lag <= 0 or len(values) < lag + 8:
        return 0.0
    x = values[:-lag]
    y = values[lag:]
    n = len(x)
    cx, cy, cxy = Counter(x), Counter(y), Counter(zip(x, y))
    mi = 0.0
    for (a, b), c in cxy.items():
        pxy = c / n
        px = cx[a] / n
        py = cy[b] / n
        if pxy > 0 and px > 0 and py > 0:
            mi += pxy * math.log2(pxy / (px * py))
    # Binary direction information is capped at ~1 bit. Normalize conservatively.
    return clamp(mi)


def permutation_entropy(prices: list[float], order: int = 3, delay: int = 1) -> float:
    if order < 2 or len(prices) < order * delay + 4:
        return 1.0
    patterns = []
    for i in range((order-1)*delay, len(prices)):
        window = [prices[i-j*delay] for j in reversed(range(order))]
        rank = tuple(sorted(range(order), key=lambda k: (window[k], k)))
        patterns.append(rank)
    if not patterns:
        return 1.0
    counts = Counter(patterns); n = len(patterns)
    h = -sum((c/n)*math.log(c/n) for c in counts.values())
    max_h = math.log(math.factorial(order))
    return clamp(h / max_h if max_h else 1.0)


def autocorrelation(xs: list[float], lag: int = 1) -> float:
    if lag <= 0 or len(xs) < lag + 6:
        return 0.0
    a, b = xs[:-lag], xs[lag:]
    ma, mb = mean(a), mean(b)
    va = sum((x-ma)**2 for x in a); vb = sum((y-mb)**2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x-ma)*(y-mb) for x,y in zip(a,b)) / math.sqrt(va*vb)


def variance_ratio(prices: list[float], q: int = 5) -> float:
    if len(prices) < q * 5 or q < 2:
        return 1.0
    rs = [math.log(prices[i] / prices[i-1]) for i in range(1, len(prices)) if prices[i] > 0 and prices[i-1] > 0]
    if len(rs) < q * 3:
        return 1.0
    mu = mean(rs)
    var1 = sum((r-mu)**2 for r in rs) / max(1, len(rs)-1)
    if var1 <= 0:
        return 1.0
    qrets = [sum(rs[i-q+1:i+1]) for i in range(q-1, len(rs))]
    muq = mean(qrets)
    varq = sum((r-muq)**2 for r in qrets) / max(1, len(qrets)-1)
    return varq / (q * var1)


def hurst_rs(prices: list[float], min_chunk: int = 8) -> float:
    """Lightweight R/S estimate; intended as a regime feature, not a standalone proof of memory."""
    if len(prices) < 48:
        return 0.5
    rs = [math.log(prices[i] / prices[i-1]) for i in range(1, len(prices)) if prices[i] > 0 and prices[i-1] > 0]
    sizes = sorted({min_chunk, min_chunk*2, min_chunk*4, min_chunk*8})
    pts = []
    for size in sizes:
        if size > len(rs)//2:
            continue
        vals = []
        for start in range(0, len(rs)-size+1, size):
            seg = rs[start:start+size]; m = mean(seg)
            dev=[]; acc=0.0
            for x in seg:
                acc += x-m; dev.append(acc)
            R = max(dev)-min(dev)
            S = math.sqrt(sum((x-m)**2 for x in seg)/max(1,len(seg)-1))
            if S > 0 and R > 0:
                vals.append(R/S)
        if vals:
            pts.append((math.log(size), math.log(mean(vals))))
    if len(pts) < 2:
        return 0.5
    mx=mean([p[0] for p in pts]); my=mean([p[1] for p in pts])
    den=sum((x-mx)**2 for x,_ in pts)
    if den <= 0:
        return 0.5
    slope=sum((x-mx)*(y-my) for x,y in pts)/den
    return clamp(slope, 0.0, 1.0)


def predictability_features(prices: list[float]) -> dict:
    dirs = direction_series(prices)
    logrets = [math.log(prices[i]/prices[i-1]) for i in range(1,len(prices)) if prices[i] > 0 and prices[i-1] > 0]
    h = shannon_entropy(dirs)
    er = entropy_rate(dirs, 3)
    pe = permutation_entropy(prices, 3)
    mi1 = mutual_information_lag(dirs, 1)
    mi2 = mutual_information_lag(dirs, 2)
    ac1 = autocorrelation(logrets, 1)
    vr5 = variance_ratio(prices, 5)
    hurst = hurst_rs(prices)
    # Predictability grows with lower entropy rate, mutual information and departure from pure random-walk diagnostics.
    structure = clamp(0.34*(1-er) + 0.16*(1-pe) + 0.20*max(mi1,mi2) + 0.12*min(1,abs(ac1)*4) + 0.10*min(1,abs(vr5-1)) + 0.08*min(1,abs(hurst-.5)*4))
    return {
        'shannonEntropy': round(h,4), 'conditionalEntropy': round(conditional_entropy(dirs,1),4),
        'entropyRate': round(er,4), 'permutationEntropy': round(pe,4),
        'mutualInformationLag1': round(mi1,4), 'mutualInformationLag2': round(mi2,4),
        'autocorrelationLag1': round(ac1,4), 'varianceRatio5': round(vr5,4),
        'hurst': round(hurst,4), 'predictability': round(structure,4),
    }
