# astock-agent-system

A股多Agent智能投研系统 — 哨兵盯盘 + 飞书机器人 + 盘前/盘中/盘后全流程自动化。

## 架构

```
A股多Agent系统
├── 哨兵 (Sentinel)        实时盯盘，交易时段异动秒级预警
├── 研究员 (Researcher)     盘前扫描 / 盘中监控 / 信号生成
├── 策略师 (Strategist)     盘后复盘 / 盘前简报
├── 风控官 (Risk Officer)   交易前风控校验 / 仓位管理 / 回撤控制
├── 交易员 (Day Trader)     订单执行 / 持仓追踪 / 交易日志
├── 操盘手 (Portfolio Mgr)  仓位管理 / 组合优化 / 多策略协调
└── 协调器 (Coordinator)   多Agent工作流编排

数据层
├── 行情层   mootdx + 腾讯财经        K线 / 盘口 / PE/PB/市值
├── 信号层   同花顺热点 + 北向资金      强势股 / 题材归因 / 北向分钟流向
├── 研报层   东财 + iwencai           研报列表 / 一致预期
├── 新闻层   akshare + 财联社         个股新闻 / 快讯 / 国际资讯
├── 基础数据  mootdx 财务/F10         季报 / 公司资料
└── 公告层   巨潮资讯                  全量公告检索
```

## 快速开始

```bash
# 安装
pip install -r requirements.txt
pip install -e .

# 飞书全栈（bot + 哨兵 + 调度器）
python -m managed_agents.main feishu

# 哨兵盯盘
python -m managed_agents.main sentinel --interval 120
```

## Agent 决策链回测

```bash
# 单日回测
python -m managed_agents.main backtest run -d 2026-05-08 -p 688017 600519 300750

# 批量回测
python -m managed_agents.main backtest batch -s 2026-05-05 -e 2026-05-12 -m 2.0 -o report.json

# 查看报告
python -m managed_agents.main backtest report report.json
```

回测链路：历史K线 → 热点推导 → 信号生成 → 风控过滤 → 前向收益验证 → 归因报告

## 数据工具

| 场景 | 命令 |
|------|------|
| 今日热点 | `astock signal hotspot` |
| 北向资金 | `astock signal northbound` |
| 快讯 | `astock news flash -n 10` |
| 实时估值 | `astock market valuation 600519` |
| 研报 | `astock research reports 688017` |
| 季报 | `astock fund finance 688017` |
| 公告 | `astock ann list 600519` |
| 策略回测 | `astock-trade backtest run 600519 --strategy ma_crossover` |

## 定时任务

| 时间 | 任务 |
|------|------|
| 09:02 | 盘前扫描（隔夜消息+外围+热点+北向） |
| 09:37 | 盘中首扫 |
| 13:05 | 下午扫描 |
| 14:52 | 尾盘提醒 |
| 15:10 | 盘后复盘 |

## License

Apache License 2.0
