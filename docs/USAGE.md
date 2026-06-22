# 使用教程

这份教程从“只看示例页面”讲到“接入自己的掘金回测结果”。

## 方式一：只查看示例页面

适合想先看效果的人。

### 1. 下载仓库

可以用 Git：

```bash
git clone https://github.com/yingy-buxing/dc-quant-visualizer.git
cd dc-quant-visualizer
```

也可以在 GitHub 页面点击 `Code -> Download ZIP`，解压后打开目录。

### 2. 打开页面

直接打开：

```text
index.html
```

默认会加载：

```text
examples/20260621-032219/payload.js
```

页面需要联网，因为图表库来自 Lightweight Charts CDN。

### 3. 如果本地文件打不开

用静态服务器启动：

```bash
python -m http.server 8000
```

然后访问：

```text
http://localhost:8000/
```

## 方式二：启用 GitHub Pages

适合把项目展示给别人。

### 1. 打开仓库设置

进入 GitHub 仓库页面：

```text
Settings -> Pages
```

### 2. 设置发布方式

选择：

```text
Source: Deploy from a branch
Branch: main
Folder: /root
```

点击保存。

### 3. 等待部署完成

GitHub 会生成类似这样的访问地址：

```text
https://yingy-buxing.github.io/dc-quant-visualizer/
```

以后只要推送到 `main` 分支，GitHub Pages 会自动更新页面。

## 方式三：接入自己的掘金回测结果

适合想把自己的策略回测变成可交互页面的人。

### 1. 准备 Python 和掘金 SDK

安装依赖：

```powershell
pip install gm
```

如果你已经在掘金量化终端或自己的虚拟环境里装好了 `gm`，可以直接使用那个环境。

### 2. 设置 token

不要把 token 写进代码。运行前设置环境变量：

```powershell
$env:GM_TOKEN="your_gm_token_here"
```

### 3. 进入离线系统目录

```powershell
Set-Location offline_system
```

### 4. 跑官方回测

```powershell
python trace_strategy.py
```

它会调用掘金 `run(...)`，并在 `backtest_output/` 下生成：

```text
official_signals.csv
official_orders.csv
official_executions.csv
official_indicator.csv
```

其中：

- `official_indicator.csv` 是官方收益、年化、夏普、回撤等指标
- `official_executions.csv` 是官方成交明细
- `official_signals.csv` 是策略信号和目标仓位
- `official_orders.csv` 是订单流水

### 5. 导出行情和辅助数据

```powershell
python export_multi_etf_data.py
```

它会生成：

```text
etf_bars.csv
bars_equity.csv
trades.csv
```

这些文件用来补齐 K 线、成交点、成交量和组合曲线。

### 6. 生成前端数据

```powershell
python render_lightweight_visualization.py
```

它会生成：

```text
backtest_output/lightweight_viewer.html
backtest_output/current_payload.js
backtest_output/official_equity_reconstructed.csv
```

打开：

```text
backtest_output/lightweight_viewer.html
```

或者：

```text
backtest_output/lightweight_viewer.html?data=current_payload.js
```

### 7. 放进 GitHub Pages 示例目录

假设你的版本叫 `my-run`：

```powershell
Set-Location ..
New-Item -ItemType Directory -Force .\examples\my-run
Copy-Item .\offline_system\backtest_output\current_payload.js .\examples\my-run\payload.js
```

然后本地打开：

```text
index.html?data=examples/my-run/payload.js
```

推送到 GitHub 后，也可以访问：

```text
https://<your-user>.github.io/<repo>/index.html?data=examples/my-run/payload.js
```

## 如何换成自己的策略

最小改动方式：

1. 修改 `offline_system/etf_strategy_core.py` 的选股、择时和仓位逻辑。
2. 如果需要改订阅标的，修改其中的 `SYMBOL_INFO`。
3. 保持 `calculate_targets(...)` 返回目标仓位。
4. 重新跑：

```powershell
python trace_strategy.py
python export_multi_etf_data.py
python render_lightweight_visualization.py
```

更灵活的方式：

- 保留前端 `index.html`
- 自己生成符合格式的 `payload.js`
- 用 `?data=...` 加载自己的 payload

## Payload 最小结构

页面读取：

```js
window.BACKTEST_PAYLOAD = {
  summary: {},
  symbols: [],
  symbol_names: {},
  charts: {},
  equity: [],
  drawdown: [],
  trades: [],
  contribution: []
};
```

如果你不用掘金，也可以从其他回测框架导出这些字段。

## 安全注意事项

- 不要提交真实 token
- 不要提交 `.env`
- 不要提交 `gmcache`
- 不要提交巨大的 `backtest_output`
- 可以提交脱敏后的 `payload.js` 作为 demo 数据

## 常见问题

### 为什么 GitHub 上只能看到代码，看不到网页？

需要开启 GitHub Pages。步骤见“方式二”。

### 为什么页面打开后没有图？

常见原因：

- 没联网，导致 Lightweight Charts CDN 加载失败
- `payload.js` 路径不对
- 浏览器限制本地文件脚本加载

推荐用：

```bash
python -m http.server 8000
```

### 为什么官方收益和离线复算收益不一致？

官方收益以掘金回测引擎为准。离线复算用于图表展示和辅助分析，可能因为复权、撮合、成交价、手续费细节与官方不同而有差异。

### 这个项目只能展示 ETF 吗？

不是。示例数据是 ETF，但前端是通用交易回测可视化。股票、ETF、指数、期货都可以，只要数据格式满足 payload 要求。
