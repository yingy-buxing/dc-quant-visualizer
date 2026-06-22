# coding=utf-8
from __future__ import print_function, absolute_import

import argparse
import csv
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "backtest_output"
VERSIONS_DIR = ROOT / "backtest_versions"
INDEX_JSON = VERSIONS_DIR / "index.json"
INDEX_HTML = VERSIONS_DIR / "index.html"

CODE_FILES = [
    "etf_strategy_core.py",
    "main.py",
    "trace_strategy.py",
]

OUTPUT_FILES = [
    "official_equity_reconstructed.csv",
    "official_executions.csv",
    "official_orders.csv",
    "official_signals.csv",
    "official_indicator.csv",
    "etf_bars.csv",
    "bars_equity.csv",
    "trades.csv",
]

TRAINING_CODE_FILES = [
    "train_t1_strategy_search.py",
    "etf_strategy_core.py",
]

TRAINING_OUTPUT_FILES = [
    "best_config.txt",
    "best_equity.csv",
    "best_trades.csv",
    "best_walk_forward_config.txt",
    "best_window_diagnostics.csv",
    "search_results.csv",
    "training_bars.csv",
    "walk_forward_results.csv",
    "walk_forward_windows.csv",
]


def read_csv_rows(path):
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values):
    return sum(values) / len(values) if values else 0.0


def stdev(values):
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return (sum((value - avg) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def pct(value):
    return "{:.2%}".format(value)


def mask_token(value):
    token = str(value).strip().strip("'\"")
    if len(token) <= 10:
        return "***"
    return token[:6] + "..." + token[-4:]


def parse_strategy_config():
    trace_path = ROOT / "trace_strategy.py"
    text = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""

    constants = {}
    for key, value in re.findall(r"^([A-Z][A-Z0-9_]*)\s*=\s*([^\n#]+)", text, re.MULTILINE):
        constants[key] = value.strip().rstrip(",")

    params = {}
    for key, value in re.findall(r"context\.(\w+)\s*=\s*([^\n#]+)", text):
        key = key.strip()
        if key in {
            "symbol",
            "frequency",
            "mean_window",
            "trend_window",
            "entry_z",
            "full_entry_z",
            "exit_z",
            "stop_z",
            "min_entry_day_return",
            "first_target",
            "full_target",
            "fast_window",
            "slow_window",
            "trend_window",
            "entry_buffer",
            "exit_buffer",
            "target_percent",
            "symbols",
            "current_targets",
        }:
            clean_value = value.strip().rstrip(",")
            params[key] = constants.get(clean_value, clean_value)

    symbol_match = re.search(r"^SYMBOL\s*=\s*([^\n#]+)", text, re.MULTILINE)
    if symbol_match and "symbol" not in params:
        params["symbol"] = symbol_match.group(1).strip().rstrip(",")

    run_args = {}
    for key, value in re.findall(
        r"(strategy_id|filename|mode|token|backtest_[a-zA-Z0-9_]+)\s*=\s*([^,\n)]+)",
        text,
    ):
        clean_value = value.strip().rstrip(",")
        run_args[key] = mask_token(clean_value) if key == "token" else clean_value

    return {"params": params, "run_args": run_args}


def collect_metrics():
    indicator_rows = read_csv_rows(OUTPUT_DIR / "official_indicator.csv")
    indicator = indicator_rows[0] if indicator_rows else {}
    executions = read_csv_rows(OUTPUT_DIR / "official_executions.csv")
    equity_rows = read_csv_rows(OUTPUT_DIR / "official_equity_reconstructed.csv")
    bars = read_csv_rows(OUTPUT_DIR / "bars_equity.csv")

    buy_hold_return = None
    if bars:
        first_close = fnum(bars[0].get("close"))
        last_close = fnum(bars[-1].get("close"))
        if first_close:
            buy_hold_return = last_close / first_close - 1

    reconstructed_return = None
    reconstructed_max_drawdown = None
    if equity_rows:
        reconstructed_return = fnum(equity_rows[-1].get("return"))
        reconstructed_max_drawdown = min(fnum(row.get("drawdown")) for row in equity_rows)

    return {
        "official_return": fnum(indicator.get("pnl_ratio")),
        "official_annual_return": fnum(indicator.get("pnl_ratio_annual")),
        "official_max_drawdown": fnum(indicator.get("max_drawdown")),
        "official_sharpe": fnum(indicator.get("sharp_ratio")),
        "official_win_ratio": fnum(indicator.get("win_ratio")),
        "open_count": int(fnum(indicator.get("open_count"))),
        "close_count": int(fnum(indicator.get("close_count"))),
        "execution_count": len(executions),
        "reconstructed_return": reconstructed_return,
        "reconstructed_max_drawdown": reconstructed_max_drawdown,
        "buy_hold_return": buy_hold_return,
    }


def collect_training_metrics():
    training_dir = OUTPUT_DIR / "t1_training"
    equity_rows = read_csv_rows(training_dir / "best_equity.csv")
    result_rows = read_csv_rows(training_dir / "walk_forward_results.csv")
    window_rows = read_csv_rows(training_dir / "best_window_diagnostics.csv")
    trades = read_csv_rows(training_dir / "best_trades.csv")
    config_path = training_dir / "best_config.txt"
    best_config = config_path.read_text(encoding="utf-8").strip() if config_path.exists() else ""
    best = next((row for row in result_rows if row.get("config_id") == best_config), result_rows[0] if result_rows else {})

    total_return = fnum(best.get("full_return"))
    annual = fnum(best.get("full_annual"))
    sharpe = fnum(best.get("full_sharpe"))
    max_drawdown = fnum(best.get("full_max_drawdown"))

    if equity_rows and (not best or best.get("config_id") != best_config):
        first = fnum(equity_rows[0].get("equity"))
        last = fnum(equity_rows[-1].get("equity"))
        total_return = last / first - 1 if first else 0.0
        years = len(equity_rows) / 252.0
        annual = (1 + total_return) ** (1 / years) - 1 if years > 0 and total_return > -1 else -1.0
        daily = [
            fnum(equity_rows[i].get("equity")) / fnum(equity_rows[i - 1].get("equity")) - 1
            for i in range(1, len(equity_rows))
            if fnum(equity_rows[i - 1].get("equity"))
        ]
        vol = (stdev(daily) or 0.0) * (252 ** 0.5)
        sharpe = (annual - 0.027378) / vol if vol > 0 else 0.0
        high = first
        max_drawdown = 0.0
        for row in equity_rows:
            equity = fnum(row.get("equity"))
            high = max(high, equity)
            max_drawdown = min(max_drawdown, equity / high - 1 if high else 0.0)
        if window_rows:
            test_returns = [fnum(row.get("test_return")) for row in window_rows]
            test_sharpes = [fnum(row.get("test_sharpe")) for row in window_rows]
            test_drawdowns = [fnum(row.get("test_max_drawdown")) for row in window_rows]
            best = {
                "positive_windows": len([value for value in test_returns if value > 0]),
                "window_count": len(window_rows),
                "avg_test_sharpe": mean(test_sharpes),
                "min_test_sharpe": min(test_sharpes) if test_sharpes else 0.0,
                "worst_test_drawdown": min(test_drawdowns) if test_drawdowns else 0.0,
            }

    closed = [row for row in trades if row.get("side") == "sell" and row.get("reason") != "final_liquidate"]
    wins = [row for row in closed if fnum(row.get("pnl")) > 0]

    return {
        "official_return": total_return,
        "official_annual_return": annual,
        "official_max_drawdown": abs(max_drawdown),
        "official_sharpe": sharpe,
        "official_win_ratio": len(wins) / len(closed) if closed else 0.0,
        "open_count": 0,
        "close_count": len(closed),
        "execution_count": len(trades),
        "reconstructed_return": total_return,
        "reconstructed_max_drawdown": max_drawdown,
        "buy_hold_return": 0.0,
        "training_positive_windows": int(fnum(best.get("positive_windows"))),
        "training_window_count": int(fnum(best.get("window_count"))),
        "training_avg_window_sharpe": fnum(best.get("avg_test_sharpe")),
        "training_min_window_sharpe": fnum(best.get("min_test_sharpe")),
        "training_worst_window_drawdown": fnum(best.get("worst_test_drawdown")),
    }


def copy_files(version_dir):
    code_dir = version_dir / "code"
    output_dir = version_dir / "outputs"
    code_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied = {"code": [], "outputs": []}
    missing = []

    for name in CODE_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, code_dir / name)
            copied["code"].append(name)
        else:
            missing.append(name)

    for name in OUTPUT_FILES:
        src = OUTPUT_DIR / name
        if src.exists():
            shutil.copy2(src, output_dir / name)
            copied["outputs"].append(name)
        else:
            missing.append("backtest_output/" + name)

    return copied, missing


def copy_training_files(version_dir):
    code_dir = version_dir / "code"
    output_dir = version_dir / "outputs"
    training_dir = OUTPUT_DIR / "t1_training"
    code_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied = {"code": [], "outputs": []}
    missing = []

    for name in TRAINING_CODE_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, code_dir / name)
            copied["code"].append(name)
        else:
            missing.append(name)

    for name in TRAINING_OUTPUT_FILES:
        src = training_dir / name
        if src.exists():
            shutil.copy2(src, output_dir / name)
            copied["outputs"].append(name)
        else:
            missing.append("backtest_output/t1_training/" + name)

    return copied, missing


def load_index():
    if not INDEX_JSON.exists():
        return []
    return json.loads(INDEX_JSON.read_text(encoding="utf-8"))


def html_text(value):
    return html.escape(str(value) if value is not None else "")


def link_if_exists(version_dir, rel_path, label=None):
    path = version_dir / rel_path
    safe_label = html_text(label or rel_path)
    safe_href = html_text(rel_path.as_posix() if isinstance(rel_path, Path) else str(rel_path).replace("\\", "/"))
    if path.exists():
        return f"<a href=\"{safe_href}\">{safe_label}</a>"
    return f"<span class=\"missing\">{safe_label}</span>"


def file_list(version_dir, rel_paths):
    items = []
    for rel_path in rel_paths:
        items.append("<li>{}</li>".format(link_if_exists(version_dir, rel_path)))
    return "\n".join(items) if items else "<li class=\"muted\">无</li>"


def shared_viewer_link(version_id):
    return "../backtest_output/lightweight_viewer.html?data=../backtest_versions/{}/payload.js&version={}".format(
        version_id,
        version_id,
    )


def write_shared_viewer():
    import render_lightweight_visualization as visualization

    OUTPUT_DIR.mkdir(exist_ok=True)
    visualization.write_html(OUTPUT_DIR / "lightweight_viewer.html")


def write_version_payload(entry):
    version_id = entry["version_id"]
    version_dir = VERSIONS_DIR / version_id
    output_dir = version_dir / "outputs"
    payload_path = version_dir / "payload.js"

    import render_lightweight_visualization as visualization

    old_out_dir = visualization.OUT_DIR
    try:
        visualization.OUT_DIR = output_dir
        payload = visualization.build_payload()
        visualization.write_payload_js(payload_path, payload)
    finally:
        visualization.OUT_DIR = old_out_dir


def calc_drawdown_rows(equity_rows):
    high = None
    rows = []
    for row in equity_rows:
        equity = fnum(row.get("equity"))
        high = equity if high is None else max(high, equity)
        drawdown = equity / high - 1 if high else 0.0
        item = dict(row)
        item["drawdown"] = drawdown
        rows.append(item)
    return rows


def build_training_payload(version_dir, metrics):
    output_dir = version_dir / "outputs"
    equity_rows = calc_drawdown_rows(read_csv_rows(output_dir / "best_equity.csv"))
    trades = read_csv_rows(output_dir / "best_trades.csv")
    windows = read_csv_rows(output_dir / "best_window_diagnostics.csv")
    if not windows:
        best_config = (output_dir / "best_config.txt").read_text(encoding="utf-8").strip() if (output_dir / "best_config.txt").exists() else ""
        windows = [
            row
            for row in read_csv_rows(output_dir / "walk_forward_windows.csv")
            if row.get("config_id") == best_config
        ]

    contribution = {}
    for trade in trades:
        if trade.get("side") != "sell" or trade.get("reason") == "final_liquidate":
            continue
        symbol = trade.get("symbol", "")
        item = contribution.setdefault(symbol, {"symbol": symbol, "pnl": 0.0, "trades": 0, "wins": 0})
        pnl = fnum(trade.get("pnl"))
        item["pnl"] += pnl
        item["trades"] += 1
        if pnl > 0:
            item["wins"] += 1

    equity = [
        {
            "date": row.get("date"),
            "equity": fnum(row.get("equity")),
            "return": fnum(row.get("return")),
            "drawdown": fnum(row.get("drawdown")),
            "exposure": fnum(row.get("exposure")),
            "position_count": int(fnum(row.get("position_count"))),
            "stress_count": int(fnum(row.get("stress_count"))),
        }
        for row in equity_rows
    ]
    trade_rows = [
        {
            "date": row.get("date"),
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "side": row.get("side"),
            "price": fnum(row.get("price")),
            "value": fnum(row.get("value")),
            "pnl": fnum(row.get("pnl")),
            "trade_return": fnum(row.get("trade_return")),
            "hold_days": row.get("hold_days"),
            "reason": row.get("reason"),
        }
        for row in trades
    ]
    return {
        "summary": metrics,
        "equity": equity,
        "windows": windows,
        "contribution": sorted(contribution.values(), key=lambda row: row["pnl"], reverse=True),
        "trades": trade_rows,
    }


def write_training_viewer(entry):
    version_id = entry["version_id"]
    version_dir = VERSIONS_DIR / version_id
    metadata_path = version_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else entry
    metrics = metadata.get("metrics", entry.get("metrics", {}))
    payload = build_training_payload(version_dir, metrics)
    payload_json = json.dumps(payload, ensure_ascii=False)
    html_page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Training Viewer __VERSION__</title>
  <style>
    body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; background: #f5f6f8; color: #111827; }
    header { padding: 20px 26px; background: #fff; border-bottom: 1px solid #dde3ea; display: flex; justify-content: space-between; gap: 16px; align-items: center; }
    h1 { margin: 0; font-size: 22px; }
    .sub { margin-top: 6px; color: #64748b; font-size: 13px; }
    main { padding: 18px 26px 28px; }
    .stats { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 10px; margin-bottom: 14px; }
    .stat, .panel { background: #fff; border: 1px solid #dde3ea; border-radius: 6px; }
    .stat { padding: 12px; }
    .label { color: #64748b; font-size: 12px; }
    .value { margin-top: 6px; font-size: 20px; font-weight: 700; }
    .panel { padding: 14px; margin-bottom: 14px; }
    .toolbar { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 8px; }
    .title { font-weight: 700; }
    svg { width: 100%; height: 280px; display: block; overflow: visible; }
    .grid { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(320px, 1fr); gap: 14px; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { padding: 7px 8px; border-bottom: 1px solid #edf2f7; text-align: right; white-space: nowrap; }
    th { color: #64748b; background: #f8fafc; position: sticky; top: 0; }
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
    .scroll { max-height: 420px; overflow: auto; border: 1px solid #edf2f7; border-radius: 6px; }
    .pos { color: #15803d; font-weight: 700; }
    .neg { color: #b42318; font-weight: 700; }
    a { color: #2563eb; text-decoration: none; font-weight: 700; }
    @media (max-width: 1000px) { .stats { grid-template-columns: repeat(2, 1fr); } .grid { grid-template-columns: 1fr; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>训练结果可视化 __VERSION__</h1>
      <div class="sub">数据来自本版本 outputs/best_equity.csv、best_trades.csv、walk_forward_windows.csv。</div>
    </div>
    <a href="index.html">返回详情</a>
  </header>
  <main>
    <section class="stats">
      <div class="stat"><div class="label">累计收益</div><div class="value" id="ret"></div></div>
      <div class="stat"><div class="label">年化收益</div><div class="value" id="ann"></div></div>
      <div class="stat"><div class="label">最大回撤</div><div class="value" id="dd"></div></div>
      <div class="stat"><div class="label">夏普</div><div class="value" id="sharpe"></div></div>
      <div class="stat"><div class="label">窗口胜率</div><div class="value" id="windows"></div></div>
      <div class="stat"><div class="label">交易数</div><div class="value" id="trades"></div></div>
    </section>
    <section class="panel">
      <div class="toolbar"><div class="title">权益曲线</div><div class="label">蓝线=累计收益，灰线=仓位暴露</div></div>
      <svg id="equitySvg"></svg>
    </section>
    <section class="panel">
      <div class="toolbar"><div class="title">回撤曲线</div></div>
      <svg id="drawdownSvg"></svg>
    </section>
    <section class="grid">
      <div class="panel">
        <div class="toolbar"><div class="title">半年度窗口</div></div>
        <div class="scroll"><table><thead><tr><th>窗口</th><th>区间</th><th>收益</th><th>夏普</th><th>回撤</th></tr></thead><tbody id="windowRows"></tbody></table></div>
      </div>
      <div class="panel">
        <div class="toolbar"><div class="title">标的贡献</div></div>
        <div class="scroll"><table><thead><tr><th>标的</th><th>净盈亏</th><th>交易</th><th>胜率</th></tr></thead><tbody id="contribRows"></tbody></table></div>
      </div>
    </section>
    <section class="panel">
      <div class="toolbar"><div class="title">交易明细</div></div>
      <div class="scroll"><table><thead><tr><th>日期</th><th>标的</th><th>方向</th><th>价格</th><th>盈亏</th><th>收益率</th><th>原因</th></tr></thead><tbody id="tradeRows"></tbody></table></div>
    </section>
  </main>
<script>
const payload = __PAYLOAD__;
const fmtPct = v => `${(Number(v || 0) * 100).toFixed(2)}%`;
const fmtNum = v => Number(v || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const cls = v => Number(v || 0) >= 0 ? "pos" : "neg";
document.getElementById("ret").textContent = fmtPct(payload.summary.official_return);
document.getElementById("ann").textContent = fmtPct(payload.summary.official_annual_return);
document.getElementById("dd").textContent = fmtPct(payload.summary.official_max_drawdown);
document.getElementById("sharpe").textContent = Number(payload.summary.official_sharpe || 0).toFixed(4);
document.getElementById("windows").textContent = `${payload.summary.training_positive_windows || 0}/${payload.summary.training_window_count || 0}`;
document.getElementById("trades").textContent = payload.trades.length;

function drawLine(svgId, rows, fields, options = {}) {
  const svg = document.getElementById(svgId);
  const w = svg.clientWidth || 1000, h = svg.clientHeight || 280;
  const pad = { l: 52, r: 18, t: 18, b: 28 };
  const vals = [];
  rows.forEach(r => fields.forEach(f => vals.push(Number(r[f.key] || 0) * (f.scale || 1))));
  let min = Math.min(...vals), max = Math.max(...vals);
  if (options.zeroFloor) min = Math.min(min, 0);
  if (max === min) { max += 1; min -= 1; }
  const x = i => pad.l + i * (w - pad.l - pad.r) / Math.max(1, rows.length - 1);
  const y = v => pad.t + (max - v) * (h - pad.t - pad.b) / (max - min);
  const grid = [0, 0.25, 0.5, 0.75, 1].map(p => {
    const yy = pad.t + p * (h - pad.t - pad.b);
    const value = max - p * (max - min);
    return `<line x1="${pad.l}" y1="${yy}" x2="${w-pad.r}" y2="${yy}" stroke="#edf2f7"/><text x="8" y="${yy+4}" fill="#64748b" font-size="11">${value.toFixed(1)}%</text>`;
  }).join("");
  const lines = fields.map(f => {
    const d = rows.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(r[f.key] || 0) * (f.scale || 1)).toFixed(1)}`).join(" ");
    return `<path d="${d}" fill="none" stroke="${f.color}" stroke-width="${f.width || 2}"/>`;
  }).join("");
  svg.innerHTML = `<rect x="0" y="0" width="${w}" height="${h}" fill="#fff"/>${grid}${lines}`;
}

drawLine("equitySvg", payload.equity, [
  { key: "return", scale: 100, color: "#2563eb", width: 2 },
  { key: "exposure", scale: 100, color: "#94a3b8", width: 1.5 }
], { zeroFloor: true });
drawLine("drawdownSvg", payload.equity, [
  { key: "drawdown", scale: 100, color: "#dc2626", width: 2 }
]);

document.getElementById("windowRows").innerHTML = payload.windows.map(w => `
  <tr><td>${w.window || ""}</td><td>${w.test_start || ""} - ${w.test_end || ""}</td><td class="${cls(w.test_return)}">${fmtPct(w.test_return)}</td><td>${Number(w.test_sharpe || 0).toFixed(3)}</td><td class="neg">${fmtPct(w.test_max_drawdown)}</td></tr>
`).join("");
document.getElementById("contribRows").innerHTML = payload.contribution.map(r => `
  <tr><td>${r.symbol}</td><td class="${cls(r.pnl)}">${fmtNum(r.pnl)}</td><td>${r.trades}</td><td>${fmtPct(r.trades ? r.wins / r.trades : 0)}</td></tr>
`).join("");
document.getElementById("tradeRows").innerHTML = payload.trades.slice().reverse().slice(0, 1000).map(t => `
  <tr><td>${t.date || ""}</td><td>${t.symbol || ""}</td><td>${t.side || ""}</td><td>${fmtNum(t.price)}</td><td class="${cls(t.pnl)}">${fmtNum(t.pnl)}</td><td class="${cls(t.trade_return)}">${fmtPct(t.trade_return)}</td><td>${t.reason || ""}</td></tr>
`).join("");
</script>
</body>
</html>"""
    html_page = html_page.replace("__VERSION__", html_text(version_id)).replace("__PAYLOAD__", payload_json)
    (version_dir / "training_viewer.html").write_text(html_page, encoding="utf-8")


def write_version_detail(entry):
    version_id = entry["version_id"]
    version_dir = VERSIONS_DIR / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = version_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else entry
    metrics = metadata.get("metrics", entry.get("metrics", {}))
    copied = metadata.get("copied_files", {})

    code_names = [name for name in CODE_FILES if (version_dir / "code" / name).exists()]
    if not code_names:
        code_names = [
            name
            for name in copied.get("code", [])
            if name.endswith(".py")
        ]

    output_names = [
        name
        for name in copied.get("outputs", OUTPUT_FILES)
        if name.endswith(".csv") and (version_dir / "outputs" / name).exists()
    ]
    if not output_names:
        output_names = [name for name in OUTPUT_FILES if (version_dir / "outputs" / name).exists()]

    run_args = metadata.get("strategy_config", {}).get("run_args", {})
    run_arg_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td></tr>".format(html_text(key), html_text(value))
        for key, value in run_args.items()
    ) or "<tr><td colspan=\"2\" class=\"muted\">无</td></tr>"
    viewer_section = ""
    if metadata.get("run_type") == "training":
        viewer_section = """
    <section class="panel">
      <h2>训练可视化</h2>
      <ul><li>__TRAINING_VIEWER_LINK__</li></ul>
    </section>"""

    page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backtest Version __VERSION__</title>
  <style>
    body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; background: #f5f6f8; color: #111827; }
    header { padding: 22px 28px; background: #fff; border-bottom: 1px solid #dde3ea; display: flex; align-items: center; justify-content: space-between; gap: 16px; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    main { padding: 22px 28px; }
    .back { color: #2563eb; text-decoration: none; font-weight: 700; }
    .note { margin-top: 8px; color: #475569; }
    .stats { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: 10px; margin-bottom: 16px; }
    .stat, .panel { background: #fff; border: 1px solid #dde3ea; border-radius: 6px; }
    .stat { padding: 12px; }
    .label { color: #64748b; font-size: 12px; }
    .value { margin-top: 6px; font-size: 20px; font-weight: 700; }
    .grid { display: grid; grid-template-columns: minmax(260px, 1fr) minmax(260px, 1fr); gap: 14px; }
    .panel { padding: 14px; margin-bottom: 14px; }
    h2 { margin: 0 0 10px; font-size: 16px; }
    ul { margin: 0; padding-left: 18px; line-height: 1.9; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    td { padding: 8px 10px; border-bottom: 1px solid #edf2f7; }
    td:first-child { color: #64748b; width: 230px; }
    a { color: #2563eb; text-decoration: none; font-weight: 700; }
    .muted, .missing { color: #94a3b8; }
    @media (max-width: 1000px) { .stats { grid-template-columns: repeat(2, minmax(120px, 1fr)); } .grid { grid-template-columns: 1fr; } header { align-items: flex-start; flex-direction: column; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>回测版本 __VERSION__</h1>
      <div class="note">__CREATED_AT__ · __NOTE__</div>
    </div>
    <a class="back" href="../index.html">返回版本列表</a>
  </header>
  <main>
    <section class="stats">
      <div class="stat"><div class="label">官方收益</div><div class="value">__RET__</div></div>
      <div class="stat"><div class="label">官方年化</div><div class="value">__ANN__</div></div>
      <div class="stat"><div class="label">最大回撤</div><div class="value">__DD__</div></div>
      <div class="stat"><div class="label">夏普</div><div class="value">__SHARPE__</div></div>
      <div class="stat"><div class="label">胜率</div><div class="value">__WIN__</div></div>
      <div class="stat"><div class="label">成交笔数</div><div class="value">__EXECUTIONS__</div></div>
    </section>
    <section class="grid">
      <div class="panel">
        <h2>策略代码</h2>
        <ul>__CODE_LINKS__</ul>
      </div>
      <div class="panel">
        <h2>回测数据</h2>
        <ul>__OUTPUT_LINKS__</ul>
      </div>
    </section>
    <section class="panel">
      <h2>运行参数</h2>
      <table><tbody>__RUN_ARGS__</tbody></table>
    </section>
    <section class="panel">
      <h2>原始记录</h2>
      <ul><li>__METADATA_LINK__</li></ul>
    </section>
    __VIEWER_SECTION__
  </main>
</body>
</html>"""

    replacements = {
        "__VERSION__": html_text(version_id),
        "__CREATED_AT__": html_text(metadata.get("created_at", entry.get("created_at", ""))),
        "__NOTE__": html_text(metadata.get("note", entry.get("note", "")) or "无备注"),
        "__RET__": pct(metrics.get("official_return", 0)),
        "__ANN__": pct(metrics.get("official_annual_return", 0)),
        "__DD__": pct(metrics.get("official_max_drawdown", 0)),
        "__SHARPE__": "{:.4f}".format(metrics.get("official_sharpe", 0) or 0),
        "__WIN__": pct(metrics.get("official_win_ratio", 0)),
        "__EXECUTIONS__": html_text(metrics.get("execution_count", 0)),
        "__CODE_LINKS__": file_list(version_dir, [Path("code") / name for name in code_names]),
        "__OUTPUT_LINKS__": file_list(version_dir, [Path("outputs") / name for name in output_names]),
        "__RUN_ARGS__": run_arg_rows,
        "__METADATA_LINK__": link_if_exists(version_dir, "metadata.json", "metadata.json"),
        "__VIEWER_SECTION__": viewer_section.replace(
            "__TRAINING_VIEWER_LINK__",
            link_if_exists(version_dir, "training_viewer.html", "training_viewer.html"),
        ),
    }
    for key, value in replacements.items():
        page = page.replace(key, value)
    (version_dir / "index.html").write_text(page, encoding="utf-8")


def write_index(entries):
    VERSIONS_DIR.mkdir(exist_ok=True)
    write_shared_viewer()
    INDEX_JSON.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rows = []
    for entry in sorted(entries, key=lambda item: item["created_at"], reverse=True):
        metrics = entry["metrics"]
        version_id = html.escape(entry["version_id"])
        note = html.escape(entry.get("note") or "")
        detail_link = f"{version_id}/index.html"
        if entry.get("run_type") == "training":
            write_training_viewer(entry)
            write_version_detail(entry)
            visualization_link = html.escape(f"{version_id}/training_viewer.html", quote=True)
            indicator_link = f"{version_id}/outputs/walk_forward_results.csv"
            executions_link = f"{version_id}/outputs/best_trades.csv"
        else:
            write_version_detail(entry)
            write_version_payload(entry)
            visualization_link = html.escape(shared_viewer_link(entry["version_id"]), quote=True)
            indicator_link = f"{version_id}/outputs/official_indicator.csv"
            executions_link = f"{version_id}/outputs/official_executions.csv"
        rows.append(
            "<tr>"
            f"<td><a href=\"{visualization_link}\">{version_id}</a></td>"
            f"<td>{html.escape(entry['created_at'])}</td>"
            f"<td>{pct(metrics.get('official_return', 0))}</td>"
            f"<td>{pct(metrics.get('official_annual_return', 0))}</td>"
            f"<td>{pct(metrics.get('official_max_drawdown', 0))}</td>"
            f"<td>{metrics.get('official_sharpe', 0):.4f}</td>"
            f"<td>{pct(metrics.get('buy_hold_return') or 0)}</td>"
            f"<td>{metrics.get('execution_count', 0)}</td>"
            f"<td><a href=\"{detail_link}\">详情</a> / <a href=\"{indicator_link}\">指标</a> / <a href=\"{executions_link}\">成交</a></td>"
            f"<td>{note}</td>"
            "</tr>"
        )

    page = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backtest Versions</title>
  <style>
    body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; background: #f5f6f8; color: #111827; }
    header { padding: 22px 28px; background: #fff; border-bottom: 1px solid #dde3ea; }
    h1 { margin: 0; font-size: 24px; letter-spacing: 0; }
    main { padding: 22px 28px; }
    table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dde3ea; }
    th, td { padding: 10px 12px; border-bottom: 1px solid #edf2f7; text-align: right; font-size: 13px; }
    th { background: #f8fafc; color: #475569; position: sticky; top: 0; }
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(9), td:nth-child(9), th:last-child, td:last-child { text-align: left; }
    a { color: #2563eb; text-decoration: none; font-weight: 700; }
  </style>
</head>
<body>
  <header><h1>回测版本记录</h1></header>
  <main>
    <table>
      <thead>
        <tr><th>版本</th><th>创建时间</th><th>官方收益</th><th>官方年化</th><th>最大回撤</th><th>夏普</th><th>买入持有</th><th>成交笔数</th><th>数据</th><th>备注</th></tr>
      </thead>
      <tbody>
        __ROWS__
      </tbody>
    </table>
  </main>
</body>
</html>"""
    INDEX_HTML.write_text(page.replace("__ROWS__", "\n".join(rows)), encoding="utf-8")


def record_version(note):
    VERSIONS_DIR.mkdir(exist_ok=True)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    version_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    version_dir = VERSIONS_DIR / version_id
    if version_dir.exists():
        raise RuntimeError("version already exists: {}".format(version_dir))

    version_dir.mkdir(parents=True)
    copied, missing = copy_files(version_dir)
    metadata = {
        "version_id": version_id,
        "created_at": created_at,
        "note": note,
        "metrics": collect_metrics(),
        "strategy_config": parse_strategy_config(),
        "copied_files": copied,
        "missing_files": missing,
        "entry_report": None,
    }
    (version_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    entries = [entry for entry in load_index() if entry.get("version_id") != version_id]
    entries.append(
        {
            "version_id": version_id,
            "created_at": created_at,
            "note": note,
            "metrics": metadata["metrics"],
            "entry_report": None,
        }
    )
    write_index(entries)
    return metadata


def record_training_version(note):
    VERSIONS_DIR.mkdir(exist_ok=True)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    version_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    version_dir = VERSIONS_DIR / version_id
    if version_dir.exists():
        raise RuntimeError("version already exists: {}".format(version_dir))

    version_dir.mkdir(parents=True)
    copied, missing = copy_training_files(version_dir)
    config_path = OUTPUT_DIR / "t1_training" / "best_config.txt"
    best_config = config_path.read_text(encoding="utf-8").strip() if config_path.exists() else ""
    metadata = {
        "version_id": version_id,
        "created_at": created_at,
        "note": note,
        "run_type": "training",
        "metrics": collect_training_metrics(),
        "strategy_config": {"training_best_config": best_config},
        "copied_files": copied,
        "missing_files": missing,
        "entry_report": None,
    }
    (version_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    entries = [entry for entry in load_index() if entry.get("version_id") != version_id]
    entries.append(
        {
            "version_id": version_id,
            "created_at": created_at,
            "note": note,
            "run_type": "training",
            "metrics": metadata["metrics"],
            "entry_report": None,
        }
    )
    write_index(entries)
    return metadata


def main():
    parser = argparse.ArgumentParser(description="Record current backtest output as a version.")
    parser.add_argument("--note", default="", help="Short note for this backtest version.")
    parser.add_argument("--training", action="store_true", help="Record t1_training search output instead of official backtest output.")
    args = parser.parse_args()

    metadata = record_training_version(args.note) if args.training else record_version(args.note)
    print("版本:", metadata["version_id"])
    print("官方收益:", pct(metadata["metrics"]["official_return"]))
    print("最大回撤:", pct(metadata["metrics"]["official_max_drawdown"]))
    print("买入持有:", pct(metadata["metrics"].get("buy_hold_return") or 0))
    print("版本目录:", VERSIONS_DIR / metadata["version_id"])
    print("版本索引:", INDEX_HTML)


if __name__ == "__main__":
    main()
