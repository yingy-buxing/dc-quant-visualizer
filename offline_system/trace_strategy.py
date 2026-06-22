# coding=utf-8
from __future__ import print_function, absolute_import

import csv
import json
import os
from pathlib import Path

from gm.api import *

from etf_strategy_core import (
    FREQUENCY,
    LOOKBACK,
    REBALANCE_INTERVAL,
    SYMBOLS,
    calculate_targets,
    signal_reason,
    should_rebalance,
)


OUT_DIR = Path("backtest_output")
MAX_HOLD_DAYS = 18
STOP_LOSS = 0.07
TAKE_PROFIT = 0.0


def gm_token():
    token = os.environ.get("GM_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Please set GM_TOKEN before running this script.")
    return token


def init(context):
    context.etf_symbols = SYMBOLS
    context.frequency = FREQUENCY
    context.current_targets = {symbol: 0.0 for symbol in context.etf_symbols}
    context.position_state = {}
    context.last_bar_day = None
    context.day_count = 0

    context.signal_trace = []
    context.order_trace = []
    context.execution_trace = []

    subscribe(
        symbols=",".join(context.etf_symbols),
        frequency=context.frequency,
        count=LOOKBACK + 5,
        fields="symbol,open,high,low,close,amount,eob",
    )


def _history_by_symbol(context, end_time):
    result = {}
    day = str(end_time)[:10]
    for symbol in context.etf_symbols:
        data = history_n(
            symbol=symbol,
            frequency=context.frequency,
            count=LOOKBACK,
            end_time=end_time,
            fields="open,high,low,close,amount,eob",
            adjust=ADJUST_PREV,
            df=True,
        )
        if data is None or len(data) < 60:
            continue
        if str(data.iloc[-1]["eob"])[:10] != day:
            continue
        result[symbol] = data.to_dict("records")
    if len(result) < 5:
        return None
    return result


def _apply_trade_controls(context, targets, metrics):
    forced = {}
    for symbol, old_target in context.current_targets.items():
        if old_target < 0.005:
            continue
        metric = metrics.get(symbol)
        if not metric:
            continue
        state = context.position_state.setdefault(
            symbol,
            {"entry_price": metric["close"], "hold_days": 0},
        )
        state["hold_days"] += 1
        reason = ""
        if metric["low"] <= state["entry_price"] * (1 - STOP_LOSS):
            reason = "stop_loss"
        elif TAKE_PROFIT > 0 and metric["high"] >= state["entry_price"] * (1 + TAKE_PROFIT):
            reason = "take_profit"
        elif state["hold_days"] >= MAX_HOLD_DAYS:
            reason = "max_hold"
        if reason:
            targets[symbol] = 0.0
            forced[symbol] = reason
    return forced


def _update_position_state(context, targets, metrics):
    for symbol in context.etf_symbols:
        target = targets.get(symbol, 0.0)
        old_target = context.current_targets.get(symbol, 0.0)
        if target >= 0.005:
            if old_target < 0.005 or symbol not in context.position_state:
                metric = metrics.get(symbol, {})
                context.position_state[symbol] = {
                    "entry_price": metric.get("close", 0.0),
                    "hold_days": 0,
                }
        else:
            context.position_state.pop(symbol, None)


def on_bar(context, bars):
    bar = bars[0]
    day = str(bar["eob"])[:10]
    if context.last_bar_day == day:
        return
    context.last_bar_day = day
    context.day_count += 1

    if (context.day_count - 1) % REBALANCE_INTERVAL != 0:
        return

    history_map = _history_by_symbol(context, bar["eob"])
    if history_map is None:
        return

    targets, diagnostics, metrics = calculate_targets(history_map, context.current_targets)
    forced_reasons = _apply_trade_controls(context, targets, metrics)
    if not should_rebalance(context.current_targets, targets):
        return

    rebalance_symbols = sorted(
        context.etf_symbols,
        key=lambda item: targets.get(item, 0.0) - context.current_targets.get(item, 0.0),
    )
    for symbol in rebalance_symbols:
        target = targets.get(symbol, 0.0)
        old_target = context.current_targets.get(symbol, 0.0)
        if old_target < 0.0001 and target < 0.0001:
            continue
        metric = metrics.get(symbol, {})
        reason = forced_reasons.get(symbol) or signal_reason(old_target, target)
        signal = {
            "eob": bar["eob"],
            "symbol": symbol,
            "reason": reason,
            "close": metric.get("close", ""),
            "trend_mean": metric.get("ma120", ""),
            "z_score": metric.get("score", metric.get("trend200", "")),
            "from_target": old_target,
            "to_target": target,
            "risk_on": diagnostics["risk_on"],
            "selected": diagnostics["selected"],
            "gold_ok": diagnostics["gold_ok"],
            "active_names": diagnostics.get("active_names", ""),
            "estimated_vol": diagnostics.get("estimated_vol", ""),
            "top_scores": diagnostics["top_scores"],
        }
        context.signal_trace.append(signal)

        order_target_percent(
            symbol=symbol,
            percent=target,
            position_side=PositionSide_Long,
            order_type=OrderType_Market,
        )
    _update_position_state(context, targets, metrics)
    context.current_targets = targets


def on_order_status(context, order):
    context.order_trace.append(dict(order))


def on_execution_report(context, execution):
    context.execution_trace.append(dict(execution))


def _normalize(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value) if value is not None else ""


def _write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return

    fields = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                fields.append(key)
                seen.add(key)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _normalize(row.get(key)) for key in fields})


def on_backtest_finished(context, indicator):
    OUT_DIR.mkdir(exist_ok=True)
    _write_csv(OUT_DIR / "official_signals.csv", context.signal_trace)
    _write_csv(OUT_DIR / "official_orders.csv", context.order_trace)
    _write_csv(OUT_DIR / "official_executions.csv", context.execution_trace)
    _write_csv(OUT_DIR / "official_indicator.csv", [dict(indicator)])

    print("===== OFFICIAL TRACE FILES =====")
    print(OUT_DIR / "official_signals.csv")
    print(OUT_DIR / "official_orders.csv")
    print(OUT_DIR / "official_executions.csv")
    print(OUT_DIR / "official_indicator.csv")
    print("orders:", len(context.order_trace))
    print("executions:", len(context.execution_trace))
    print("pnl_ratio: {:.2%}".format(indicator["pnl_ratio"]))
    print("pnl_ratio_annual: {:.2%}".format(indicator["pnl_ratio_annual"]))
    print("max_drawdown: {:.2%}".format(indicator["max_drawdown"]))
    print("===== END TRACE =====")


if __name__ == "__main__":
    run(
        strategy_id="6dbacfa5-5036-11f1-9870-94bb43f0a40e",
        filename="trace_strategy.py",
        mode=MODE_BACKTEST,
        token=gm_token(),
        backtest_start_time="2020-01-01 08:00:00",
        backtest_end_time="2025-12-31 16:00:00",
        backtest_adjust=ADJUST_PREV,
        backtest_initial_cash=10000000,
        backtest_commission_ratio=0.0001,
        backtest_slippage_ratio=0.0001,
        backtest_match_mode=1,
    )
