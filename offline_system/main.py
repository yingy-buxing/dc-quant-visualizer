# coding=utf-8
from __future__ import print_function, absolute_import

import os

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

MAX_HOLD_DAYS = 18
STOP_LOSS = 0.07
TAKE_PROFIT = 0.0


def gm_token():
    token = os.environ.get("GM_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Please set GM_TOKEN before running this script.")
    return token


def init(context):
    """Multi-ETF rotation with gold and cash hedges."""
    context.etf_symbols = SYMBOLS
    context.frequency = FREQUENCY
    context.current_targets = {symbol: 0.0 for symbol in context.etf_symbols}
    context.position_state = {}
    context.last_bar_day = None
    context.day_count = 0

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
        item = metrics.get(symbol)
        if not item:
            continue
        state = context.position_state.setdefault(
            symbol,
            {"entry_price": item["close"], "hold_days": 0},
        )
        state["hold_days"] += 1
        reason = ""
        if item["low"] <= state["entry_price"] * (1 - STOP_LOSS):
            reason = "stop_loss"
        elif TAKE_PROFIT > 0 and item["high"] >= state["entry_price"] * (1 + TAKE_PROFIT):
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
                item = metrics.get(symbol, {})
                context.position_state[symbol] = {
                    "entry_price": item.get("close", 0.0),
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
        if context.current_targets.get(symbol, 0.0) < 0.0001 and target < 0.0001:
            continue
        order_target_percent(
            symbol=symbol,
            percent=target,
            position_side=PositionSide_Long,
            order_type=OrderType_Market,
        )
        print(
            "{time} {reason} {symbol}: {old:.0%} -> {new:.0%}, "
            "risk_on={risk_on}, selected={selected}, gold_ok={gold_ok}, active={active}".format(
                time=bar["eob"],
                reason=forced_reasons.get(symbol) or signal_reason(context.current_targets.get(symbol, 0.0), target),
                symbol=symbol,
                old=context.current_targets.get(symbol, 0.0),
                new=target,
                risk_on=diagnostics["risk_on"],
                selected=diagnostics["selected"],
                gold_ok=diagnostics["gold_ok"],
                active=diagnostics.get("active_names", ""),
            )
        )
    _update_position_state(context, targets, metrics)
    context.current_targets = targets


def on_backtest_finished(context, indicator):
    print("===== BACKTEST INDICATOR =====")
    print("累计收益率: {:.2%}".format(indicator["pnl_ratio"]))
    print("年化收益率: {:.2%}".format(indicator["pnl_ratio_annual"]))
    print("最大回撤: {:.2%}".format(indicator["max_drawdown"]))
    print("夏普比率: {:.4f}".format(indicator["sharp_ratio"]))
    print("胜率: {:.2%}".format(indicator["win_ratio"]))
    print("开仓次数: {}".format(indicator["open_count"]))
    print("平仓次数: {}".format(indicator["close_count"]))
    print("盈利次数: {}".format(indicator["win_count"]))
    print("亏损次数: {}".format(indicator["lose_count"]))
    print("Calmar: {:.4f}".format(indicator["calmar_ratio"]))
    print("===== END INDICATOR =====")


if __name__ == "__main__":
    run(
        strategy_id="6dbacfa5-5036-11f1-9870-94bb43f0a40e",
        filename="main.py",
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
