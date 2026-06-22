# Offline Backtest Pipeline

这个目录放可公开的离线/本地回测辅助系统。它用于把掘金量化回测结果转换成前端可视化页面需要的 `payload.js`。

不包含内容：

- 掘金 token
- 本地缓存目录
- 参数搜索和机器训练脚本
- 大规模研究输出

## 文件说明

- `etf_strategy_core.py`: 多标的轮动策略核心逻辑
- `main.py`: 掘金官方 `run(...)` 回测入口
- `trace_strategy.py`: 带信号、订单、成交、指标落盘的官方回测入口
- `export_multi_etf_data.py`: 导出 K 线、成交和组合曲线所需 CSV
- `render_lightweight_visualization.py`: 将 CSV 转成前端 `current_payload.js` 和 `lightweight_viewer.html`
- `record_backtest_version.py`: 记录一个回测版本快照
- `analyze_loss_trades.py`: 亏损交易复盘辅助脚本

## 环境变量

脚本不内置 token。运行前需要在本机设置：

```powershell
$env:GM_TOKEN="your_gm_token_here"
```

也可以在系统环境变量里长期配置 `GM_TOKEN`。

## 基本流程

```powershell
Set-Location offline_system

# 1. 跑掘金官方回测并导出官方信号、订单、成交和指标
python trace_strategy.py

# 2. 基于官方输出和行情数据生成可视化所需 CSV
python export_multi_etf_data.py

# 3. 生成 Lightweight Charts 前端和 payload
python render_lightweight_visualization.py

# 4. 可选：记录一个回测版本
python record_backtest_version.py
```

默认输出目录是当前目录下的 `backtest_output/`。公开仓库 `.gitignore` 已排除该目录。

## 预览

生成后可以打开：

```text
backtest_output/lightweight_viewer.html
```

或者把生成的 payload 复制到仓库 `examples/<version>/payload.js`，用根目录 `index.html?data=...` 展示。
