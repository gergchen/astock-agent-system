# a-stock-data

A 股全栈数据工具包 — 6 层架构 · 15 个端点 · 7 个数据源

一个结构化 Python 包，把分散在 7 个数据源里的 A 股原始数据整合成 CLI 工具集 + Claude Code Skill。

> 上游灵感：[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) (Apache 2.0)
>
> 本仓库：独立 Python 包 + CLI + 缓存 + 测试，非单文件嵌入模式

## 架构

```
A 股全栈数据 · 六层架构
│
├── 行情层    mootdx + 腾讯财经       K 线 + 五档盘口 + PE/PB/市值/换手率
├── 信号层    同花顺热点 + 北向资金    当日强势股 + 题材归因 + 北向分钟流向
├── 研报层    东财 + akshare + iwencai 研报列表 / PDF下载 / 一致预期 / NL搜索
├── 新闻层    akshare × 3              个股新闻 / 财联社快讯 / 全球资讯
├── 基础数据  mootdx finance / F10     37字段季报 + 9类公司资料
└── 公告层    巨潮 cninfo + mootdx     沪深北京全量公告
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 CLI
pip install -e .

# 3. （可选）配置 API Keys
export IWENCAI_API_KEY="your_key_here"
export NEWSAPI_API_KEY="your_key_here"   # 国际新闻源，免费100次/天

# 4. 使用
astock market valuation 600519
astock signal hotspot
astock workflow valuate 688017
```

### 作为 Claude Code Skill

```bash
# 将 SKILL.md 放入 skills 目录
mkdir -p ~/.claude/skills/a-stock-data
cp .claude/skills/astock_data/SKILL.md ~/.claude/skills/a-stock-data/

# 启动 Claude Code，说"查一下 688017 的估值"即可自动激活
```

## 使用示例

| 场景 | 命令 |
|------|------|
| 实时估值 | `astock market valuation 600519 000001` |
| K线数据 | `astock market kline 000001 -c day -n 20` |
| 今日热点 | `astock signal hotspot` |
| 热点题材排名 | `astock signal hotspot --sectors` |
| 北向资金 | `astock signal northbound --realtime` |
| 研报列表 | `astock research reports 688017` |
| 一致预期 | `astock research expectations 688017` |
| 语义搜索 | `astock research search "人形机器人 丝杠"` |
| 个股新闻 | `astock news stock 688017` |
| 财联社快讯 | `astock news flash` |
| 国际地缘新闻 | `astock news geopolitics "中东 伊朗"` |
| 国际头条 | `astock news headlines` |
| 基本面 | `astock fund basics 600519` |
| 季报数据 | `astock fund finance 688017` |
| 公司资料 | `astock fund f10 688017 -c "公司概况"` |
| 公告列表 | `astock ann list 600519` |
| 单票估值 | `astock workflow valuate 688017` |
| 批量对比 | `astock workflow compare 688017 300308 300476` |
| 主题研报 | `astock workflow thematic "人形机器人" "减速器"` |

## 估值框架

- **前向PE** = 当前股价 / 一致预期EPS
- **PEG** = 前向PE / (CAGR × 100)，PEG < 1 便宜
- **PE消化** = 当前PE消化到30x锚定需要多少年
- **30x锚点** = A 股成长股估值重力线

## 数据源

| 数据源 | 协议 | 封IP风险 | 状态 |
|--------|------|---------|------|
| mootdx | TCP (7709) | 极低 | 需直连 |
| 腾讯财经 | HTTP | 低 | ✅ |
| akshare | Python | 中 | ✅ |
| iwencai | OpenAPI | 低 (需Key) | 可选 |
| 同花顺热点 | HTTP | 极低 | ✅ |
| 同花顺 hsgtApi | HTTP | 极低 | ✅ |

## License

[Apache License 2.0](./LICENSE)
