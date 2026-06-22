# Trading Backtest Visualizer

一个基于 [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) 的交易回测可视化项目。

它适合展示股票、ETF、指数或其他有 K 线数据的交易策略回测结果。仓库包含一个可直接打开的前端页面、一个示例回测 payload，以及一套可公开的本地数据转换脚本。

## 你能看到什么

- K 线、成交量、买入点、卖出点
- 鼠标悬停查看每根 K 线的 OHLCV 信息
- 鼠标悬停成交点查看成交价格、方向、仓位和信号分数
- 官方组合收益曲线、回撤曲线和每日仓位
- 逐笔成交明细表，点击成交行可联动跳转图表
- 各标的收益贡献概览
- 支持通过 `?data=...` 加载不同回测版本的数据

## 在线展示

开启 GitHub Pages 后，访问：

```text
https://<your-github-user>.github.io/<repo-name>/
```

例如本仓库启用 Pages 后通常是：

```text
https://yingy-buxing.github.io/dc-quant-visualizer/
```

当前默认示例数据来自：

```text
examples/20260621-032219/payload.js
```

也可以显式指定数据文件：

```text
index.html?data=examples/20260621-032219/payload.js
```

## 本地预览

最简单的方式是直接双击打开 `index.html`。页面会从 CDN 加载 Lightweight Charts，所以需要联网。

如果浏览器限制本地脚本加载，使用静态服务器：

```bash
python -m http.server 8000
```

然后访问：

```text
http://localhost:8000/
```

## 示例截图

![20260621-032219 demo](docs/images/20260621-032219-full.png)

## 仓库结构

```text
.
├─ index.html                         # 可视化前端入口
├─ examples/
│  └─ 20260621-032219/
│     ├─ payload.js                   # 示例回测数据
│     ├─ metadata.json                # 示例版本摘要
│     └─ index.html                   # 示例跳转页
├─ docs/
│  ├─ USAGE.md                        # 完整使用教程
│  └─ images/
│     └─ 20260621-032219-full.png     # 展示截图
└─ offline_system/
   ├─ etf_strategy_core.py            # 示例策略核心
   ├─ main.py                         # 掘金官方回测入口
   ├─ trace_strategy.py               # 导出官方信号/订单/成交/指标
   ├─ export_multi_etf_data.py         # 导出可视化所需 CSV
   ├─ render_lightweight_visualization.py
   ├─ record_backtest_version.py
   └─ analyze_loss_trades.py
```

## 快速使用

如果你只想看前端效果：

1. 克隆或下载本仓库。
2. 打开 `index.html`。
3. 查看示例回测可视化页面。

如果你想接入自己的回测数据：

1. 按 `offline_system/README.md` 跑官方回测和导出脚本。
2. 生成 `backtest_output/current_payload.js`。
3. 将它复制到 `examples/<your-version>/payload.js`。
4. 用 `index.html?data=examples/<your-version>/payload.js` 打开。

完整教程见：[docs/USAGE.md](docs/USAGE.md)。

## 数据格式

页面读取全局变量：

```js
window.BACKTEST_PAYLOAD = { ... };
```

核心字段：

- `summary`: 官方回测指标
- `symbols`: 可选标的列表
- `symbol_names`: 标的名称映射
- `charts`: 各标的 K 线、成交量、买卖点
- `equity`: 组合收益曲线和每日仓位
- `drawdown`: 回撤曲线
- `trades`: 官方成交明细
- `contribution`: 各标的收益贡献

## 离线回测与数据转换

可公开的本地回测辅助脚本放在 `offline_system/`。

运行前设置掘金 token：

```powershell
$env:GM_TOKEN="your_gm_token_here"
```

然后进入目录执行：

```powershell
Set-Location offline_system
python trace_strategy.py
python export_multi_etf_data.py
python render_lightweight_visualization.py
```

详细说明见：[offline_system/README.md](offline_system/README.md)。

## 不包含内容

- 掘金量化真实 token
- 机器训练和参数搜索脚本
- 本地缓存目录
- 原始大规模研究输出
- 个人环境配置

## License

MIT
