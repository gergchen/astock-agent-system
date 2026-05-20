# A股多Agent交易系统 | A-Stock Multi-Agent Trading System

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

全栈自动化 A 股交易平台 — 哨兵盯盘 + 回测引擎 + 确定性风控 + 多Agent编排。
Full-stack automated A-share trading platform — sentinel monitoring, backtesting engine, deterministic risk control, multi-agent orchestration.

---

## 架构 | Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent Layer (managed_agents)                                     │
│  sentinel(哨兵) → researcher(研究员) → risk-officer(风控官)       │
│  → day-trader(交易员) → portfolio-manager(操盘手)                 │
│  coordinator(编排器, 指数退避重试) / scheduler(时段调度)           │
│  notifier(推送) / api(FastAPI 多租户)                              │
├──────────────────────────────────────────────────────────────────┤
│  Trading Layer (astock_trade)                                     │
│  risk_engine(熔断/硬限制/软限制+审计) / signal_bus(SQLite WAL)    │
│  backtest(滑点/佣金/基准/6种策略) / monitor(7子系统健康检查)      │
├──────────────────────────────────────────────────────────────────┤
│  Data Layer (astock_data)                                         │
│  mootdx + 腾讯 + akshare + 同花顺 + 财联社                       │
│  行情/热点/北向/研报/快讯/公告/财务                               │
└──────────────────────────────────────────────────────────────────┘
```

## 快速开始 | Quick Start

```bash
# 安装 | Install
pip install -r requirements.txt
pip install -e .

# 系统状态 | System status
python -m astock_trade.cli status
python -m astock_trade.cli status --health     # 7个子系统健康检查

# 数据工具 | Data tools
python -m astock_data.cli signal hotspot --sectors    # 热点板块
python -m astock_data.cli signal northbound            # 北向资金
python -m astock_data.cli news flash -n 10             # 最新快讯

# 回测 | Backtesting
python -m astock_trade.cli backtest run 600519 -s ma_crossover --cash 100000
python -m astock_trade.cli backtest run 600519 -s ma_crossover --benchmark 000300
python -m astock_trade.cli backtest compare 600519    # 多策略对比
python -m astock_trade.cli backtest batch 600519 002230 -s triple_filter

# 哨兵盯盘 | Sentinel monitoring
python -m managed_agents.main sentinel --interval 60
```

## CLI 界面 | CLI Interface

所有命令支持 `--json` / `-j` 参数输出机器可读格式。
All commands support `--json` / `-j` for machine-readable output.

**状态仪表盘 | Status Dashboard**
```bash
python -m astock_trade.cli status -H
```
彩色双栏布局：左侧系统概览（密钥/策略/自选股），右侧运行状态（健康检查/告警）。
Two-column color layout: left panel (overview), right panel (health checks + alerts).

**回测报告 | Backtest Report**
```bash
python -m astock_trade.cli backtest run 600519 -s triple_filter --benchmark 000300
```
彩色面板：绿色正值/红色负值/黄色回撤，含基准对比（Alpha/Beta/IR）。
Color-coded panel: green for gains, red for losses, yellow for drawdowns, benchmark comparison included.

**交易记录 | Trade Journal**
```bash
python -m astock_trade.cli journal query --start 2026-05-01 --end 2026-05-15
```
表格输出：盈亏列自动颜色编码（绿盈红亏）。
Table output with auto-colored P&L column.

## 回测引擎 | Backtest Engine

确定性回测 — 相同输入永远产生相同输出，无 LLM 依赖。
Deterministic — same input always produces same output, no LLM dependency.

| 特性 | Feature | 说明 | Description |
|------|---------|------|-------------|
| 滑点模型 | Slippage | Tick滑点(A股0.01)、固定BPS、成交量冲击 | Tick, fixed BPS, volume impact |
| 佣金模型 | Commission | ASHARE真实费率: 印花税+过户费+券商佣金 | Stamp duty + transfer + brokerage |
| 基准对比 | Benchmark | 沪深300/中证500 — Alpha/Beta/IR/捕获比 | CSI300/500 — Alpha/Beta/IR |
| 绩效指标 | Metrics | 总收益/年化/夏普/回撤/胜率/盈亏比 | Return/Sharpe/Drawdown/Win rate |
| 多策略对比 | Comparison | 单标的运行多策略横向比较 | Cross-strategy comparison |

### 内置策略 | Built-in Strategies

| 策略 | Strategy | 说明 | Description |
|------|----------|------|-------------|
| `ma_crossover` | MA Crossover | MA5/20 金叉死叉 | Golden/death cross |
| `ma_crossover_volume` | MA + Volume | MA交叉+放量确认 | With volume confirmation |
| `ma_crossover_trend` | MA + Trend | MA交叉+趋势过滤 | With trend filter |
| `triple_filter` | Triple Filter | 金叉+趋势+RSI+量 | Golden cross + trend + RSI + volume |
| `price_breakout` | Price Breakout | 突破N日高低点 | N-day high/low breakout |
| `buy_and_hold` | Buy & Hold | 买入持有（基准） | Baseline strategy |

## 风控引擎 | Risk Engine

确定性风控 — 无LLM依赖，全部可审计。
Deterministic risk — no LLM dependency, fully auditable.

| 规则 | Rule | 硬限制 | 软限制 | 触发 |
|------|------|--------|--------|------|
| ST股票 | ST stocks | ✓ | — | REJECT |
| 单只持仓>20% | Single position >20% | ✓ | — | REJECT |
| 总仓位>70% | Total exposure >70% | ✓ | — | REJECT |
| 日内回撤>5% | Daily drawdown >5% | ✓ | — | REJECT |
| 连续亏损>3次 | Consecutive losses >3 | ✓ | — | REJECT |
| 单笔订单>10% | Single order >10% | — | ✓ | WARN |
| 置信度<0.3 | Confidence <0.3 | — | ✓ | WARN |
| 累计亏损>15% | Accumulated loss >15% | 熔断 | — | 暂停30min |

## API 服务器 | API Server

FastAPI 多租户 HTTP API，启动：
FastAPI multi-tenant HTTP API, start with:

```bash
python -m managed_agents.api.server
```

| 端点 | Endpoint | 说明 | Description |
|------|----------|------|-------------|
| `GET /` | Root | 状态页 | Status page |
| `GET /api/v1/health` | Health | 健康检查 | Health check |
| `GET/POST /api/v1/tenants` | Tenants | 租户管理 | Tenant management |
| `GET /api/v1/agents` | Agents | Agent列表 | List agents |
| `POST /api/v1/sessions` | Sessions | 创建会话 | Create session |
| `WS /api/v1/ws/alerts` | Alerts | 实时告警 | Real-time alerts |
| `GET /docs` | Docs | Swagger文档 | Swagger docs |

## 部署 | Deployment

```bash
# 飞书全栈 | Feishu full-stack
python -m managed_agents.main feishu

# 哨兵盯盘 | Sentinel monitoring (60s间隔)
python -m managed_agents.main sentinel --interval 60

# Agent决策链回测 | Agent decision chain backtest
python -m managed_agents.main backtest run -d 2026-05-08 -p 688017 600519 300750
```

### 定时任务 | Scheduled Tasks

| 时间 | Time | 任务 | Task |
|------|------|------|------|
| 09:02 | Morning | 盘前扫描 | Pre-market scan |
| 09:37 | Session 1 | 盘中首扫 | First intraday scan |
| 13:05 | Session 2 | 午后异动 | Afternoon monitoring |
| 14:52 | Close | 尾盘提醒 | Pre-close check |
| 15:10 | Review | 盘后复盘 | Post-market review |

## 配置 | Configuration

环境变量 | Environment variables:

| 变量 | Variable | 说明 | Description |
|------|----------|------|-------------|
| `ATRADE_LOG_LEVEL` | Log Level | 日志级别 (`DEBUG`/`INFO`) |
| `ANTHROPIC_BASE_URL` | LLM URL | LLM API地址 |
| `ANTHROPIC_AUTH_TOKEN` | LLM Key | LLM API Key |
| `FEISHU_WEBHOOK_URL` | Webhook | 飞书通知URL |
| `AGENT_SENTINEL_INTERVAL` | Scan Interval | 哨兵扫描间隔(秒) |

## 文件结构 | File Structure

```
astock_trade/               # 交易核心 | Trading core
├── cli.py                  # CLI入口 + rich UI输出 | CLI with rich UI
├── config.py               # 统一配置中心 | Unified config
├── monitor.py              # 健康检查(7子系统) | Health monitor
├── risk_engine.py          # 确定性风控 | Risk engine
├── signal_bus.py           # 消息总线 | Signal bus
├── utils/
│   ├── cli_ui.py           # rich UI组件库 | UI components ← NEW
│   ├── logging_setup.py    # 日志配置 | Logging
│   └── alerting.py         # 告警路由 | Alerting
├── backtest/               # 回测引擎 | Backtest engine
│   ├── engine.py           # 回测引擎 | Engine
│   ├── models.py           # 滑点/佣金模型 | Slippage/commission
│   ├── benchmark.py        # 基准对比 | Benchmark
│   ├── metrics.py          # 绩效指标 | Performance metrics
│   ├── strategies.py       # 6种内置策略 | 6 built-in strategies
│   └── strategy_registry.py# 策略注册表 | Registry
├── broker/                 # 券商对接 | Broker integration
├── skills/                 # Agent技能 | Agent skills
└── ...

managed_agents/             # Agent编排 | Agent orchestration
├── main.py                 # 主入口 | Main entry
├── api/
│   ├── server.py           # FastAPI服务 + CORS | API server
│   └── adapter.py          # 模型适配 | Model adapter
├── agents/roles/           # 角色Agent | Role agents
├── orchestra/              # 编排器 | Orchestrator
└── backtest/               # Agent决策链回测 | Agent decision backtest

astock_data/                # 数据源 | Data sources
├── core/                   # 数据源管理/缓存 | DataSource manager/cache
├── market/                 # 行情接口 | Market data APIs
└── ...
```

## License

Apache License 2.0
