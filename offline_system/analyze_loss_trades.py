# coding=utf-8
from __future__ import absolute_import, print_function

import csv
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

from etf_strategy_core import fnum, mean, stdev


OUT_DIR = Path("backtest_output")

ETF_NAMES = {
    "SHSE.510880": "dividend",
    "SHSE.512800": "bank",
    "SHSE.512400": "nonferrous",
    "SHSE.513500": "sp500",
    "SHSE.518880": "gold",
    "SHSE.511010": "treasury",
    "SHSE.511260": "ten_year_treasury",
}


def read_csv(path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fields = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def parse_day(value):
    return str(value)[:10]


def days_between(start, end):
    return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days


def pct(value):
    return "{:.2%}".format(value)


def build_bars():
    rows = read_csv(OUT_DIR / "etf_bars.csv")
    by_symbol = defaultdict(list)
    for row in rows:
        item = {
            "date": row["date"],
            "symbol": row["symbol"],
            "open": fnum(row["open"]),
            "high": fnum(row["high"]),
            "low": fnum(row["low"]),
            "close": fnum(row["close"]),
            "volume": fnum(row.get("volume")),
            "amount": fnum(row.get("amount")),
        }
        by_symbol[item["symbol"]].append(item)
    for symbol in by_symbol:
        by_symbol[symbol].sort(key=lambda item: item["date"])
    return dict(by_symbol)


def daily_returns(closes, lookback):
    if len(closes) < lookback + 1:
        return []
    tail = closes[-lookback - 1 :]
    return [tail[index] / tail[index - 1] - 1 for index in range(1, len(tail)) if tail[index - 1]]


def enrich_bars(by_symbol):
    enriched = {}
    for symbol, rows in by_symbol.items():
        result = []
        closes = []
        for row in rows:
            closes.append(row["close"])
            idx = len(closes) - 1
            item = dict(row)
            if idx >= 199:
                ma20 = mean(closes[-20:])
                ma60 = mean(closes[-60:])
                ma120 = mean(closes[-120:])
                ma200 = mean(closes[-200:])
                high20 = max(closes[-20:])
                high60 = max(closes[-60:])
                low20 = min(closes[-20:])
                mom20 = closes[-1] / closes[-20] - 1 if closes[-20] else 0.0
                mom60 = closes[-1] / closes[-60] - 1 if closes[-60] else 0.0
                mom120 = closes[-1] / closes[-120] - 1 if closes[-120] else 0.0
                vol60 = (stdev(daily_returns(closes, 60)) or 0.0) * (252 ** 0.5)
                item.update(
                    {
                        "ma20": ma20,
                        "ma60": ma60,
                        "ma120": ma120,
                        "ma200": ma200,
                        "high20": high20,
                        "high60": high60,
                        "low20": low20,
                        "mom20": mom20,
                        "mom60": mom60,
                        "mom120": mom120,
                        "vol60": vol60,
                        "pullback20": closes[-1] / high20 - 1 if high20 else 0.0,
                        "pullback60": closes[-1] / high60 - 1 if high60 else 0.0,
                    }
                )
            result.append(item)
        enriched[symbol] = result
    return enriched


def index_bars(enriched):
    return {
        symbol: {row["date"]: idx for idx, row in enumerate(rows)}
        for symbol, rows in enriched.items()
    }


def signal_reason_by_order():
    signals = read_csv(OUT_DIR / "official_signals.csv")
    result = {}
    for row in signals:
        result[(parse_day(row.get("eob")), row.get("symbol"))] = row
    return result


def reconstruct_sells():
    executions = read_csv(OUT_DIR / "official_executions.csv")
    signals = signal_reason_by_order()
    lots = defaultdict(deque)
    sells = []
    for execution in executions:
        day = parse_day(execution.get("created_at"))
        symbol = execution["symbol"]
        side = str(execution.get("side"))
        qty = fnum(execution.get("volume"))
        price = fnum(execution.get("price"))
        amount = fnum(execution.get("amount"))
        commission = fnum(execution.get("commission"))
        signal = signals.get((day, symbol), {})
        if side == "1":
            lots[symbol].append(
                {
                    "date": day,
                    "qty": qty,
                    "cost": amount + commission,
                    "price": price,
                }
            )
            continue
        if side != "2":
            continue

        remain = qty
        cost_basis = 0.0
        entry_dates = []
        entry_value_sum = 0.0
        while remain > 1e-9 and lots[symbol]:
            lot = lots[symbol][0]
            take = min(remain, lot["qty"])
            old_qty = lot["qty"]
            old_cost = lot["cost"]
            cost_piece = old_cost * take / old_qty
            cost_basis += cost_piece
            entry_value_sum += lot["price"] * take
            entry_dates.append(lot["date"])
            lot["qty"] = old_qty - take
            lot["cost"] = old_cost * lot["qty"] / old_qty
            remain -= take
            if lot["qty"] <= 1e-9:
                lots[symbol].popleft()

        proceeds = amount - commission
        pnl = proceeds - cost_basis
        ret = pnl / cost_basis if cost_basis else 0.0
        avg_entry = entry_value_sum / qty if qty else 0.0
        sells.append(
            {
                "date": day,
                "symbol": symbol,
                "name": ETF_NAMES.get(symbol, symbol),
                "qty": qty,
                "avg_entry_price": avg_entry,
                "exit_price": price,
                "cost_basis": cost_basis,
                "proceeds": proceeds,
                "realized_pnl": pnl,
                "realized_return": ret,
                "entry_dates": ";".join(entry_dates),
                "first_entry_date": min(entry_dates) if entry_dates else "",
                "last_entry_date": max(entry_dates) if entry_dates else "",
                "reason": signal.get("reason", ""),
                "from_target": signal.get("from_target", ""),
                "to_target": signal.get("to_target", ""),
                "selected": signal.get("selected", ""),
            }
        )
    return sells


def first_risk_signal(rows, start_idx, end_idx):
    peak = None
    signal = None
    for idx in range(start_idx, end_idx + 1):
        row = rows[idx]
        close = row["close"]
        peak = close if peak is None else max(peak, close)
        if "ma120" not in row:
            continue
        draw_from_peak = close / peak - 1 if peak else 0.0
        checks = [
            ("trend_break", close < row["ma120"] and row["mom20"] < -0.02),
            ("momentum_crash", close < row["ma60"] and row["mom20"] < -0.05),
            ("deep_pullback", row["pullback60"] < -0.16),
            ("trailing_stop", draw_from_peak < -0.08 and close < row["ma20"]),
        ]
        for name, ok in checks:
            if ok:
                signal = {
                    "risk_signal_date": row["date"],
                    "risk_signal": name,
                    "risk_signal_close": close,
                    "risk_signal_drawdown_from_peak": draw_from_peak,
                }
                return signal
    return {}


def classify_loss(review):
    causes = []
    if review["entry_overheat"] == "1":
        causes.append("entry_chased_strength")
    if review["entry_weak_trend"] == "1":
        causes.append("entry_weak_trend")
    if fnum(review["mfe"]) > 0.08 and fnum(review["realized_return"]) < 0:
        causes.append("profit_not_protected")
    if review.get("risk_signal_before_exit") == "1":
        causes.append("exit_late_after_risk_signal")
    if fnum(review["mae"]) < -0.10 and fnum(review["mfe"]) < 0.03:
        causes.append("wrong_entry_then_drawdown")
    if fnum(review["hold_days"]) > 180 and fnum(review["realized_return"]) < -0.05:
        causes.append("long_hold_thesis_decay")
    if review["sold_near_holding_low"] == "1":
        causes.append("sold_near_low")
    if not causes:
        causes.append("normal_rebalance_loss")
    return "|".join(causes)


def recommendation(review):
    cause = review["loss_causes"]
    if "profit_not_protected" in cause:
        return "add trailing trim: after MFE > 8%, cut target when close falls > 6% from holding peak and below MA20"
    if "exit_late_after_risk_signal" in cause:
        return "add earlier risk exit: reduce target when close < MA120 and mom20 < -2%, or close < MA60 and mom20 < -5%"
    if "entry_chased_strength" in cause:
        return "add entry guard: do not add when close is > 5% above MA20 or 20-day momentum is already > 8%"
    if "entry_weak_trend" in cause:
        return "require trend confirmation: new/add weight only when close > MA120 and MA60 slope is positive"
    if "wrong_entry_then_drawdown" in cause:
        return "use smaller starter size and wait for second confirmation after pullback"
    if "long_hold_thesis_decay" in cause:
        return "add stale-position rule: if holding loses money after 120 trading days and score stays weak, cut further"
    return "treat as small rebalance loss; avoid overfitting unless repeated by symbol"


def review_losses():
    bars = enrich_bars(build_bars())
    bar_index = index_bars(bars)
    sells = reconstruct_sells()
    loss_reviews = []

    for sell in sells:
        if sell["realized_pnl"] >= 0:
            continue
        symbol = sell["symbol"]
        first_entry = sell["first_entry_date"]
        exit_date = sell["date"]
        if symbol not in bars or first_entry not in bar_index[symbol] or exit_date not in bar_index[symbol]:
            continue
        rows = bars[symbol]
        start_idx = bar_index[symbol][first_entry]
        end_idx = bar_index[symbol][exit_date]
        if start_idx > end_idx:
            continue
        hold_rows = rows[start_idx : end_idx + 1]
        closes = [row["close"] for row in hold_rows]
        min_row = min(hold_rows, key=lambda row: row["close"])
        max_row = max(hold_rows, key=lambda row: row["close"])
        avg_entry = sell["avg_entry_price"]
        exit_price = sell["exit_price"]
        mfe = max_row["close"] / avg_entry - 1 if avg_entry else 0.0
        mae = min_row["close"] / avg_entry - 1 if avg_entry else 0.0
        entry_row = rows[start_idx]
        exit_row = rows[end_idx]
        entry_overheat = (
            "ma20" in entry_row
            and (
                entry_row["close"] / entry_row["ma20"] - 1 > 0.05
                or entry_row["mom20"] > 0.08
            )
        )
        entry_weak_trend = (
            "ma120" in entry_row
            and (entry_row["close"] < entry_row["ma120"] or entry_row["mom60"] < 0)
        )
        signal = first_risk_signal(rows, start_idx, end_idx)
        risk_signal_date = signal.get("risk_signal_date", "")
        signal_before_exit = bool(risk_signal_date and risk_signal_date < exit_date)
        hold_days = days_between(first_entry, exit_date)
        review = {
            "sell_date": exit_date,
            "symbol": symbol,
            "name": sell["name"],
            "entry_dates": sell["entry_dates"],
            "first_entry_date": first_entry,
            "last_entry_date": sell["last_entry_date"],
            "hold_days": hold_days,
            "avg_entry_price": avg_entry,
            "exit_price": exit_price,
            "realized_pnl": sell["realized_pnl"],
            "realized_return": sell["realized_return"],
            "mae": mae,
            "mfe": mfe,
            "holding_low_date": min_row["date"],
            "holding_low_close": min_row["close"],
            "holding_high_date": max_row["date"],
            "holding_high_close": max_row["close"],
            "entry_gap_to_hindsight_low": avg_entry / min_row["close"] - 1 if min_row["close"] else 0.0,
            "exit_gap_to_hindsight_high": max_row["close"] / exit_price - 1 if exit_price else 0.0,
            "sold_near_holding_low": "1" if exit_price <= min_row["close"] * 1.03 else "0",
            "entry_overheat": "1" if entry_overheat else "0",
            "entry_weak_trend": "1" if entry_weak_trend else "0",
            "entry_close_vs_ma20": entry_row["close"] / entry_row["ma20"] - 1 if "ma20" in entry_row and entry_row["ma20"] else "",
            "entry_mom20": entry_row.get("mom20", ""),
            "entry_mom60": entry_row.get("mom60", ""),
            "entry_pullback60": entry_row.get("pullback60", ""),
            "exit_close_vs_ma120": exit_row["close"] / exit_row["ma120"] - 1 if "ma120" in exit_row and exit_row["ma120"] else "",
            "exit_mom20": exit_row.get("mom20", ""),
            "risk_signal_before_exit": "1" if signal_before_exit else "0",
            "days_from_risk_signal_to_exit": days_between(risk_signal_date, exit_date) if signal_before_exit else "",
            "risk_signal": signal.get("risk_signal", ""),
            "risk_signal_date": risk_signal_date,
            "risk_signal_close": signal.get("risk_signal_close", ""),
            "reason": sell["reason"],
        }
        review["loss_causes"] = classify_loss(review)
        review["strategy_fix_hint"] = recommendation(review)
        loss_reviews.append(review)

    summary = []
    by_cause = Counter()
    by_symbol = defaultdict(list)
    for row in loss_reviews:
        for cause in row["loss_causes"].split("|"):
            by_cause[cause] += 1
        by_symbol[row["symbol"]].append(row)
    for cause, count in by_cause.most_common():
        rows = [row for row in loss_reviews if cause in row["loss_causes"].split("|")]
        summary.append(
            {
                "type": "cause",
                "key": cause,
                "count": count,
                "gross_loss": sum(fnum(row["realized_pnl"]) for row in rows),
                "avg_return": mean([fnum(row["realized_return"]) for row in rows]),
                "avg_mae": mean([fnum(row["mae"]) for row in rows]),
                "avg_mfe": mean([fnum(row["mfe"]) for row in rows]),
            }
        )
    for symbol, rows in sorted(by_symbol.items()):
        summary.append(
            {
                "type": "symbol",
                "key": "{} {}".format(symbol, ETF_NAMES.get(symbol, "")),
                "count": len(rows),
                "gross_loss": sum(fnum(row["realized_pnl"]) for row in rows),
                "avg_return": mean([fnum(row["realized_return"]) for row in rows]),
                "avg_mae": mean([fnum(row["mae"]) for row in rows]),
                "avg_mfe": mean([fnum(row["mfe"]) for row in rows]),
            }
        )

    write_csv(OUT_DIR / "loss_trade_review.csv", loss_reviews)
    write_csv(OUT_DIR / "loss_trade_cause_summary.csv", summary)

    print("loss trades:", len(loss_reviews))
    print("gross loss:", round(sum(fnum(row["realized_pnl"]) for row in loss_reviews), 2))
    print("files:", OUT_DIR / "loss_trade_review.csv", OUT_DIR / "loss_trade_cause_summary.csv")
    for item in summary:
        if item["type"] == "cause":
            print(
                item["key"],
                "count=" + str(item["count"]),
                "gross_loss=" + str(round(item["gross_loss"], 2)),
                "avg_mfe=" + pct(item["avg_mfe"]),
                "avg_mae=" + pct(item["avg_mae"]),
            )


if __name__ == "__main__":
    review_losses()
