# coding=utf-8
from __future__ import print_function, absolute_import

import csv
import json
from pathlib import Path


OUT_DIR = Path("backtest_output")
INITIAL_CASH = 10000000.0

SYMBOL_NAMES = {
    "SHSE.510300": "沪深300ETF",
    "SHSE.510500": "中证500ETF",
    "SHSE.511880": "银华日利",
    "SHSE.512170": "医疗ETF",
    "SHSE.512800": "银行ETF",
    "SHSE.512880": "证券ETF",
    "SHSE.515030": "新能源车ETF",
    "SHSE.518880": "黄金ETF",
    "SHSE.588000": "科创50ETF",
    "SZSE.159915": "创业板ETF",
}


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames = fields or list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row.get(key), ensure_ascii=False, sort_keys=True)
                    if isinstance(row.get(key), (dict, list, tuple))
                    else row.get(key, "")
                    for key in fieldnames
                }
            )


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def date_key(value):
    return str(value)[:10]


def build_official_equity(bars, executions, etf_bars=None):
    by_date = {}
    for execution in executions:
        by_date.setdefault(date_key(execution["created_at"]), []).append(execution)

    if etf_bars:
        close_by_day = {}
        factor_by_day = {}
        for row in etf_bars:
            day = date_key(row["date"])
            symbol = row["symbol"]
            close = fnum(row["close"])
            raw_close = fnum(row.get("raw_close")) or close
            close_by_day.setdefault(day, {})[symbol] = close
            factor_by_day.setdefault(day, {})[symbol] = close / raw_close if raw_close else 1.0

        cash = INITIAL_CASH
        shares = {}
        high = INITIAL_CASH
        rows = []

        for bar in bars:
            day = date_key(bar["date"])
            day_closes = close_by_day.get(day, {})

            for execution in by_date.get(day, []):
                symbol = execution.get("symbol", "")
                side = int(fnum(execution["side"]))
                amount = fnum(execution["amount"])
                volume = fnum(execution["volume"])
                commission = fnum(execution["commission"])
                shares.setdefault(symbol, 0.0)
                if side == 1:
                    cash -= amount + commission
                    shares[symbol] += volume
                elif side == 2:
                    cash += amount - commission
                    shares[symbol] -= volume

            holdings = []
            holdings_value = 0.0
            for symbol, volume in shares.items():
                value = volume * day_closes.get(symbol, 0.0)
                holdings_value += value
                if abs(value) > 1:
                    holdings.append({"symbol": symbol, "value": value, "shares": volume})
            equity = cash + holdings_value
            positions = [
                {
                    "symbol": item["symbol"],
                    "value": item["value"],
                    "shares": item["shares"],
                    "weight": item["value"] / equity if equity else 0.0,
                }
                for item in sorted(holdings, key=lambda row: row["value"], reverse=True)
            ]
            high = max(high, equity)
            rows.append(
                {
                    "time": day,
                    "close": fnum(bar["close"]),
                    "cash": cash,
                    "shares": json.dumps(shares, ensure_ascii=False, sort_keys=True),
                    "positions": positions,
                    "cash_weight": cash / equity if equity else 0.0,
                    "equity": equity,
                    "return": equity / INITIAL_CASH - 1,
                    "drawdown": equity / high - 1,
                }
            )

        return rows

    cash = INITIAL_CASH
    shares = 0.0
    high = INITIAL_CASH
    rows = []

    for bar in bars:
        day = date_key(bar["date"])
        close = fnum(bar["close"])

        for execution in by_date.get(day, []):
            side = int(fnum(execution["side"]))
            amount = fnum(execution["amount"])
            volume = fnum(execution["volume"])
            commission = fnum(execution["commission"])
            if side == 1:
                cash -= amount + commission
                shares += volume
            elif side == 2:
                cash += amount - commission
                shares -= volume

        equity = cash + shares * close
        high = max(high, equity)
        rows.append(
            {
                "time": day,
                "close": close,
                "cash": cash,
                "shares": shares,
                "equity": equity,
                "return": equity / INITIAL_CASH - 1,
                "drawdown": equity / high - 1,
            }
        )

    return rows


def build_symbol_contribution(executions, etf_bars, final_day):
    close_by_symbol = {}
    factor_by_day_symbol = {}
    if etf_bars:
        for row in etf_bars:
            symbol = row.get("symbol", "")
            day = date_key(row.get("date", ""))
            if not symbol or day > final_day:
                continue
            close = fnum(row.get("close"))
            raw_close = fnum(row.get("raw_close")) or close
            close_by_symbol[symbol] = close
            factor_by_day_symbol[(day, symbol)] = close / raw_close if raw_close else 1.0

    states = {}
    for execution in sorted(executions, key=lambda row: row.get("created_at", "")):
        symbol = execution.get("symbol", "")
        if not symbol:
            continue
        state = states.setdefault(
            symbol,
            {
                "symbol": symbol,
                "shares": 0.0,
                "cost_basis": 0.0,
                "realized": 0.0,
                "buy_amount": 0.0,
                "sell_amount": 0.0,
                "commission": 0.0,
                "buy_count": 0,
                "sell_count": 0,
                "trade_count": 0,
            },
        )
        side = int(fnum(execution.get("side")))
        amount = fnum(execution.get("amount"))
        volume = fnum(execution.get("volume"))
        commission = fnum(execution.get("commission"))
        day = date_key(execution.get("created_at", ""))
        state["commission"] += commission
        state["trade_count"] += 1

        if side == 1:
            state["shares"] += volume
            state["cost_basis"] += amount + commission
            state["buy_amount"] += amount
            state["buy_count"] += 1
        elif side == 2:
            previous_shares = state["shares"]
            average_cost = state["cost_basis"] / previous_shares if previous_shares > 0 else 0.0
            closed_volume = min(volume, previous_shares) if previous_shares > 0 else volume
            closed_cost = average_cost * closed_volume
            state["shares"] -= volume
            state["cost_basis"] -= closed_cost
            if abs(state["shares"]) < 1e-8:
                state["shares"] = 0.0
                state["cost_basis"] = 0.0
            state["realized"] += amount - commission - closed_cost
            state["sell_amount"] += amount
            state["sell_count"] += 1

    rows = []
    for symbol, state in states.items():
        final_close = close_by_symbol.get(symbol, 0.0)
        final_value = state["shares"] * final_close
        unrealized = final_value - state["cost_basis"]
        total = state["realized"] + unrealized
        rows.append(
            {
                "symbol": symbol,
                "realized": state["realized"],
                "unrealized": unrealized,
                "total": total,
                "contribution": total / INITIAL_CASH,
                "final_shares": state["shares"],
                "final_value": final_value,
                "buy_amount": state["buy_amount"],
                "sell_amount": state["sell_amount"],
                "commission": state["commission"],
                "buy_count": state["buy_count"],
                "sell_count": state["sell_count"],
                "trade_count": state["trade_count"],
            }
        )

    return sorted(rows, key=lambda row: row["total"], reverse=True)


def build_payload():
    bars = read_csv(OUT_DIR / "bars_equity.csv")
    etf_bars_path = OUT_DIR / "etf_bars.csv"
    etf_bars = read_csv(etf_bars_path) if etf_bars_path.exists() else None
    executions = read_csv(OUT_DIR / "official_executions.csv")
    signals = read_csv(OUT_DIR / "official_signals.csv")
    indicator = read_csv(OUT_DIR / "official_indicator.csv")[0]
    equity = build_official_equity(bars, executions, etf_bars)
    final_day = equity[-1]["time"] if equity else date_key(bars[-1]["date"]) if bars else ""
    contribution = build_symbol_contribution(executions, etf_bars, final_day)
    signal_by_day = {date_key(row["eob"]): row for row in signals}
    signal_by_day_symbol = {(date_key(row["eob"]), row.get("symbol", "")): row for row in signals}
    factor_by_day_symbol = {}
    if etf_bars:
        for row in etf_bars:
            day = date_key(row.get("date", ""))
            symbol = row.get("symbol", "")
            close = fnum(row.get("close"))
            raw_close = fnum(row.get("raw_close")) or close
            factor_by_day_symbol[(day, symbol)] = close / raw_close if raw_close else 1.0

    charts = {}
    if etf_bars:
        rows_by_symbol = {}
        for row in etf_bars:
            rows_by_symbol.setdefault(row["symbol"], []).append(row)
        for symbol, symbol_rows in sorted(rows_by_symbol.items()):
            candles_for_symbol = []
            prev_symbol_close = None
            for row in symbol_rows:
                close = fnum(row["close"])
                pct_change = None if not prev_symbol_close else close / prev_symbol_close - 1
                candles_for_symbol.append(
                    {
                        "time": date_key(row["date"]),
                        "open": fnum(row["open"]),
                        "high": fnum(row["high"]),
                        "low": fnum(row["low"]),
                        "close": close,
                        "volume": fnum(row["volume"]),
                        "amount": fnum(row["amount"]),
                        "pct_change": pct_change,
                    }
                )
                prev_symbol_close = close
            charts[symbol] = {
                "candles": candles_for_symbol,
                "volume": [
                    {
                        "time": candle["time"],
                        "value": candle["volume"],
                        "color": "rgba(100, 116, 139, 0.28)",
                    }
                    for candle in candles_for_symbol
                ],
                "markers": [],
            }

    candles = []
    prev_close = None
    for row in bars:
        close = fnum(row["close"])
        pct_change = None if not prev_close else close / prev_close - 1
        candles.append(
            {
                "time": date_key(row["date"]),
                "open": fnum(row["open"]),
                "high": fnum(row["high"]),
                "low": fnum(row["low"]),
                "close": close,
                "volume": fnum(row["volume"]),
                "amount": fnum(row["amount"]),
                "pct_change": pct_change,
            }
        )
        prev_close = close
    if not charts:
        symbol = bars[0].get("symbol", "benchmark") if bars else "benchmark"
        charts[symbol] = {"candles": candles, "volume": [], "markers": []}
    volume = [
        {
            "time": date_key(row["date"]),
            "value": fnum(row["volume"]),
            "color": "rgba(100, 116, 139, 0.28)",
        }
        for row in bars
    ]
    equity_line = [
        {
            "time": row["time"],
            "value": row["return"] * 100,
            "equity": row.get("equity", 0),
            "cash_weight": row.get("cash_weight", 0),
            "positions": row.get("positions", []),
        }
        for row in equity
    ]
    equity_dates = {row["time"] for row in equity_line}
    drawdown = [
        {
            "time": row["time"],
            "value": row["drawdown"] * 100,
            "color": "rgba(220, 38, 38, 0.45)",
        }
        for row in equity
    ]

    trades = []
    first_trade_symbol = executions[0].get("symbol", "") if executions else ""
    for execution in executions:
        day = date_key(execution["created_at"])
        side = int(fnum(execution["side"]))
        symbol = execution.get("symbol", "")
        signal = signal_by_day_symbol.get((day, symbol), signal_by_day.get(day, {}))
        direction = "buy" if side == 1 else "sell"
        target = fnum(signal.get("to_target"), None)
        raw_price = fnum(execution["price"])
        trades.append(
            {
                "time": execution["created_at"],
                "day": day,
                "symbol": symbol,
                "side": "买入" if side == 1 else "卖出",
                "reason": "",
                "price": raw_price,
                "raw_price": raw_price,
                "volume": fnum(execution["volume"]),
                "amount": fnum(execution["amount"]),
                "commission": fnum(execution["commission"]),
                "target": target,
                "z_score": fnum(signal.get("z_score"), None),
            }
        )
        label = ("买" if direction == "buy" else "卖")
        if target is not None:
            label += " {:.0%}".format(target)
        charts.setdefault(symbol, {"candles": [], "volume": [], "markers": []})
        charts[symbol]["markers"].append(
            {
                "time": day,
                "position": "belowBar" if direction == "buy" else "aboveBar",
                "color": "#16a34a" if direction == "buy" else "#dc2626",
                "shape": "arrowUp" if direction == "buy" else "arrowDown",
                "text": label,
            }
        )

    if equity_dates:
        for chart in charts.values():
            chart["candles"] = [candle for candle in chart["candles"] if candle["time"] in equity_dates]
            chart["volume"] = [item for item in chart["volume"] if item["time"] in equity_dates]
            chart["markers"] = [marker for marker in chart["markers"] if marker["time"] in equity_dates]

    default_symbol = first_trade_symbol or (sorted(charts.keys())[0] if charts else "")
    default_chart = charts.get(default_symbol, {"candles": candles, "volume": volume, "markers": []})

    return {
        "symbols": sorted(charts.keys()),
        "symbol_names": SYMBOL_NAMES,
        "default_symbol": default_symbol,
        "benchmark_symbol": bars[0].get("symbol", "") if bars else "",
        "charts": charts,
        "candles": default_chart["candles"],
        "volume": default_chart["volume"],
        "equity": equity_line,
        "drawdown": drawdown,
        "contribution": contribution,
        "trades": trades,
        "markers": default_chart["markers"],
        "summary": {
            "official_return": fnum(indicator.get("pnl_ratio")),
            "official_annual_return": fnum(indicator.get("pnl_ratio_annual")),
            "official_drawdown": fnum(indicator.get("max_drawdown")),
            "official_sharpe": fnum(indicator.get("sharp_ratio")),
            "official_win_ratio": fnum(indicator.get("win_ratio")),
            "open_count": int(fnum(indicator.get("open_count"))),
            "close_count": int(fnum(indicator.get("close_count"))),
            "reconstructed_return": equity[-1]["return"],
            "reconstructed_drawdown": min(row["drawdown"] for row in equity),
        },
    }


def write_payload_js(path, payload):
    path.write_text(
        "window.BACKTEST_PAYLOAD = {};\n".format(json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8",
    )


def write_reconstructed_equity(path, payload):
    drawdown_by_time = {row["time"]: row["value"] / 100.0 for row in payload.get("drawdown", [])}
    rows = []
    for row in payload.get("equity", []):
        rows.append(
            {
                "time": row.get("time"),
                "equity": row.get("equity", 0.0),
                "return": fnum(row.get("value")) / 100.0,
                "drawdown": drawdown_by_time.get(row.get("time"), 0.0),
                "cash_weight": row.get("cash_weight", 0.0),
                "positions": row.get("positions", []),
            }
        )
    write_csv(path, rows, ["time", "equity", "return", "drawdown", "cash_weight", "positions"])


def write_html(path, payload=None):
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Official Backtest - Lightweight Charts</title>
  <script src="https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js"></script>
  <script>
    (function () {
      const data = new URLSearchParams(window.location.search).get("data");
      if (data) {
        document.write('<script src="' + data.replace(/"/g, "%22") + '"><\\/script>');
      }
    })();
  </script>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; color: #111827; background: #f4f6f8; }
    header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 24px 12px; background: #fff; border-bottom: 1px solid #dde3ea; }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    .sub { margin-top: 6px; color: #64748b; font-size: 13px; }
    .tv { color: #2563eb; text-decoration: none; font-size: 13px; white-space: nowrap; }
    .stats { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 10px; padding: 14px 24px; }
    .stat { background: #fff; border: 1px solid #dde3ea; border-radius: 6px; padding: 11px 12px; }
    .label { color: #64748b; font-size: 12px; }
    .value { margin-top: 5px; font-size: 19px; font-weight: 700; }
    main { padding: 0 24px 24px; }
    .panel { background: #fff; border: 1px solid #dde3ea; border-radius: 6px; padding: 10px; margin-bottom: 14px; }
    .chart-wrap { position: relative; }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
    .title { font-weight: 700; font-size: 14px; }
    .buttons { display: flex; gap: 8px; flex-wrap: wrap; }
    button { border: 1px solid #cbd5e1; background: #fff; border-radius: 5px; padding: 6px 10px; font-size: 12px; cursor: pointer; }
    select { border: 1px solid #cbd5e1; background: #fff; border-radius: 5px; padding: 6px 9px; font-size: 12px; min-width: 140px; }
    button:hover { background: #f1f5f9; }
    #priceChart { height: 520px; }
    #tradeTooltip, #equityTooltip { display: none; position: absolute; z-index: 10; pointer-events: none; min-width: 260px; max-width: 380px; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: rgba(255, 255, 255, 0.98); box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16); font-size: 12px; color: #111827; }
    .tip-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 7px; font-weight: 700; }
    .tip-row { display: grid; grid-template-columns: 76px 1fr; gap: 8px; line-height: 1.7; }
    .tip-label { color: #64748b; }
    .tip-buy { color: #15803d; font-weight: 700; }
    .tip-sell { color: #b42318; font-weight: 700; }
    #equityChart { height: 280px; }
    #drawdownChart { height: 220px; }
    .contribution-grid { display: grid; grid-template-columns: minmax(280px, 1fr) minmax(360px, 1.5fr); gap: 12px; align-items: stretch; }
    .contribution-bars { display: flex; flex-direction: column; gap: 10px; padding: 4px 2px; }
    .contribution-item { display: grid; grid-template-columns: 150px 1fr 110px; gap: 10px; align-items: center; cursor: pointer; }
    .contribution-name { font-size: 12px; color: #334155; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-track { position: relative; height: 18px; background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 4px; overflow: hidden; }
    .bar-zero { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #94a3b8; }
    .bar-fill { position: absolute; top: 2px; bottom: 2px; min-width: 2px; border-radius: 3px; }
    .bar-fill.positive { left: 50%; background: #16a34a; }
    .bar-fill.negative { right: 50%; background: #dc2626; }
    .contribution-value { font-size: 12px; font-weight: 700; text-align: right; }
    .positive-text { color: #15803d; }
    .negative-text { color: #b42318; }
    .table-wrap { max-height: 500px; overflow: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #edf2f7; text-align: right; white-space: nowrap; }
    th { position: sticky; top: 0; background: #f8fafc; color: #475569; }
    th:first-child, td:first-child, th:nth-child(3), td:nth-child(3) { text-align: left; }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: #f8fafc; }
    tbody tr.selected { background: #e0f2fe; }
    .buy { color: #15803d; font-weight: 700; }
    .sell { color: #b42318; font-weight: 700; }
    @media (max-width: 900px) {
      header { align-items: flex-start; flex-direction: column; }
      .stats { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      .contribution-grid { grid-template-columns: 1fr; }
      .contribution-item { grid-template-columns: 120px 1fr 90px; }
      #priceChart { height: 460px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>掘金官方成交回测可视化</h1>
      <div class="sub">支持鼠标拖动、滚轮缩放、十字光标和价格/收益轴缩放；数据来自 official_executions.csv 与 official_indicator.csv。</div>
    </div>
    <a class="tv" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">Charts by TradingView Lightweight Charts™</a>
  </header>
  <section class="stats">
    <div class="stat"><div class="label">官方累计收益</div><div class="value" id="ret"></div></div>
    <div class="stat"><div class="label">年化收益</div><div class="value" id="ann"></div></div>
    <div class="stat"><div class="label">最大回撤</div><div class="value" id="dd"></div></div>
    <div class="stat"><div class="label">夏普</div><div class="value" id="sharpe"></div></div>
    <div class="stat"><div class="label">胜率</div><div class="value" id="win"></div></div>
    <div class="stat"><div class="label">成交笔数</div><div class="value" id="trades"></div></div>
  </section>
  <main>
    <section class="panel">
      <div class="toolbar">
        <div class="title">标的收益贡献</div>
      </div>
      <div class="contribution-grid">
        <div class="contribution-bars" id="contributionBars"></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>标的</th><th>总盈亏</th><th>贡献率</th><th>已实现</th><th>浮动</th><th>期末市值</th><th>手续费</th><th>成交</th></tr></thead>
            <tbody id="contributionRows"></tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="toolbar">
        <div class="title">价格 K 线、成交点与成交量</div>
        <div class="buttons"><select id="symbolSelect" aria-label="选择ETF"></select><button id="fitPrice">适配全图</button><button id="lastYear">最近一年</button></div>
      </div>
      <div class="chart-wrap">
        <div id="priceChart"></div>
        <div id="tradeTooltip"></div>
      </div>
    </section>
    <section class="panel">
      <div class="toolbar"><div class="title" id="equityTitle">官方组合收益曲线与当日仓位</div><div class="buttons"><button id="fitEquity">适配全图</button></div></div>
      <div class="chart-wrap">
        <div id="equityChart"></div>
        <div id="equityTooltip"></div>
      </div>
    </section>
    <section class="panel">
      <div class="toolbar"><div class="title">回撤曲线</div></div>
      <div id="drawdownChart"></div>
    </section>
    <section class="panel">
      <div class="toolbar"><div class="title">官方逐笔成交明细</div></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>成交时间</th><th>代码</th><th>方向</th><th>目标仓位</th><th>成交价</th><th>成交量</th><th>成交金额</th><th>手续费</th><th>信号分数</th></tr></thead>
          <tbody id="tradeRows"></tbody>
        </table>
      </div>
    </section>
  </main>
<script>
const payload = window.BACKTEST_PAYLOAD || __PAYLOAD__;
if (!payload) {
  document.body.innerHTML = '<main style="padding:24px;font-family:Arial,Microsoft YaHei,sans-serif;"><h1>没有加载到回测数据</h1><p>请从回测版本记录页打开，或提供 data 参数。</p></main>';
  throw new Error("No backtest payload loaded.");
}
const LWC = window.LightweightCharts;
const fmtPct = v => (v * 100).toFixed(2) + "%";
const fmtPctPoint = v => v.toFixed(2) + "%";
const fmtNum = v => Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const fmtSignedNum = v => `${v >= 0 ? "+" : ""}${fmtNum(v)}`;
const symbolNames = payload.symbol_names || {};
const symbolLabel = symbol => symbolNames[symbol] ? `${symbol} ${symbolNames[symbol]}` : symbol;

document.getElementById("ret").textContent = fmtPct(payload.summary.official_return);
document.getElementById("ann").textContent = fmtPct(payload.summary.official_annual_return);
document.getElementById("dd").textContent = fmtPct(payload.summary.official_drawdown);
document.getElementById("sharpe").textContent = payload.summary.official_sharpe.toFixed(4);
document.getElementById("win").textContent = fmtPct(payload.summary.official_win_ratio);
document.getElementById("trades").textContent = payload.trades.length;

const baseOptions = {
  layout: { background: { color: "#ffffff" }, textColor: "#334155" },
  grid: { vertLines: { color: "#edf2f7" }, horzLines: { color: "#edf2f7" } },
  crosshair: { mode: LWC.CrosshairMode.Normal },
  rightPriceScale: { borderColor: "#dbe3ea", scaleMargins: { top: 0.08, bottom: 0.22 } },
  timeScale: { borderColor: "#dbe3ea", timeVisible: false, secondsVisible: false },
  localization: { locale: "zh-CN" },
  handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
  handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
  attributionLogo: true
};

function makeChart(id, height) {
  const el = document.getElementById(id);
  const chart = LWC.createChart(el, { ...baseOptions, width: el.clientWidth, height });
  new ResizeObserver(entries => {
    const width = Math.floor(entries[0].contentRect.width);
    chart.applyOptions({ width });
  }).observe(el);
  return chart;
}

const priceChart = makeChart("priceChart", document.getElementById("priceChart").clientHeight);
const candleSeries = priceChart.addSeries(LWC.CandlestickSeries, {
  upColor: "#16a34a", downColor: "#dc2626", borderVisible: false,
  wickUpColor: "#16a34a", wickDownColor: "#dc2626"
});
const volumeSeries = priceChart.addSeries(LWC.HistogramSeries, {
  priceFormat: { type: "volume" },
  priceScaleId: "",
});
volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
const symbolSelect = document.getElementById("symbolSelect");
payload.symbols.forEach(symbol => {
  const option = document.createElement("option");
  option.value = symbol;
  option.textContent = symbolLabel(symbol);
  symbolSelect.appendChild(option);
});

let activeSymbol = payload.default_symbol || payload.symbols[0];
let activeCandles = [];
let candleByDay = new Map();
let candleIndexByDay = new Map();
let tradesByDay = new Map();
let markerApi = null;

function setSeriesMarkers(markers) {
  if (LWC.createSeriesMarkers) {
    if (markerApi && markerApi.setMarkers) {
      markerApi.setMarkers(markers);
    } else {
      markerApi = LWC.createSeriesMarkers(candleSeries, markers);
    }
  } else if (candleSeries.setMarkers) {
    candleSeries.setMarkers(markers);
  }
}

function loadSymbolChart(symbol, options = {}) {
  const chartData = payload.charts[symbol];
  if (!chartData) return;
  activeSymbol = symbol;
  symbolSelect.value = symbol;
  activeCandles = chartData.candles || [];
  candleSeries.setData(activeCandles);
  volumeSeries.setData(chartData.volume || []);
  setSeriesMarkers(chartData.markers || []);
  candleByDay = new Map(activeCandles.map(candle => [candle.time, candle]));
  candleIndexByDay = new Map(activeCandles.map((candle, index) => [candle.time, index]));
  tradesByDay = new Map();
  payload.trades.filter(trade => trade.symbol === symbol).forEach(trade => {
    const list = tradesByDay.get(trade.day) || [];
    list.push(trade);
    tradesByDay.set(trade.day, list);
  });
  if (selectedPriceLine) {
    candleSeries.removePriceLine(selectedPriceLine);
    selectedPriceLine = null;
  }
  tradeTooltip.style.display = "none";
  if (options.fit !== false) priceChart.timeScale().fitContent();
}

symbolSelect.onchange = () => loadSymbolChart(symbolSelect.value);
const tradeTooltip = document.getElementById("tradeTooltip");
const priceChartEl = document.getElementById("priceChart");
function renderKlineTooltip(candle, trades, time) {
  const tradeRows = trades.map(t => `
    <div class="tip-head">
      <span class="${t.side === "买入" ? "tip-buy" : "tip-sell"}">${t.side} ${symbolLabel(t.symbol)}</span>
    </div>
    <div class="tip-row"><span class="tip-label">成交价</span><span>${t.price.toFixed(4)}</span></div>
    <div class="tip-row"><span class="tip-label">成交量</span><span>${fmtNum(t.volume)}</span></div>
    <div class="tip-row"><span class="tip-label">成交金额</span><span>${fmtNum(t.amount)}</span></div>
    <div class="tip-row"><span class="tip-label">手续费</span><span>${fmtNum(t.commission)}</span></div>
    <div class="tip-row"><span class="tip-label">目标仓位</span><span>${t.target == null ? "" : fmtPct(t.target)}</span></div>
    <div class="tip-row"><span class="tip-label">信号分数</span><span>${t.z_score == null ? "" : t.z_score.toFixed(2)}</span></div>
  `).join('<div style="height:1px;background:#e5e7eb;margin:8px 0;"></div>');
  const klineRows = `
    <div class="tip-head"><span>K 线行情</span><span>${time}</span></div>
    <div class="tip-row"><span class="tip-label">开盘</span><span>${candle.open.toFixed(4)}</span></div>
    <div class="tip-row"><span class="tip-label">最高</span><span>${candle.high.toFixed(4)}</span></div>
    <div class="tip-row"><span class="tip-label">最低</span><span>${candle.low.toFixed(4)}</span></div>
    <div class="tip-row"><span class="tip-label">收盘</span><span>${candle.close.toFixed(4)}</span></div>
    <div class="tip-row"><span class="tip-label">涨跌幅</span><span class="${(candle.pct_change || 0) >= 0 ? "tip-buy" : "tip-sell"}">${candle.pct_change == null ? "" : fmtPct(candle.pct_change)}</span></div>
    <div class="tip-row"><span class="tip-label">成交量</span><span>${fmtNum(candle.volume)}</span></div>
    <div class="tip-row"><span class="tip-label">成交额</span><span>${fmtNum(candle.amount)}</span></div>
  `;
  tradeTooltip.innerHTML = trades.length
    ? klineRows + '<div style="height:1px;background:#cbd5e1;margin:9px 0;"></div>' + tradeRows
    : klineRows;
}
priceChart.subscribeCrosshairMove(param => {
  if (!param || !param.time || !param.point) {
    tradeTooltip.style.display = "none";
    return;
  }
  const time = typeof param.time === "string" ? param.time : `${param.time.year}-${String(param.time.month).padStart(2, "0")}-${String(param.time.day).padStart(2, "0")}`;
  const candle = candleByDay.get(time);
  const trades = tradesByDay.get(time) || [];
  if (!candle || param.point.x < 0 || param.point.y < 0 || param.point.x > priceChartEl.clientWidth || param.point.y > priceChartEl.clientHeight) {
    tradeTooltip.style.display = "none";
    return;
  }
  renderKlineTooltip(candle, trades, time);
  tradeTooltip.style.display = "block";
  const box = tradeTooltip.getBoundingClientRect();
  const wrap = priceChartEl.getBoundingClientRect();
  const x = Math.min(param.point.x + 18, wrap.width - box.width - 8);
  const y = Math.max(8, Math.min(param.point.y - 12, wrap.height - box.height - 8));
  tradeTooltip.style.left = `${Math.max(8, x)}px`;
  tradeTooltip.style.top = `${y}px`;
});

const equityChart = makeChart("equityChart", document.getElementById("equityChart").clientHeight);
const equitySeries = equityChart.addSeries(LWC.LineSeries, {
  color: "#2563eb", lineWidth: 2,
  priceFormat: { type: "custom", formatter: fmtPctPoint }
});
equitySeries.setData(payload.equity);
equityChart.timeScale().fitContent();

const equityTooltip = document.getElementById("equityTooltip");
const equityChartEl = document.getElementById("equityChart");
const equityByDay = new Map(payload.equity.map(row => [row.time, row]));
function renderEquityTooltip(row, time) {
  const positionRows = (row.positions || []).length
    ? row.positions.map(pos => `
      <div class="tip-row"><span class="tip-label">${symbolLabel(pos.symbol)}</span><span>${fmtPct(pos.weight)} / ${fmtNum(pos.value)}</span></div>
    `).join("")
    : '<div class="tip-row"><span class="tip-label">持仓</span><span>空仓</span></div>';
  equityTooltip.innerHTML = `
    <div class="tip-head"><span>组合仓位</span><span>${time}</span></div>
    <div class="tip-row"><span class="tip-label">组合收益</span><span>${fmtPctPoint(row.value)}</span></div>
    <div class="tip-row"><span class="tip-label">组合净值</span><span>${fmtNum(row.equity)}</span></div>
    <div class="tip-row"><span class="tip-label">现金</span><span>${fmtPct(row.cash_weight || 0)}</span></div>
    <div style="height:1px;background:#cbd5e1;margin:9px 0;"></div>
    ${positionRows}
  `;
}
equityChart.subscribeCrosshairMove(param => {
  if (!param || !param.time || !param.point) {
    equityTooltip.style.display = "none";
    return;
  }
  const time = typeof param.time === "string" ? param.time : `${param.time.year}-${String(param.time.month).padStart(2, "0")}-${String(param.time.day).padStart(2, "0")}`;
  const row = equityByDay.get(time);
  if (!row || param.point.x < 0 || param.point.y < 0 || param.point.x > equityChartEl.clientWidth || param.point.y > equityChartEl.clientHeight) {
    equityTooltip.style.display = "none";
    return;
  }
  renderEquityTooltip(row, time);
  equityTooltip.style.display = "block";
  const box = equityTooltip.getBoundingClientRect();
  const wrap = equityChartEl.getBoundingClientRect();
  const x = Math.min(param.point.x + 18, wrap.width - box.width - 8);
  const y = Math.max(8, Math.min(param.point.y - 12, wrap.height - box.height - 8));
  equityTooltip.style.left = `${Math.max(8, x)}px`;
  equityTooltip.style.top = `${y}px`;
});

const drawdownChart = makeChart("drawdownChart", document.getElementById("drawdownChart").clientHeight);
const drawdownSeries = drawdownChart.addSeries(LWC.HistogramSeries, {
  color: "rgba(220, 38, 38, 0.5)",
  priceFormat: { type: "custom", formatter: fmtPctPoint }
});
drawdownSeries.setData(payload.drawdown);
drawdownChart.timeScale().fitContent();

function syncVisibleRange(source, targets) {
  source.timeScale().subscribeVisibleLogicalRangeChange(range => {
    if (!range) return;
    targets.forEach(chart => chart.timeScale().setVisibleLogicalRange(range));
  });
}
syncVisibleRange(priceChart, [equityChart, drawdownChart]);
syncVisibleRange(equityChart, [priceChart, drawdownChart]);
syncVisibleRange(drawdownChart, [priceChart, equityChart]);

document.getElementById("fitPrice").onclick = () => priceChart.timeScale().fitContent();
document.getElementById("fitEquity").onclick = () => equityChart.timeScale().fitContent();
document.getElementById("lastYear").onclick = () => {
  const last = activeCandles.length - 1;
  priceChart.timeScale().setVisibleLogicalRange({ from: Math.max(0, last - 250), to: last + 5 });
};

document.getElementById("tradeRows").innerHTML = payload.trades.map((t, index) => `
  <tr class="trade-row" data-trade-index="${index}">
    <td>${t.time}</td>
    <td>${symbolLabel(t.symbol)}</td>
    <td class="${t.side === "买入" ? "buy" : "sell"}">${t.side}</td>
    <td>${t.target == null ? "" : fmtPct(t.target)}</td>
    <td>${t.price.toFixed(4)}</td>
    <td>${fmtNum(t.volume)}</td>
    <td>${fmtNum(t.amount)}</td>
    <td>${fmtNum(t.commission)}</td>
    <td>${t.z_score == null ? "" : t.z_score.toFixed(2)}</td>
  </tr>
`).join("");
let selectedPriceLine = null;
loadSymbolChart(activeSymbol);

function renderContribution() {
  const rows = payload.contribution || [];
  const barsEl = document.getElementById("contributionBars");
  const tableEl = document.getElementById("contributionRows");
  if (!rows.length) {
    barsEl.innerHTML = '<div class="tip-label">暂无标的收益贡献数据</div>';
    tableEl.innerHTML = '<tr><td colspan="8">暂无数据</td></tr>';
    return;
  }
  const maxAbs = Math.max(...rows.map(row => Math.abs(row.total || 0)), 1);
  barsEl.innerHTML = rows.map(row => {
    const width = Math.max(1, Math.abs(row.total || 0) / maxAbs * 50);
    const klass = row.total >= 0 ? "positive" : "negative";
    const textClass = row.total >= 0 ? "positive-text" : "negative-text";
    return `
      <div class="contribution-item contribution-row" data-symbol="${row.symbol}">
        <div class="contribution-name" title="${symbolLabel(row.symbol)}">${symbolLabel(row.symbol)}</div>
        <div class="bar-track">
          <div class="bar-zero"></div>
          <div class="bar-fill ${klass}" style="width:${width}%"></div>
        </div>
        <div class="contribution-value ${textClass}">${fmtSignedNum(row.total)}</div>
      </div>
    `;
  }).join("");
  tableEl.innerHTML = rows.map(row => {
    const textClass = row.total >= 0 ? "positive-text" : "negative-text";
    return `
      <tr class="contribution-row" data-symbol="${row.symbol}">
        <td>${symbolLabel(row.symbol)}</td>
        <td class="${textClass}">${fmtSignedNum(row.total)}</td>
        <td class="${textClass}">${fmtPct(row.contribution || 0)}</td>
        <td>${fmtSignedNum(row.realized || 0)}</td>
        <td>${fmtSignedNum(row.unrealized || 0)}</td>
        <td>${fmtNum(row.final_value || 0)}</td>
        <td>${fmtNum(row.commission || 0)}</td>
        <td>${row.trade_count || 0}</td>
      </tr>
    `;
  }).join("");
  document.querySelectorAll(".contribution-row").forEach(row => {
    row.addEventListener("click", () => {
      const symbol = row.dataset.symbol;
      if (payload.charts && payload.charts[symbol]) {
        loadSymbolChart(symbol);
        document.getElementById("priceChart").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });
}
renderContribution();

function focusTrade(index) {
  const trade = payload.trades[index];
  if (!trade) return;
  if (trade.symbol !== activeSymbol) {
    loadSymbolChart(trade.symbol, { fit: false });
  }
  const candleIndex = candleIndexByDay.get(trade.day);
  if (candleIndex == null) return;

  document.querySelectorAll(".trade-row").forEach(row => row.classList.remove("selected"));
  const row = document.querySelector(`.trade-row[data-trade-index="${index}"]`);
  if (row) row.classList.add("selected");

  priceChart.timeScale().setVisibleLogicalRange({
    from: Math.max(0, candleIndex - 45),
    to: Math.min(activeCandles.length - 1, candleIndex + 25),
  });

  if (selectedPriceLine) {
    candleSeries.removePriceLine(selectedPriceLine);
  }
  selectedPriceLine = candleSeries.createPriceLine({
    price: trade.price,
    color: trade.side === "买入" ? "#16a34a" : "#dc2626",
    lineWidth: 2,
    lineStyle: LWC.LineStyle.Dashed,
    axisLabelVisible: true,
    title: `${trade.side} ${trade.price.toFixed(4)}`,
  });

  const candle = candleByDay.get(trade.day);
  const trades = tradesByDay.get(trade.day) || [];
  renderKlineTooltip(candle, trades, trade.day);
  tradeTooltip.style.display = "block";
  tradeTooltip.style.left = "18px";
  tradeTooltip.style.top = "18px";
}
document.querySelectorAll(".trade-row").forEach(row => {
  row.addEventListener("click", () => focusTrade(Number(row.dataset.tradeIndex)));
});
</script>
</body>
</html>"""
    payload_json = "null" if payload is None else json.dumps(payload, ensure_ascii=False)
    path.write_text(html.replace("__PAYLOAD__", payload_json), encoding="utf-8")


def main():
    payload = build_payload()
    write_html(OUT_DIR / "lightweight_viewer.html")
    write_payload_js(OUT_DIR / "current_payload.js", payload)
    write_reconstructed_equity(OUT_DIR / "official_equity_reconstructed.csv", payload)
    print("Lightweight Charts 页面:", OUT_DIR / "lightweight_viewer.html")
    print("当前数据:", OUT_DIR / "current_payload.js")
    print("官方累计收益:", "{:.2%}".format(payload["summary"]["official_return"]))
    print("成交笔数:", len(payload["trades"]))


if __name__ == "__main__":
    main()
