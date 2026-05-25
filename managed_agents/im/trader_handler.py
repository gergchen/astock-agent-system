"""交易员消息处理器 — 从 run_feishu_bot() 提取的独立模块。

负责：
- 消息路由（交易员 / Claude / 私聊）
- 对话历史管理
- 数据上下文构建
- MemoryStore 长期记忆集成
"""

import json as _json
import logging
import re
import subprocess
import time
from datetime import datetime, time as dt_time
from pathlib import Path

from ..api.client import APIClient
from ..config import get_config
from ..memory.memory_store import MemoryStore

logger = logging.getLogger(__name__)

CLAUDE_CLI = [
    "node",
    str(Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli-wrapper.cjs"),
]

ASTOCK = "python -X utf8 -m astock_data.cli"
CODE_RE = re.compile(r'(?<!\d)([036]\d{5})(?!\d)')


class TraderHandler:
    """交易员消息处理器 — 路由、上下文、历史、记忆。"""

    def __init__(self, llm: APIClient):
        self.llm = llm
        self.config = get_config()
        # 对话历史: chat_id -> [{"role": "user"/"assistant", "content": str}, ...]
        self._trader_history: dict[str, list[dict]] = {}
        self._MAX_HISTORY_EXCHANGES = 10
        self._last_reply: dict[str, tuple[str, float]] = {}
        self._OUTPUT_DEDUP_WINDOW = 30.0

    # ── 工具方法 ──

    @staticmethod
    def _extract_codes(text: str) -> list[str]:
        codes = CODE_RE.findall(text)
        return list(dict.fromkeys(codes))[:8]

    @staticmethod
    def _needs_claude(text: str) -> bool:
        t = text.lower()
        keywords = [
            "claude", "修复", "改代码", "改bug", "查bug", "修bug",
            "开发", "部署", "配置", "安装", "升级",
            "不对", "错了", "不准", "坏了", "挂了",
            "怎么用", "怎么改", "帮我写", "帮我改",
            "git", "commit", "push", "分支",
        ]
        return any(kw in t for kw in keywords)

    @staticmethod
    def _is_private_chat(chat_id: str) -> bool:
        return chat_id.startswith("ou_")

    @staticmethod
    def _run(cmd: str, timeout: int = 90) -> str:
        """执行 CLI 命令，返回易读的文字输出（最大 4000 字符）。"""
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            out = (r.stdout or "").strip()
            if not out:
                out = (r.stderr or "").strip()
            if not out:
                return "(空)"
            if out.startswith("{"):
                try:
                    parsed = _json.loads(out)
                    d = parsed.get("data", parsed)
                except _json.JSONDecodeError:
                    return out[:4000]

                if isinstance(d, dict) and "stocks" in d:
                    lines = [f"技术分析: {d['success']}/{d['total']} 只, 耗时 {d.get('elapsed_seconds','?')}s"]
                    for code in d.get("stocks", {}):
                        s = d["stocks"][code]
                        if "error" in s:
                            lines.append(f"  {code}: {s['error']}")
                            continue
                        ind = s.get("indicators", {})
                        sigs = s.get("indicator_signals", {})
                        buy = sigs.get("buy_signals", [])
                        sell = sigs.get("sell_signals", [])
                        pdi, mdi = ind.get("pdi", 0), ind.get("mdi", 0)
                        trend = "↑多头" if pdi > mdi else "↓空头" if mdi > pdi else "→盘整"
                        sig_str = ""
                        if buy: sig_str += f"买入({len(buy)})"
                        if sell: sig_str += f"卖出({len(sell)})"
                        info = f"{trend} ADX={ind.get('adx',0):.0f} MACD={ind.get('macdh',0):+.1f} RSI={ind.get('rsi',0):.0f} CCI={ind.get('cci',0):.0f} MA10={ind.get('ma10',0):.0f} MA50={ind.get('ma50',0):.0f}"
                        if sig_str: info += f" {sig_str}"
                        pat = s.get("pattern_details", {})
                        if pat:
                            info += " 形态:" + ",".join(f"{v['name_cn']}{v['signal']}" for v in pat.values())
                        lines.append(f"  {code} {info}")
                    return "\n".join(lines[:20])

                if isinstance(d, list):
                    rows = []
                    for item in d[:15]:
                        if isinstance(item, dict):
                            rows.append("  " + " | ".join(f"{v}" for k, v in item.items() if not k.startswith("_")))
                        else:
                            rows.append(f"  {item}")
                    return "\n".join(rows) if rows else "(空)"

                if isinstance(d, dict):
                    rows = []
                    for k, v in d.items():
                        if isinstance(v, (str, int, float, bool)):
                            rows.append(f"  {k}={v}")
                        elif isinstance(v, dict):
                            inner = " ".join(f"{kk}={vv}" for kk, vv in v.items() if isinstance(vv, (str, int, float)))
                            if inner:
                                rows.append(f"  {k}: {inner}")
                        elif isinstance(v, list) and len(v) < 20:
                            rows.append(f"  {k}: {len(v)}项")
                    return "\n".join(rows[:25])

                return str(d)[:2000]

            return out[:4000]
        except subprocess.TimeoutExpired:
            return f"[超时 {timeout}s]"
        except Exception as e:
            return f"[错误] {e}"

    # ── 数据上下文 ──

    def _build_data_context(self, user_text: str) -> str:
        """根据用户问题获取相关数据上下文。"""
        t = user_text.lower()
        codes = self._extract_codes(user_text)
        blocks = []
        now_str = datetime.now().strftime("%H:%M")

        needs_market = any(kw in t for kw in ["大盘","指数","行情","今天","盘面","市场","走势"])
        needs_hotspot = any(kw in t for kw in ["热点","板块","资金","涨跌","涨停","题材"])
        needs_ta = bool(codes) or any(kw in t for kw in ["技术","指标","分析","怎么看","能不能买","走势","趋势"])
        needs_news = any(kw in t for kw in ["新闻","快讯","消息","资讯","公告"])
        needs_northbound = any(kw in t for kw in ["北向","外资","资金流向"])

        if needs_market or needs_hotspot:
            try:
                from astock_data.market.tencent_finance import get_valuation
                index_codes = ["000001","000688","000300","399001","399006"]
                idx_data = get_valuation(index_codes)
                parts = []
                for code in index_codes:
                    d = idx_data.get(code, {})
                    if d.get("price"):
                        pct = d.get("change_pct", 0)
                        arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
                        amt = d.get("amount_wan", 0) / 10000
                        parts.append(f"{d['name']}{d['price']:.0f}{arrow}{pct:+.2f}%成交{amt:.0f}亿")
                if parts:
                    blocks.append(f"【指数 {now_str}】" + " ".join(parts))
            except Exception as e:
                logger.warning(f"指数数据获取失败: {e}")

        if needs_hotspot:
            try:
                from astock_data.signal.ths_hotspot import get_hot_sectors, get_hot_stocks
                sectors = get_hot_sectors()[:10]
                if sectors:
                    sec_parts = [f"{s['sector']}({s['count']}只)" for s in sectors]
                    blocks.append(f"【热点板块】{' '.join(sec_parts)}")
                    hs_df = get_hot_stocks()
                    if hs_df is not None and not hs_df.empty and "题材归因" in hs_df.columns:
                        from astock_data.market.tencent_finance import get_valuation
                        top_sector = sectors[0]["sector"]
                        mask = hs_df["题材归因"].str.contains(top_sector, na=False)
                        sector_stocks = hs_df[mask].head(3)
                        if not sector_stocks.empty:
                            stock_codes = [str(c).zfill(6) for c in sector_stocks["代码"].tolist()]
                            quotes = get_valuation(stock_codes)
                            detail_parts = []
                            for _, row in sector_stocks.iterrows():
                                c = str(row["代码"]).zfill(6)
                                q = quotes.get(c, {})
                                if q.get("price"):
                                    detail_parts.append(f"{row['名称']}{q['price']}{q['change_pct']:+.2f}%")
                            if detail_parts:
                                blocks.append(f"【{top_sector}领涨】{' '.join(detail_parts)}")
            except Exception as e:
                logger.warning(f"热点数据获取失败: {e}")

        if needs_northbound or needs_market:
            try:
                from astock_data.signal.northbound import get_northbound_realtime
                nb = get_northbound_realtime()
                if nb is not None and not nb.empty:
                    row = nb.iloc[-1]
                    blocks.append(f"【北向资金 {now_str}】净流入{row.get('net_amount',0):+.1f}亿")
            except Exception as e:
                logger.warning(f"北向资金获取失败: {e}")

        if codes:
            try:
                from astock_data.market.tencent_finance import get_valuation
                quotes = get_valuation(codes)
                parts = []
                for c in codes:
                    q = quotes.get(c, {})
                    if q.get("price"):
                        arrow = "↑" if q.get("change_pct",0) > 0 else ("↓" if q.get("change_pct",0) < 0 else "→")
                        parts.append(f"{q['name']}{q['price']}{arrow}{q['change_pct']:+.2f}%换手{q['turnover_pct']:.1f}%PE{q['pe_ttm']:.1f}")
                if parts:
                    blocks.append(f"【个股行情 {now_str}】{' '.join(parts)}")
            except Exception as e:
                logger.warning(f"个股行情获取失败: {e}")

        if needs_news or needs_market:
            try:
                from astock_data.news.cls_news import get_flash_news
                news = get_flash_news()[:8]
                if news:
                    news_lines = []
                    for n in news:
                        ts = n.get("time", "")[-5:] if n.get("time") else ""
                        title = n.get("title", "")[:60]
                        news_lines.append(f"  {ts} {title}")
                    blocks.append("【快讯】\n" + "\n".join(news_lines))
            except Exception as e:
                logger.warning(f"快讯获取失败: {e}")

        if needs_ta and codes:
            try:
                from astock_data.ta import get_latest_indicators, get_technical_signals
                from astock_data.market.mootdx_quote import get_kline
                for c in codes[:3]:
                    df = get_kline(c, "day", 120)
                    if df is not None and len(df) > 30:
                        ind = get_latest_indicators(df)
                        sigs = get_technical_signals(ind)
                        pdi, mdi = ind.get("pdi",0), ind.get("mdi",0)
                        trend = "多头" if pdi > mdi else "空头" if mdi > pdi else "盘整"
                        macd = ind.get("macdh",0)
                        rsi = ind.get("rsi",0)
                        ma10, ma50 = ind.get("ma10",0), ind.get("ma50",0)
                        close_price = float(df["close"].iloc[-1]) if "close" in df.columns else 0
                        ma_info = ""
                        if ma10 and ma50 and close_price:
                            if close_price > ma10 > ma50: ma_info = "价MA10↑MA50↑"
                            elif close_price < ma10 < ma50: ma_info = "价MA10↓MA50↓"
                            else: ma_info = f"价{close_price:.2f}MA10{ma10:.2f}MA50{ma50:.2f}"
                        blocks.append(f"【{c}技术】{trend} MACD{macd:+.2f} RSI{rsi:.0f} {ma_info}")
            except Exception as e:
                logger.warning(f"技术分析失败: {e}")

        return "\n\n".join(blocks) if blocks else ""

    # ── 消息路由 ──

    def handle_message(self, chat_id: str, user_text: str, chat_type: str = "group") -> str | None:
        """统一消息入口：去重 → 路由 → 处理。"""
        try:
            if chat_type == "p2p":
                return self._handle_claude_private(chat_id, user_text)
            elif self._needs_claude(user_text):
                return self._handle_claude(chat_id, user_text)
            else:
                return self._handle_trader(chat_id, user_text)
        except Exception as e:
            logger.error(f"handle_message 异常: {e}", exc_info=True)
            return "系统繁忙，请稍后再试"

    # ── 交易员路径 ──

    def _handle_trader(self, chat_id: str, user_text: str) -> str:
        """DeepSeek + CLI 数据 + 对话历史 + 长期记忆。"""
        try:
            # 查询长期记忆
            try:
                mem_store = MemoryStore.get_instance()
                relevant_memories = mem_store.search(user_text[:30], tier="session")
                chat_memories = [
                    m for m in relevant_memories
                    if m["key"].startswith(f"chat:{chat_id}:")
                ][-5:]
            except Exception:
                chat_memories = []

            context = self._build_data_context(user_text)
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            system_parts = [
                f"当前日期: {now_str}",
                "你是用户的私人交易员，在群里和他交流 A 股。",
                "风格：自然口语化，像朋友聊股票一样，轻松但有干货。",
                "要求：",
                "1. 把数据揉进话里自然说出来，别列清单",
                "2. 有观点就说清楚为什么，别只甩结论",
                "3. 语气平和，别太嗨也别太冷",
                "4. 数据在下面，挑有用的用",
            ]
            if chat_memories:
                memory_lines = "\n".join(
                    f"- {m['key'].split(':', 2)[-1]}: {m['value'][:100]}"
                    for m in chat_memories
                )
                system_parts.append(f"\n参考历史记忆:\n{memory_lines}")
            system_instruction = "\n".join(system_parts)

            context_block = f"当前数据:\n{context}" if context else ""
            history = self._trader_history.get(chat_id, [])
            messages = [
                {"role": "user", "content": system_instruction},
                *history,
                {"role": "user", "content": f"{context_block}\n\n用户: {user_text}".strip()},
            ]

            resp = self.llm.call(messages)
            reply = resp[:6000]

            # 更新历史
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": reply})
            if len(history) > self._MAX_HISTORY_EXCHANGES * 2:
                history[:] = history[-(self._MAX_HISTORY_EXCHANGES * 2):]
            self._trader_history[chat_id] = history

            # 保存长期记忆
            try:
                mem_store = MemoryStore.get_instance()
                mem_store.put(
                    key=f"chat:{chat_id}:topic:{int(time.time())}",
                    value=f"用户: {user_text[:80]} → {reply[:200]}",
                    tier="session",
                    tags=["trader", "chat"],
                )
                all_chat = mem_store.search(f"chat:{chat_id}:topic:", tier="session")
                if len(all_chat) > 50:
                    for old in all_chat[50:]:
                        mem_store.delete(old["key"], tier="session")
            except Exception as e:
                logger.debug(f"记忆存储失败: {e}")

            # 交易员输出去重：同一 chat 短时间内相同回复不重复发送
            _now = time.time()
            _prev = self._last_reply.get(chat_id)
            if _prev and _prev[0] == reply and _now - _prev[1] < self._OUTPUT_DEDUP_WINDOW:
                return None
            self._last_reply[chat_id] = (reply, _now)

            return f"[交易员] {reply}"
        except Exception as e:
            logger.error(f"交易员处理失败: {e}", exc_info=True)
            return f"[交易员] 处理异常，请重试"

    # ── Claude 路径 ──

    def _handle_claude_private(self, chat_id: str, user_text: str) -> str:
        """私聊路径 — 纯 Claude 对话。"""
        try:
            from ..utils.claude_bridge import call_claude
            resp = call_claude(user_text, chat_id=chat_id, timeout=300)
            return resp[:6000]
        except ImportError:
            resp = self.llm.call([{"role": "user", "content": user_text}])
            return f"{resp[:6000]}"
        except TimeoutError:
            return "任务耗时过长，请在电脑上重试"
        except Exception as e:
            logger.error(f"Claude 私聊失败: {e}", exc_info=True)
            return f"调用失败: {e}"

    def _handle_claude(self, chat_id: str, user_text: str) -> str:
        """Claude 处理路径 — 转发给 Claude Code CLI。"""
        context = self._build_data_context(user_text)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        full_prompt = user_text
        if context:
            full_prompt = f"当前时间 {now_str}\n\n以下是当前市场数据，参考但不限于此：\n{context}\n\n用户问题：{user_text}"

        try:
            from ..utils.claude_bridge import call_claude
            resp = call_claude(full_prompt, chat_id=chat_id, timeout=300)
            return f"[Claude] {resp[:6000]}"
        except ImportError:
            prompt = (
                "你是运行在用户台式机上的 Claude，负责代码开发、优化和修复。\n"
                "当前运行在回退模式（Claude Code CLI 未安装）。\n"
                f"{'参考数据:\n' + context if context else ''}\n"
                f"用户: {user_text}"
            )
            resp = self.llm.call([{"role": "user", "content": prompt}])
            return f"[Claude(回退)] {resp[:6000]}"
        except TimeoutError:
            return "[Claude] 任务耗时过长，请在 VSCode 中重试"
        except Exception as e:
            logger.error(f"Claude 桥接失败: {e}", exc_info=True)
            return f"[Claude] 调用失败: {e}"
