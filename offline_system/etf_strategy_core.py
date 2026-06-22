# coding=utf-8
from __future__ import absolute_import, print_function


FREQUENCY = "1d"
BENCHMARK_SYMBOL = "SHSE.510300"
LOOKBACK = 260
REBALANCE_INTERVAL = 1
MIN_WEIGHT_CHANGE = 0.035

MAX_INVESTED_WEIGHT = 0.98
MAX_SYMBOL_WEIGHT = 0.30
EX_ANTE_TARGET_VOL = 0.14
MIN_EXPOSURE_SCALE = 0.35
MAX_EXPOSURE_SCALE = 1.0
MOMENTUM_LOOKBACK = 60
TREND_MA = 60
VOL_LOOKBACK = 60
ENTRY_THRESHOLD = 0.01
MIN_AMOUNT = 10000000
MARKET_MA = 60
MARKET_MOM_FLOOR = 0.0
MAX_POSITIONS = 5
MAX_ENTRY_MA20_GAP = 0.05
MAX_ENTRY_MOM20 = 0.08
HOLD_MOM20_FLOOR = -0.025
HOLD_MOM60_FLOOR = 0.0

SYMBOL_INFO = {
    "SHSE.510300": ("CSI300", "cn_broad"),
    "SHSE.510500": ("CSI500", "cn_broad"),
    "SHSE.510050": ("SSE50", "cn_broad"),
    "SHSE.510880": ("Dividend", "cn_factor"),
    "SHSE.588000": ("STAR50", "cn_growth"),
    "SZSE.159915": ("ChiNext", "cn_growth"),
    "SHSE.512880": ("Brokerage", "sector"),
    "SHSE.515030": ("EV", "sector"),
    "SHSE.512170": ("Healthcare", "sector"),
    "SHSE.512800": ("Bank", "sector"),
    "SHSE.512400": ("Nonferrous", "sector"),
    "SHSE.515220": ("Coal", "sector"),
    "SHSE.510900": ("HShare", "hk"),
    "SZSE.159920": ("HangSeng", "hk"),
    "SHSE.513050": ("ChinaInternet", "hk"),
    "SHSE.513100": ("Nasdaq", "overseas"),
    "SHSE.513500": ("SP500", "overseas"),
    "SHSE.518880": ("Gold", "commodity"),
    "SHSE.511010": ("Treasury", "bond"),
    "SHSE.511260": ("TenYearTreasury", "bond"),
    "SHSE.512010": ("Pharma", "sector"),
    "SHSE.512200": ("RealEstate", "sector"),
    "SHSE.512480": ("Semiconductor", "sector"),
    "SHSE.512660": ("Military", "sector"),
    "SHSE.512690": ("Wine", "sector"),
    "SHSE.512980": ("Media", "sector"),
    "SHSE.515170": ("FoodDrink", "sector"),
    "SHSE.515650": ("Consumer50", "sector"),
    "SHSE.516160": ("NewEnergy", "sector"),
    "SHSE.516950": ("Infrastructure", "sector"),
    "SZSE.159928": ("Consumer", "sector"),
    "SZSE.159995": ("Chip", "sector"),
    "SZSE.159996": ("HomeAppliance", "sector"),
    "SZSE.159869": ("Game", "sector"),
}

SYMBOLS = list(SYMBOL_INFO.keys())
STRESS_PROXIES = ("SHSE.510300", "SZSE.159915", "SZSE.159920", "SHSE.513500")
GROUP_PROXY = {
    "cn_broad": "SHSE.510300",
    "cn_factor": "SHSE.510300",
    "cn_growth": "SZSE.159915",
    "sector": "SHSE.510300",
    "hk": "SZSE.159920",
    "overseas": "SHSE.513500",
}


def fnum(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values):
    return sum(values) / len(values) if values else None


def stdev(values):
    if len(values) < 2:
        return None
    avg = mean(values)
    return (sum((item - avg) ** 2 for item in values) / (len(values) - 1)) ** 0.5


def daily_returns(closes, lookback):
    if len(closes) < lookback + 1:
        return []
    tail = closes[-lookback - 1 :]
    return [tail[i] / tail[i - 1] - 1 for i in range(1, len(tail)) if tail[i - 1]]


def symbol_metrics(rows):
    closes = [fnum(row.get("close")) for row in rows]
    amounts = [fnum(row.get("amount")) for row in rows]
    if len(closes) < 60 or closes[-1] <= 0:
        return None

    close = closes[-1]
    avg_amount20 = mean(amounts[-20:]) or amounts[-1] or 1.0

    data = {
        "close": close,
        "high": fnum(rows[-1].get("high"), close),
        "low": fnum(rows[-1].get("low"), close),
        "amount": fnum(rows[-1].get("amount")),
        "ma20": mean(closes[-20:]),
        "ma60": mean(closes[-60:]),
        "ma120": mean(closes[-120:]) if len(closes) >= 120 else None,
        "mom10": close / closes[-10] - 1 if closes[-10] else 0.0,
        "mom20": close / closes[-20] - 1 if closes[-20] else 0.0,
        "mom60": close / closes[-60] - 1 if closes[-60] else 0.0,
        "high10": max(closes[-10:]),
        "high60": max(closes[-60:]),
        "vol20": (stdev(daily_returns(closes, 20)) or 0.0) * (252 ** 0.5),
        "vol60": (stdev(daily_returns(closes, 60)) or 0.0) * (252 ** 0.5),
        "amount_ratio20": amounts[-1] / avg_amount20,
    }
    data["pullback10"] = close / data["high10"] - 1 if data["high10"] else 0.0
    data["pullback60"] = close / data["high60"] - 1 if data["high60"] else 0.0
    return data


def market_gate_ok(symbol, metrics):
    group = SYMBOL_INFO[symbol][1]
    if group in ("bond", "commodity"):
        return True

    proxy = GROUP_PROXY.get(group)
    if not proxy:
        return True
    proxy_item = metrics.get(proxy)
    if not proxy_item:
        return False

    ma = proxy_item.get("ma{}".format(MARKET_MA))
    mom = proxy_item.get("mom20")
    if ma is None or mom is None:
        return False
    return proxy_item["close"] > ma and mom > MARKET_MOM_FLOOR


def raw_momentum_score(symbol, item, metrics):
    if not market_gate_ok(symbol, metrics):
        return None
    if item["amount"] < MIN_AMOUNT:
        return None

    mom = item.get("mom{}".format(MOMENTUM_LOOKBACK))
    ma = item.get("ma{}".format(TREND_MA))
    vol = item.get("vol{}".format(VOL_LOOKBACK))
    if mom is None or ma is None or vol is None:
        return None
    if item["close"] <= ma or mom <= ENTRY_THRESHOLD:
        return None
    return mom / max(vol, 0.04)


def passes_entry_guard(item):
    ma20 = item.get("ma20")
    mom20 = item.get("mom20")
    if ma20 is not None and ma20 > 0 and item["close"] / ma20 - 1 > MAX_ENTRY_MA20_GAP:
        return False
    if mom20 is not None and mom20 > MAX_ENTRY_MOM20:
        return False
    return True


def hold_ok(item):
    ma = item.get("ma{}".format(TREND_MA))
    mom20 = item.get("mom20")
    mom60 = item.get("mom60")
    if ma is None or mom20 is None or mom60 is None:
        return False
    if item["close"] <= ma:
        return False
    if mom20 <= HOLD_MOM20_FLOOR:
        return False
    if mom60 <= HOLD_MOM60_FLOOR:
        return False
    return True


def raw_allocation_weights(symbols, metrics, total_weight):
    if not symbols or total_weight <= 0:
        return {}

    raw = {}
    for symbol in symbols:
        item = metrics.get(symbol, {})
        raw[symbol] = 1.0 / max(fnum(item.get("vol60") or item.get("vol20")), 0.05)

    max_weight = max(MAX_SYMBOL_WEIGHT, total_weight / len(symbols))
    remaining = set(symbols)
    weights = {}
    remaining_weight = total_weight
    while remaining and remaining_weight > 0:
        total_raw = sum(raw[symbol] for symbol in remaining)
        if total_raw <= 0:
            for symbol in remaining:
                weights[symbol] = remaining_weight / len(remaining)
            break
        capped = []
        for symbol in list(remaining):
            weight = remaining_weight * raw[symbol] / total_raw
            if weight > max_weight:
                weights[symbol] = max_weight
                capped.append(symbol)
        if not capped:
            for symbol in remaining:
                weights[symbol] = remaining_weight * raw[symbol] / total_raw
            break
        for symbol in capped:
            remaining.remove(symbol)
            remaining_weight -= weights[symbol]
    return weights


def allocation_weights(symbols, metrics, total_weight):
    return raw_allocation_weights(symbols, metrics, total_weight)


def scale_by_ex_ante_vol(weights, metrics):
    if not weights:
        return weights, 0.0, 1.0
    estimated_vol = 0.0
    for symbol, weight in weights.items():
        item = metrics.get(symbol, {})
        estimated_vol += abs(weight) * fnum(item.get("vol60") or item.get("vol20"), 0.20)
    if estimated_vol <= 0:
        return weights, estimated_vol, 1.0
    scale = EX_ANTE_TARGET_VOL / estimated_vol
    scale = max(MIN_EXPOSURE_SCALE, min(MAX_EXPOSURE_SCALE, scale))
    if scale >= 0.999:
        return weights, estimated_vol, 1.0
    return {symbol: weight * scale for symbol, weight in weights.items()}, estimated_vol, scale


def calculate_targets(history_by_symbol, current_targets=None):
    current_targets = current_targets or {}
    metrics = {}
    for symbol, rows in history_by_symbol.items():
        item = symbol_metrics(rows)
        if item:
            metrics[symbol] = item

    scored = []
    for symbol in SYMBOLS:
        item = metrics.get(symbol)
        if not item:
            continue
        score = raw_momentum_score(symbol, item, metrics)
        if score is not None:
            item["score"] = score
            scored.append((score, symbol))
    scored.sort(reverse=True)

    selected = []
    used_groups = set()

    held = []
    for symbol, old_target in current_targets.items():
        if old_target < 0.005:
            continue
        item = metrics.get(symbol)
        if not item or not hold_ok(item):
            continue
        score = item.get("score")
        if score is not None:
            held.append((score, symbol))

    for _, symbol in sorted(held, reverse=True):
        group = SYMBOL_INFO[symbol][1]
        if group in used_groups:
            continue
        selected.append(symbol)
        used_groups.add(group)
        if len(selected) >= MAX_POSITIONS:
            break

    for _, symbol in scored:
        if symbol in selected:
            continue
        item = metrics.get(symbol)
        if current_targets.get(symbol, 0.0) < 0.005 and not passes_entry_guard(item):
            continue
        group = SYMBOL_INFO[symbol][1]
        if group in used_groups:
            continue
        selected.append(symbol)
        used_groups.add(group)
        if len(selected) >= MAX_POSITIONS:
            break

    targets = {symbol: 0.0 for symbol in SYMBOLS}
    selected_weights = allocation_weights(selected, metrics, MAX_INVESTED_WEIGHT)
    selected_weights, estimated_vol, exposure_scale = scale_by_ex_ante_vol(selected_weights, metrics)
    targets.update(selected_weights)

    diagnostics = {
        "risk_on": True,
        "selected": ",".join(selected),
        "gold_ok": targets.get("SHSE.518880", 0.0) > 0,
        "active_names": sum(1 for value in targets.values() if value >= 0.005),
        "stress_count": 0,
        "mode": "momentum_proxy_trend_strict",
        "estimated_vol": estimated_vol,
        "exposure_scale": exposure_scale,
        "top_scores": ";".join("{}:{:.4f}".format(symbol, score) for score, symbol in scored[:10]),
    }
    return targets, diagnostics, metrics


def signal_reason(old_target, target):
    if old_target < 0.005 and target >= 0.005:
        return "entry"
    if old_target >= 0.005 and target < 0.005:
        return "exit"
    if target > old_target:
        return "add"
    if target < old_target:
        return "trim"
    return "rebalance"


def should_rebalance(current_targets, next_targets):
    for symbol in set(current_targets) | set(next_targets):
        if abs(next_targets.get(symbol, 0.0) - current_targets.get(symbol, 0.0)) >= MIN_WEIGHT_CHANGE:
            return True
    return False
