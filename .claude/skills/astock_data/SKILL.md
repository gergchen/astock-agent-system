---
name: a-stock-data
description: A股全栈数据工具包 — 覆盖行情(mootdx+腾讯)、信号(同花顺热点+北向)、研报(东财+iwencai)、新闻(akshare)、基础数据(mootdx财务/F10)、公告(巨潮)六层数据源。适用于个股估值、研报检索、题材归因、产业链调研、批量筛选等场景。
origin: custom
version: 2.0
---

# A股全栈数据工具包 V2

六层数据架构，15 个端点，7 个数据源实测可用。

## When to Activate

- 用户要查 A 股个股估值（一致预期 / PE / PEG / PE消化）
- 用户要拉实时行情（价格 / 五档盘口 / K线 / 涨跌停价）
- 用户要搜研报（按主题 / 按标的 / 按行业 / 下载PDF）
- 用户要看**当日强势股 / 题材归因 / 概念热点**
- 用户要看**北向资金动向**（沪股通/深股通分钟流向）
- 用户要看新闻资讯（个股新闻 / 财联社快讯 / 全球资讯）
- 用户要查公告（巨潮公告全文）
- 用户要做产业链调研 / 批量横向对比
- 关键词：估值、一致预期、机构预测、市盈率、PEG、市值、研报、产业链、K线、盘口、公告、新闻、**强势股、题材、热点、概念归因、北向资金、沪股通、深股通**

## Prerequisites

```bash
pip install mootdx akshare requests pandas typer
```

iwencai 语义搜索需要 API Key（可选，其他数据源全部免费无 Key）：
```bash
export IWENCAI_API_KEY="your_key_here"
# 申请地址: https://www.iwencai.com/skillhub
```

## CLI Commands

所有命令输出 JSON（AI 友好模式）。加 `-o table` 可切换为人读表格。

### 行情层
```bash
# K线数据
python -m astock_data.cli market kline 688017 -c day -n 20
python -m astock_data.cli market kline 000001 -c 5m -n 100

# 实时报价（五档盘口）
python -m astock_data.cli market quote 688017 300476

# PE/PB/市值/换手率（腾讯财经）
python -m astock_data.cli market valuation 688017 600519
```

### 信号层
```bash
# 当日强势股 + 题材归因
python -m astock_data.cli signal hotspot
python -m astock_data.cli signal hotspot --sectors  # 只看题材热度排名

# 北向资金
python -m astock_data.cli signal northbound --realtime  # 分钟级流向
python -m astock_data.cli signal northbound --history --type 001  # 沪股通历史
```

### 研报层
```bash
python -m astock_data.cli research reports 688017
python -m astock_data.cli research expectations 688017
python -m astock_data.cli research search "人形机器人 丝杠" --channel report
```

### 新闻层
```bash
python -m astock_data.cli news stock 688017
python -m astock_data.cli news flash -n 20
python -m astock_data.cli news global
```

### 基础数据
```bash
python -m astock_data.cli fund finance 688017
python -m astock_data.cli fund f10 688017 -c "公司概况"
python -m astock_data.cli fund basics 688017
```

### 公告
```bash
python -m astock_data.cli ann list 688017
python -m astock_data.cli ann latest 688017
```

### 调研流程
```bash
# 单票完整估值（PE/PEG/消化年数）
python -m astock_data.cli workflow valuate 688017

# 批量对比
python -m astock_data.cli workflow compare 688017 300308 300476

# 主题研报检索
python -m astock_data.cli workflow thematic "人形机器人 丝杠" "减速器 国产"

# 新标的快速调研
python -m astock_data.cli workflow newstock 688017
```

## Architecture

```
行情层（实时，不封IP）
├── mootdx        → K线 + 五档盘口 + 逐笔成交 (TCP 7709)
└── 腾讯财经 API   → PE/PB/市值/换手率/涨跌停 (HTTP)

信号层（V2 新增）
├── 同花顺热点     → 当日强势股 + 题材归因 reason tags (零鉴权)
└── 同花顺北向     → hgt/sgt 分钟资金流向 + 历史日级 (hsgtApi)

研报层
├── 东财 reportapi → 研报列表 + PDF下载
├── 同花顺 THS     → 一致预期EPS (akshare封装)
└── iwencai        → NL语义搜索研报 (需Key)

新闻层
├── akshare → 个股新闻 (东财)
├── akshare → 财联社快讯
└── akshare → 东财全球资讯

基础数据层
├── mootdx finance → 季报快照 (37字段)
├── mootdx F10     → 公司资料 (9大类文本)
└── akshare        → 个股基本面

公告层
├── 巨潮 cninfo    → 公告全文 (akshare封装)
└── mootdx F10     → 最新公告摘要
```

## 估值框架

- **前向PE** = 当前股价 / 未来年度一致预期EPS
- **PEG** = 前向PE / (CAGR × 100)，PEG < 1 便宜，1-1.5 合理，> 1.5 贵
- **PE消化** = 当前PE消化到30x锚定需要多少年 (< 2年合理，> 4年太贵)
- **30x锚点** = A股成长股估值重力线，所有行业统一

## 数据源优先级

| 优先级 | 数据源 | 用途 | 封IP风险 |
|--------|--------|------|---------|
| 1 | mootdx (TCP) | K线+盘口+财务+F10 | 极低 |
| 2 | 腾讯财经 (HTTP) | PE/PB/市值 | 低 |
| 3 | akshare (Python) | 研报+新闻+公告 | 中(东财源) |
| 4 | iwencai (OpenAPI) | NL主题搜索 | 低(需Key) |
| 5 | 同花顺热点 (HTTP) | 强势股+题材归因 | 极低(零鉴权) |
| 6 | 同花顺 hsgtApi (HTTP) | 北向资金 | 极低(零鉴权) |
