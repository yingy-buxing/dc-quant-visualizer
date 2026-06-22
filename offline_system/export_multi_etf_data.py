# coding=utf-8
from __future__ import absolute_import, print_function

import csv
import json
import os
from pathlib import Path

from gm.api import *

from etf_strategy_core import (
    BENCHMARK_SYMBOL,
    FREQUENCY,
    LOOKBACK,
    MIN_WEIGHT_CHANGE,
    REBALANCE_INTERVAL,
    SYMBOLS,
    calculate_targets,
    fnum,
    signal_reason,
    should_rebalance,
)


START_TIME = "2020-01-01 08:00:00"
END_TIME = "2025-12-31 16:00:00"
WARMUP_START_TIME = "2018-01-01 08:00:00"
INITIAL_CASH = 10000000.0
COMMISSION_RATIO = 0.0001
SLIPPAGE_RATIO = 0.0001


def gm_token():
    token = os.environ.get("GM_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Please set GM_TOKEN before running this script.")
    return token


def date_key(value):
    return str(value)[:10]


def pct(value):
    return "{:.2%}".format(value)


def fetch_symbol_bars(symbol, adjust=ADJUST_PREV):
    data = history(
        symbol=symbol,
        frequency=FREQUENCY,
        start_time=WARMUP_START_TIME,
        end_time=END_TIME,
        fields="eob,open,high,low,close,volume,amount",
        adjust=adjust,
        df=True,
    )
    if data is None or len(data) == 0:
        raise RuntimeError("no bars for {}".format(symbol))
    data = data.sort_values("eob").reset_index(drop=True)
    rows = []
    for _, row in data.iterrows():
        rows.append(
            {
                "date": date_key(row["eob"]),
                "symbol": symbol,
                "open": fnum(row["open"]),
                "high": fnum(row["high"]),
                "low": fnum(row["low"]),
                "close": fnum(row["close"]),
                "volume": fnum(row["volume"]),
                "amount": fnum(row["amount"]),
            }
        )
    return rows


def write_csv(path, rows, fields=None):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def history_until(rows, end_index):
    start = max(0, end_index - LOOKBACK + 1)
    return rows[start : end_index + 1]


def simulate(bars_by_symbol):
    benchmark_rows = bars_by_symbol[BENCHMARK_SYMBOL]
    index_by_symbol_date = {
        symbol: {row["date"]: index for index, row in enumerate(rows)}
        for symbol, rows in bars_by_symbol.items()
    }
    row_by_symbol_date = {
        symbol: {row["date"]: row for row in rows}
        for symbol, rows in bars_by_symbol.items()
    }

    cash = INITIAL_CASH
    shares = {symbol: 0.0 for symbol in SYMBOLS}
    current_targets = {symbol: 0.0 for symbol in SYMBOLS}
    last_close = {}
    equity_high = INITIAL_CASH
    rows = []
    trades = []
    report_day_count = 0

    for bench_index, bench_row in enumerate(benchmark_rows):
        day = bench_row["date"]
        if day < START_TIME[:10]:
            continue
        available = [symbol for symbol in SYMBOLS if day in row_by_symbol_date[symbol]]
        if BENCHMARK_SYMBOL not in available:
            continue

        close_map = {symbol: row_by_symbol_date[symbol][day]["close"] for symbol in available}
        last_close.update(close_map)
        equity_before = cash + sum(
            shares[symbol] * last_close.get(symbol, 0.0) for symbol in SYMBOLS
        )

        if report_day_count % REBALANCE_INTERVAL == 0:
            history_map = {}
            for symbol in available:
                idx = index_by_symbol_date[symbol][day]
                if idx + 1 >= 60:
                    history_map[symbol] = history_until(bars_by_symbol[symbol], idx)
            if len(history_map) >= 5:
                targets, diagnostics, metrics = calculate_targets(history_map, current_targets)
                if should_rebalance(current_targets, targets):
                    rebalance_symbols = sorted(
                        SYMBOLS,
                        key=lambda item: targets.get(item, 0.0) - current_targets.get(item, 0.0),
                    )
                    for symbol in rebalance_symbols:
                        target = targets.get(symbol, 0.0)
                        old_target = current_targets.get(symbol, 0.0)
                        close = close_map.get(symbol)
                        if close is None:
                            continue
                        current_value = shares[symbol] * close
                        actual_weight = current_value / equity_before if equity_before else 0.0
                        if abs(target - actual_weight) < MIN_WEIGHT_CHANGE:
                            continue
                        desired_value = equity_before * target
                        delta_value = desired_value - current_value
                        trade_price = close * (1 + SLIPPAGE_RATIO if delta_value > 0 else 1 - SLIPPAGE_RATIO)
                        delta_shares = delta_value / trade_price if trade_price else 0.0
                        commission = abs(delta_value) * COMMISSION_RATIO
                        cash -= delta_shares * trade_price + commission
                        shares[symbol] += delta_shares
                        trades.append(
                            {
                                "date": day,
                                "symbol": symbol,
                                "reason": signal_reason(old_target, target),
                                "close": close,
                                "from_target": old_target,
                                "target": target,
                                "delta_value": delta_value,
                                "commission": commission,
                                "risk_on": diagnostics["risk_on"],
                                "selected": diagnostics["selected"],
                                "gold_ok": diagnostics["gold_ok"],
                                "active_names": diagnostics.get("active_names", ""),
                                "estimated_vol": diagnostics.get("estimated_vol", ""),
                                "score": metrics.get(symbol, {}).get("score", ""),
                            }
                        )
                    current_targets = targets

        equity = cash + sum(shares[symbol] * last_close.get(symbol, 0.0) for symbol in SYMBOLS)
        equity_high = max(equity_high, equity)
        rows.append(
            {
                "date": day,
                "symbol": BENCHMARK_SYMBOL,
                "open": bench_row["open"],
                "high": bench_row["high"],
                "low": bench_row["low"],
                "close": bench_row["close"],
                "volume": bench_row["volume"],
                "amount": bench_row["amount"],
                "cash": cash,
                "equity": equity,
                "return": equity / INITIAL_CASH - 1,
                "drawdown": equity / equity_high - 1,
                "targets": json.dumps(current_targets, ensure_ascii=False, sort_keys=True),
            }
        )
        report_day_count += 1

    summary = {
        "final_return": rows[-1]["return"] if rows else 0.0,
        "max_drawdown": min(row["drawdown"] for row in rows) if rows else 0.0,
    }
    return rows, trades, summary


def main():
    set_token(gm_token())
    out_dir = Path("backtest_output")
    out_dir.mkdir(exist_ok=True)

    bars_by_symbol = {symbol: fetch_symbol_bars(symbol, ADJUST_PREV) for symbol in SYMBOLS}
    raw_bars_by_symbol = {symbol: fetch_symbol_bars(symbol, ADJUST_NONE) for symbol in SYMBOLS}
    raw_by_symbol_date = {
        symbol: {row["date"]: row for row in rows}
        for symbol, rows in raw_bars_by_symbol.items()
    }
    long_rows = []
    for symbol in SYMBOLS:
        for row in bars_by_symbol[symbol]:
            if row["date"] < START_TIME[:10]:
                continue
            item = dict(row)
            raw_row = raw_by_symbol_date.get(symbol, {}).get(row["date"], {})
            item["raw_open"] = raw_row.get("open", row["open"])
            item["raw_high"] = raw_row.get("high", row["high"])
            item["raw_low"] = raw_row.get("low", row["low"])
            item["raw_close"] = raw_row.get("close", row["close"])
            long_rows.append(item)
    rows, trades, summary = simulate(bars_by_symbol)

    write_csv(out_dir / "etf_bars.csv", long_rows)
    write_csv(out_dir / "bars_equity.csv", rows)
    write_csv(out_dir / "trades.csv", trades)
    print("ETF行情长表:", out_dir / "etf_bars.csv")
    print("组合资金曲线:", out_dir / "bars_equity.csv")
    print("离线交易明细:", out_dir / "trades.csv")
    print("离线复算累计收益:", pct(summary["final_return"]))
    print("离线复算最大回撤:", pct(summary["max_drawdown"]))


if __name__ == "__main__":
    main()
