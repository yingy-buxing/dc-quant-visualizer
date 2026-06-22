# Offline Backtest Pipeline

这个目录包含一套可公开的本地回测和数据转换流程，用于把掘金量化官方回测输出转换成前端可视化需要的 `payload.js`。

脚本不包含真实 token。运行前需要自己设置 `GM_TOKEN`。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `etf_strategy_core.py` | 示例多标的轮动策略核心逻辑 |
| `main.py` | 最简掘金官方 `run(...)` 回测入口 |
| `trace_strategy.py` | 推荐入口，跑官方回测并导出信号、订单、成交和指标 |
| `export_multi_etf_data.py` | 拉取行情并生成可视化所需 CSV |
| `render_lightweight_visualization.py` | 把 CSV 转成 `current_payload.js` 和 `lightweight_viewer.html` |
| `record_backtest_version.py` | 保存一次回测版本快照 |
| `analyze_loss_trades.py` | 亏损交易复盘辅助脚本 |

## 1. 准备环境

建议使用 Python 3.10+。

安装依赖：

```powershell
pip install gm
```

如果你使用掘金量化终端自带或自己创建的虚拟环境，请先激活它。

设置掘金 token：

```powershell
$env:GM_TOKEN="your_gm_token_here"
```

如果要长期使用，可以把 `GM_TOKEN` 配到系统环境变量。

## 2. 跑官方回测并导出官方流水

进入目录：

```powershell
Set-Location offline_system
```

执行：

```powershell
python trace_strategy.py
```

输出目录：

```text
backtest_output/
```

主要输出文件：

```text
backtest_output/official_signals.csv
backtest_output/official_orders.csv
backtest_output/official_executions.csv
backtest_output/official_indicator.csv
```

这些文件来自掘金官方回测，是后续可视化的核心数据来源。

## 3. 导出行情和组合数据

执行：

```powershell
python export_multi_etf_data.py
```

会生成：

```text
backtest_output/etf_bars.csv
backtest_output/bars_equity.csv
backtest_output/trades.csv
```

说明：

- `etf_bars.csv`: 各标的日线行情长表
- `bars_equity.csv`: 离线复算组合曲线
- `trades.csv`: 离线复算交易明细

前端最终优先展示官方成交和官方指标，但也需要行情数据来画 K 线、成交点和持仓。

## 4. 生成前端 payload

执行：

```powershell
python render_lightweight_visualization.py
```

会生成：

```text
backtest_output/lightweight_viewer.html
backtest_output/current_payload.js
backtest_output/official_equity_reconstructed.csv
```

打开：

```text
backtest_output/lightweight_viewer.html
```

如果页面提示没有加载数据，可以用：

```text
backtest_output/lightweight_viewer.html?data=current_payload.js
```

## 5. 保存回测版本

可选执行：

```powershell
python record_backtest_version.py
```

它会创建：

```text
backtest_versions/<timestamp>/
```

并复制当次代码、输出、metadata 和 payload，方便以后对比不同回测版本。

## 6. 把自己的结果接到 GitHub Pages

假设你生成了：

```text
offline_system/backtest_output/current_payload.js
```

可以复制到仓库示例目录：

```powershell
New-Item -ItemType Directory -Force ..\examples\my-run
Copy-Item .\backtest_output\current_payload.js ..\examples\my-run\payload.js
```

然后在仓库根目录打开：

```text
index.html?data=examples/my-run/payload.js
```

如果已经启用 GitHub Pages，访问：

```text
https://<your-user>.github.io/<repo>/index.html?data=examples/my-run/payload.js
```

## 常见问题

### 1. `Please set GM_TOKEN before running this script.`

说明没有设置环境变量。执行：

```powershell
$env:GM_TOKEN="your_gm_token_here"
```

### 2. 页面空白或提示没有数据

确认 payload 文件是否加载成功。推荐使用静态服务器：

```powershell
python -m http.server 8000
```

然后访问：

```text
http://localhost:8000/index.html?data=examples/20260621-032219/payload.js
```

### 3. 官方收益和离线复算收益不完全一致

这是正常现象。官方指标以掘金回测结果为准；离线复算主要用于补充图表和交互展示，成交价格、复权、撮合细节可能和官方引擎存在差异。

### 4. 可以换成股票而不是 ETF 吗？

可以。前端不限制资产类型。只要 payload 中提供 K 线、成交、收益曲线和回撤数据，股票、ETF、指数、期货都可以展示。
