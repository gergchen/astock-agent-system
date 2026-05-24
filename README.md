# 魔兽 — A股多智能体交易系统

基于 LLM 多 Agent 协作的 A 股全自动交易系统。覆盖盘前分析 → 盘中监控 → 信号生成 → 风控审批 → 交易执行 → 盘后复盘全链路，通过飞书推送消息，用自然语言交互。

---

## 使用步骤

### 第一步：配置环境

在 `魔兽/.env` 中填入以下凭证：

```ini
# LLM API（选择 DeepSeek 或 Anthropic）
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=sk-your-key-here

# 飞书应用凭证（用于 Bot 收发消息 + 推送通知）
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
FEISHU_CHAT_ID=oc_xxxxxxxxxxxx        # 推送目标群 ID
```

> 如果只有 Webhook（无 Bot 凭证），可只配 `FEISHU_WEBHOOK_URL`，但 Bot 的交互式回复功能不可用。

### 第二步：安装依赖

```bash
cd 魔兽

# 安装项目自身（推荐可编辑模式）
pip install -e .
```

### 第三步：启动服务

```bash
# 一键启动飞书全栈服务（推荐）
python -m managed_agents.main feishu
```

启动后系统会自动运行：
- **飞书 Bot 24h 在线** — 随时在群里发消息问行情，Bot 自动回复
- **交易日 09:00~15:05** — 调度器 + 哨兵自动开启，盘后自动休眠

### 第四步：在飞书上接收推送

无需任何额外操作。只要配置正确，系统会在盘中自动推送：

---

## 功能总览

### 1. 盘前简报 — 每个交易日 09:00 推送

飞书群中收到一条汇总消息，包含：

```
📊 昨日复盘           — 持仓回顾、盈亏总结
🌙 外围市场 & 盘前简报 — 美股/A50/港股期货表现
🔥 今日题材           — TOP5 热点板块
📈 机会板块           — 置信度达标的可买入板块
📝 交易策略           — LLM 基于热点生成的策略建议
💼 仓位规划           — 今日仓位目标、行业配置
```

### 2. 盘中机会推送 — 每 5 分钟自动扫描

当系统扫描到强势板块（≥3 只涨停/大涨股）时，立即推送：

```
📈 机会板块:
  🟢 算力 置信度60% (4只涨停)
  🟢 PCB 置信度55% (3只涨停)
```

触发自动链路：推送 → 风控审查 → 交易员执行（如已配置）。

### 3. 哨兵盯盘 — 盘中实时异动预警

每 120 秒扫描一次，发现以下异动立即推送：

| 异动类型 | 告警级别 |
|---------|---------|
| 大盘跳水（上证/深成指/创业板/科创50/沪深300）≥2% | 🔴 紧急 |
| 大盘跌幅 ≥1.5%（上证） | 🟡 关注 |
| 北向资金快速流入/流出 ≥20 亿 | 🟡 关注 |
| 北向累计流入/流出 ≥50 亿 | 🔴 紧急 |
| 快讯含"突发/紧急/暴涨/暴跌/熔断"关键词 | 🔴 紧急 |

### 4. 飞书 Bot 交互 — 随时发消息问行情

在飞书群中发消息，Bot 自动回复，回复基于实时数据：

```
用户: 今天什么板块最强？
 Bot: 目前热点前5：
     • 算力(8只涨停) 半导体(5只涨停) PCB(4只涨停)
     北向资金: 沪股通+12.3亿 深股通+8.7亿 合计+21.0亿

用户: 帮我分析一下 600519
 Bot: [输出实时行情 + 技术指标 + 板块对比分析...]

用户: 在吗 / 好的 / 谢谢
 Bot: [简短回复，不啰嗦]
```

### 5. Agent 决策链路（盘前 → 盘中 → 盘后）

```
09:00 ─ 盘前
  Morning Analyst     → 生成盘前简报（外围市场/重磅消息/热点预判）
  Researcher Trader   → 扫描题材 + 生成买入信号
  Portfolio Manager   → 制定仓位计划

09:30~15:00 ─ 盘中（每5分钟）
  Researcher Trader   → 扫描热点 + 生成信号
  ↓ 有合格信号
  Risk Officer        → 风控审查
  ↓ 审批通过
  Day Trader          → 执行交易

15:00~16:00 ─ 盘后
  Portfolio Manager   → 复盘总结（次日盘前推送）
```

### 6. 消息总线（Agent 间通信）

Agent 之间通过文件消息总线交换数据，方便调试和审计：

| 频道 | 数据流向 | 用途 |
|------|---------|------|
| `from_researcher` | 研究员 → 风控官 | 交易信号 |
| `from_risk_officer` | 风控官 → 交易员 | 审批结果 |
| `from_trader` | 交易员 → 所有人 | 执行结果 |
| `portfolio_plan` | 操盘手 → 研究员 | 仓位计划 |
| `alerts` | 任何人 → 用户 | 告警 |

### 7. 回测系统

**Agent 决策链回测** — 在历史数据上重放完整 Agent 决策过程，评估信号质量：

```bash
# 单日回测
python -m managed_agents.main backtest run --date 2026-05-15

# 自定义股票池
python -m managed_agents.main backtest run --date 2026-05-15 --pool 600519 000858 300750

# 批量回测（多日）
python -m managed_agents.main backtest batch --start 2026-05-10 --end 2026-05-15
```

**传统策略回测** — 6 种内置策略，确定性回测（无 LLM 依赖）：

```bash
python -m astock_trade.cli backtest run 600519 --strategy ma_crossover --cash 100000
python -m astock_trade.cli backtest compare 600519
python -m astock_trade.cli backtest batch 600519 000858 002230 --strategy triple_filter
```

### 8. 风控规则

| 规则 | 类型 | 触发动作 |
|------|------|---------|
| ST/*ST 股票 | 硬限制 | 拒绝交易 |
| 单只持仓 > 总资产 20% | 硬限制 | 拒绝交易 |
| 总仓位 > 70% | 硬限制 | 拒绝交易 |
| 日内回撤 > 5% | 硬限制 | 停止所有交易 |
| 连续止损 3 次 | 硬限制 | 暂停交易 30 分钟 |
| 单笔交易 > 总资产 10% | 软限制 | 警告 |
| 累计亏损 > 15% | 熔断 | 暂停交易 30 分钟 |

---

## CLI 命令速查

### 启动服务
```bash
python -m managed_agents.main feishu               # 飞书全栈（推荐）
python -m managed_agents.main sentinel --interval 120  # 仅哨兵
```

### 单次执行
```bash
python -m managed_agents.main researcher analyze 600519   # 个股分析
python -m managed_agents.main strategist briefing          # 生成早报
python -m managed_agents.main strategist review            # 收盘复盘
```

### 数据查询
```bash
python -m astock_data.cli signal hotspot --sectors   # 热点板块
python -m astock_data.cli signal northbound           # 北向资金
python -m astock_data.cli news flash -n 10            # 最新快讯
python -m astock_trade.cli status                     # 系统状态
python -m astock_trade.cli status --health            # 健康检查
python -m astock_trade.cli journal query --start 2026-05-22 --end 2026-05-22  # 交易记录
```

### Session 管理（长时间运行任务）
```bash
python -m managed_agents.main session create researcher "分析贵州茅台"   # 创建
python -m managed_agents.main session run <id>                          # 执行
python -m managed_agents.main session list                              # 列表
python -m managed_agents.main session status <id>                       # 状态
python -m managed_agents.main session resume <id> "继续分析"             # 恢复
```

---

## 项目结构

```
魔兽/
├── managed_agents/                  # Agent 系统
│   ├── main.py                      # CLI 入口 + 飞书全栈启动
│   ├── config.py                    # 全局配置
│   ├── agents/
│   │   ├── base.py                  # Agent 基类
│   │   ├── registry.py              # 注册中心（单例）
│   │   └── roles/
│   │       ├── sentinel.py          # 哨兵 — 实时盯盘异动预警
│   │       ├── morning_analyst.py   # 盘前分析师 — 生成晨报
│   │       ├── researcher_trader.py # 量化研究员 — 扫描 + 信号生成
│   │       ├── risk_officer.py      # 风控官 — 交易审批
│   │       ├── day_trader.py        # 交易员 — 下单执行
│   │       └── portfolio_manager.py # 操盘手 — 仓位管理 + 复盘
│   ├── orchestra/
│   │   ├── scheduler.py             # 交易时段调度器
│   │   └── coordinator.py           # Agent 工作流编排
│   ├── utils/
│   │   ├── notifier.py              # 飞书通知引擎
│   │   └── feishu_bot.py            # 飞书 SDK 长连接 Bot
│   ├── api/client.py                # LLM API 客户端
│   ├── backtest/                    # Agent 决策链回测
│   └── sessions/                    # Session 管理
│
├── astock_trade/                    # 交易核心库
│   ├── config.py / bus.py           # 配置 / 文件消息总线
│   ├── skills/
│   │   ├── market_monitor.py        # 盘中扫描
│   │   ├── morning_scan.py          # 盘前扫描
│   │   ├── signal_generator.py      # 信号生成
│   │   ├── postmarket_recap.py      # 盘后复盘
│   │   └── risk_assessor.py         # 风控评估
│   ├── risk_engine.py               # 风控引擎
│   ├── broker/                      # 券商接口（Mock / 同花顺）
│   └── backtest/                    # 传统策略回测
│
├── astock_data/                     # 数据源（行情/热点/北向/快讯/研报/公告）
└── .env                             # 环境变量配置
```

---

## 常见问题

**Q: 如何判断系统是否在运行？**
A: 控制台输出 `飞书全栈服务运行中` + 飞书群收到 `调度器上线` 通知。

**Q: 盘后系统在做什么？**
A: 15:05 后调度器和哨兵自动停止，深度休眠到次日 09:00。飞书 Bot 仍在线可以回复消息。

**Q: 为什么盘中没收到推送？**
A: 可能原因：
- 当前没有符合条件的板块（需要 ≥3 只涨停/大涨股）
- 不是交易日
- 信号被过滤（置信度 <0.55 或板块为"其他"等无效分类）

**Q: 如何查看系统日志？**
A: 所有通知同时写入 `data/alerts/alert.log` 审计文件，Agent 日志由 `logging_setup.py` 配置。

---

> **免责声明**: 本项目为量化交易研究和辅助决策工具，不构成投资建议。所有交易决策需用户自行判断。
