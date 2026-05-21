"""Managed Agents 主入口.

启动哨兵盯盘:
    python -m managed_agents.main sentinel --interval 60

启动飞书机器人:
    python -m managed_agents.main feishu

Session 管理:
    python -m managed_agents.main session create <agent> <task>
    python -m managed_agents.main session run <session_id>
    python -m managed_agents.main session list
    python -m managed_agents.main session status <session_id>
    python -m managed_agents.main session resume <session_id> [new_task]
    python -m managed_agents.main session history <session_id>

研究员 / 策略师:
    python -m managed_agents.main researcher analyze <code>
    python -m managed_agents.main strategist review [--date]
    python -m managed_agents.main strategist briefing

Agent 决策链回测:
    python -m managed_agents.main backtest run --date 2026-05-15
    python -m managed_agents.main backtest run --date 2026-05-15 --pool 600519 000858 300750
    python -m managed_agents.main backtest batch --start 2026-05-10 --end 2026-05-15
    python -m managed_agents.main backtest report <report.json>

多Agent编排:
    python -m managed_agents.main coordinator run <workflow> [--input <data>]

记忆管理:
    python -m managed_agents.main memory list [--tier user|project|session]
    python -m managed_agents.main memory search <query>
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from astock_trade.utils.logging_setup import setup_logging, get_logger

setup_logging()
logger = get_logger("managed_agents")

from managed_agents.agents.registry import AgentRegistry
from managed_agents.agents.roles.sentinel import Sentinel
from managed_agents.agents.roles.morning_analyst import MorningAnalyst
from managed_agents.agents.roles.researcher_trader import ResearcherTrader
from managed_agents.agents.roles.day_trader import DayTrader
from managed_agents.agents.roles.risk_officer import RiskOfficer
from managed_agents.agents.roles.portfolio_manager import PortfolioManager
from managed_agents.sessions.session_manager import SessionManager
from managed_agents.coordinator.coordinator import Coordinator
from managed_agents.memory.memory_store import MemoryStore
from managed_agents.utils.notifier import notify, sleep_until_next_session
from managed_agents.config import get_config
from managed_agents.backtest.engine import DecisionChainBacktester, BacktestConfig, DEFAULT_POOL
from managed_agents.backtest.report import AttributionReport

ALL_AGENT_CLASSES = [Sentinel, MorningAnalyst, ResearcherTrader, DayTrader, RiskOfficer, PortfolioManager]


def _setup(all_agents: bool = False):
    config = get_config()
    registry = AgentRegistry.get_instance()
    session_mgr = SessionManager.get_instance()

    classes = ALL_AGENT_CLASSES if all_agents else [Sentinel]
    for agent_cls in classes:
        try:
            agent = agent_cls()
            registry.register(agent)
            session_mgr.register_agent(agent)
        except Exception as e:
            logger.warning(f"Failed to register {agent_cls.__name__}: {e}")

    return config, registry, session_mgr


def _setup_coordinator():
    """初始化所有 Agent + Coordinator."""
    _setup(all_agents=True)
    coordinator = Coordinator.get_instance()
    for agent_cls in ALL_AGENT_CLASSES:
        try:
            agent = agent_cls()
            coordinator.register_agent(agent)
        except Exception as e:
            logger.warning(f"Coordinator: failed to register {agent_cls.__name__}: {e}")
    return coordinator


# ═══════════════════════════════════════════════════════════════════
# Sentinel
# ═══════════════════════════════════════════════════════════════════

def run_sentinel(interval: int = 120):
    config, registry, session_mgr = _setup(all_agents=False)
    sentinel = registry.get("sentinel")

    notify("哨兵上线", f"开始盯盘，扫描间隔 {interval} 秒", "info")

    try:
        while True:
            result = sentinel.scan()
            alerts = result.get("alerts", [])

            if alerts:
                for alert in alerts:
                    level = alert["level"]
                    notify_level = {"普通": "info", "关注": "warn", "紧急": "alert"}.get(level, "info")
                    notify(alert["title"], alert.get("detail", ""), notify_level)

            # 盘后深度休眠到次日盘前，零 API/Token 消耗
            if Sentinel._is_trading_time():
                time.sleep(interval)
            else:
                s = sleep_until_next_session()
                if s > 0:
                    logger.info(f"盘后休眠 {s/3600:.1f}h，{datetime.fromtimestamp(time.time() + s).strftime('%m-%d %H:%M')} 唤醒")
                    time.sleep(s)
                else:
                    time.sleep(interval)  # 盘中非交易时段（如 9:00-9:25），等待下次扫描

    except KeyboardInterrupt:
        notify("哨兵下线", "盯盘已停止", "info", force=True)


# ═══════════════════════════════════════════════════════════════════
# Researcher
# ═══════════════════════════════════════════════════════════════════

def cmd_researcher(args):
    _, _, _ = _setup(all_agents=True)
    coordinator = _setup_coordinator()
    researcher = coordinator.get_agent("researcher")

    if args.action == "analyze":
        print(f"研究员分析 {args.code} ...\n")
        result = researcher.analyze(args.code)
        if result.success:
            print(result.output)
        else:
            print(f"分析失败: {result.error}")
            sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# Strategist
# ═══════════════════════════════════════════════════════════════════

def cmd_strategist(args):
    coordinator = _setup_coordinator()
    strategist = coordinator.get_agent("strategist")

    if args.action == "review":
        print("策略师复盘 ...\n")
        result = strategist.daily_review()
    elif args.action == "briefing":
        print("策略师生早报 ...\n")
        result = strategist.morning_briefing()
    else:
        print("Unknown action")
        sys.exit(1)

    if result.success:
        print(result.output)
    else:
        print(f"失败: {result.error}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════
# Coordinator
# ═══════════════════════════════════════════════════════════════════

def cmd_coordinator(args):
    coordinator = _setup_coordinator()

    if args.action == "run":
        wf_name = args.workflow
        input_data = args.input or ""
        print(f"执行工作流: {wf_name}\n{'='*60}")

        result = coordinator.run(wf_name, input_data=input_data)

        for i, step in enumerate(result["steps"]):
            status = "OK" if step["success"] else "FAIL"
            print(f"\n--- Step {i+1}: {step['agent']} ({status}, {step['elapsed_ms']}ms) ---")
            print(step["output"][:600])
            if step.get("error"):
                print(f"  错误: {step['error']}")

    elif args.action == "list":
        print("可用工作流:")
        for name, wf in coordinator._workflows.items():
            steps = " → ".join(s.agent_name for s in wf.steps)
            print(f"  {name:<25} {steps}")


# ═══════════════════════════════════════════════════════════════════
# Memory
# ═══════════════════════════════════════════════════════════════════

def cmd_memory(args):
    store = MemoryStore.get_instance()

    if args.action == "list":
        tier = args.tier or "session"
        entries = store.list_by_tier(tier)
        if not entries:
            print(f"暂无 {tier} 级记忆")
            return
        print(f"{tier} 级记忆 ({len(entries)} 条):\n")
        for e in entries:
            ts = datetime.fromtimestamp(e["updated_at"]).strftime("%m-%d %H:%M") if e["updated_at"] else "-"
            val_short = e["value"][:100].replace("\n", " ")
            print(f"  [{ts}] {e['key']}: {val_short}")

    elif args.action == "search":
        entries = store.search(args.query)
        if not entries:
            print(f"未找到 '{args.query}' 相关记忆")
            return
        print(f"搜索 '{args.query}' ({len(entries)} 条):\n")
        for e in entries:
            val_short = e["value"][:120].replace("\n", " ")
            print(f"  [{e['tier']}] {e['key']}: {val_short}")


# ═══════════════════════════════════════════════════════════════════
# Session (保持原有)
# ═══════════════════════════════════════════════════════════════════

def cmd_session_create(args):
    _, _, mgr = _setup(all_agents=True)
    sid = mgr.create(args.agent, args.task)
    print(f"Session 已创建: {sid}")
    print(f"  Agent: {args.agent}")
    print(f"  Task:  {args.task}")


def cmd_session_run(args):
    _, _, mgr = _setup(all_agents=True)
    session = mgr.query(args.session_id)
    if session is None:
        print(f"Session {args.session_id} 不存在")
        sys.exit(1)

    print(f"执行 Session: {session.session_id}")
    print(f"  Agent: {session.agent_name}")
    print(f"  Task:  {session.task}")

    if args.sync:
        mgr._store.update(session.session_id, status="running")
        result = mgr.run_sync(session.agent_name, session.task, session_id=session.session_id)
        end_status = "completed" if result.success else "failed"
        mgr._store.update(session.session_id, status=end_status, result=result.output, data=result.data)
        print(f"\n结果: {'成功' if result.success else '失败'} ({result.elapsed_ms}ms)")
        print(f"输出:\n{result.output[:500]}")
        if result.error:
            print(f"错误: {result.error}")
    else:
        mgr.execute(args.session_id)
        print(f"Session {args.session_id} 已在后台启动")
        print(f"使用 'python -m managed_agents.main session status {args.session_id}' 查看状态")


def cmd_session_list(args):
    _, _, mgr = _setup(all_agents=True)
    sessions = mgr.list_all()
    if not sessions:
        print("暂无 Session")
        return

    print(f"{'Session ID':<18} {'Agent':<12} {'Status':<12} {'Task':<40}")
    print("-" * 80)
    for s in sessions:
        task_short = s.task[:38] + ".." if len(s.task) > 40 else s.task
        print(f"{s.session_id:<18} {s.agent_name:<12} {s.status:<12} {task_short:<40}")


def cmd_session_status(args):
    _, _, mgr = _setup(all_agents=True)
    session = mgr.query(args.session_id)
    if session is None:
        print(f"Session {args.session_id} 不存在")
        sys.exit(1)

    print(f"Session:  {session.session_id}")
    print(f"Agent:    {session.agent_name}")
    print(f"Status:   {session.status}")
    print(f"Task:     {session.task}")
    if session.created_at:
        print(f"Created:  {datetime.fromtimestamp(session.created_at).strftime('%Y-%m-%d %H:%M:%S')}")
    if session.updated_at:
        print(f"Updated:  {datetime.fromtimestamp(session.updated_at).strftime('%Y-%m-%d %H:%M:%S')}")
    if session.result:
        print(f"Result:\n{session.result[:500]}")
    if session.data:
        print(f"Data:     {session.data}")


def cmd_session_resume(args):
    _, _, mgr = _setup(all_agents=True)
    session = mgr.query(args.session_id)
    if session is None:
        print(f"Session {args.session_id} 不存在")
        sys.exit(1)

    new_task = args.task or None
    print(f"恢复 Session: {args.session_id}")
    print(f"  Agent: {session.agent_name}")
    print(f"  Original Task: {session.task}")
    if new_task:
        print(f"  New Task: {new_task}")

    result = mgr.resume(args.session_id, new_task)
    status = "成功" if result.success else "失败"
    print(f"\n结果: {status} ({result.elapsed_ms}ms)")
    print(f"输出:\n{result.output[:500]}")
    if result.error:
        print(f"错误: {result.error}")


def cmd_session_history(args):
    _, _, mgr = _setup(all_agents=True)
    try:
        messages = mgr.get_history(args.session_id)
        if not messages:
            print(f"Session {args.session_id} 无历史记录")
            return

        print(f"Session {args.session_id} 对话历史 ({len(messages)} 条):\n")
        for i, m in enumerate(messages):
            role = m["role"].upper()
            content = m["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            print(f"[{i}] {role}: {content}")
            print()
    except FileNotFoundError:
        print(f"Session {args.session_id} 无转录文件")


# ═══════════════════════════════════════════════════════════════════
# Feishu Bot
# ═══════════════════════════════════════════════════════════════════

def run_feishu_bot():
    """启动飞书全栈服务 — bot 进站 + 哨兵盯盘 + 调度器定时推送."""
    from managed_agents.utils.feishu_bot import start_bot, stop_bot
    from managed_agents.api.client import get_client

    config = get_config()
    logger.info("启动飞书全栈服务...")

    # ── 1. 调度器（定时任务：盘前/盘中/盘后）──
    scheduler = None
    try:
        _setup(all_agents=True)
        from managed_agents.orchestra.scheduler import Scheduler
        from managed_agents.coordinator.coordinator import Coordinator
        coordinator = Coordinator.get_instance()
        for agent_cls in ALL_AGENT_CLASSES:
            try:
                coordinator.register_agent(agent_cls())
            except Exception as e:
                logger.warning(f"注册 {agent_cls.__name__} 失败: {e}")
        scheduler = Scheduler(coordinator)
        scheduler.start()
        logger.info("调度器已启动")
    except Exception as e:
        logger.warning(f"调度器启动失败: {e}")

    # ── 2. 哨兵（实时盯盘）──
    sentinel = None
    try:
        sentinel = Sentinel()
        import threading
        sentinel_running = True

        def sentinel_loop():
            while sentinel_running:
                try:
                    result = sentinel.scan()
                    for alert in result.get("alerts", []):
                        level = {"普通": "info", "关注": "warn", "紧急": "alert"}.get(alert["level"], "info")
                        notify(alert["title"], alert.get("detail", ""), level)
                except Exception as e:
                    logger.warning(f"哨兵扫描异常: {e}")
                # 盘后深度休眠到次日盘前，零 API/Token 消耗
                if Sentinel._is_trading_time():
                    time.sleep(config.sentinel_scan_interval)
                else:
                    s = sleep_until_next_session()
                    if s > 0:
                        logger.info(f"哨兵盘后休眠 {s/3600:.1f}h")
                        time.sleep(s)
                    else:
                        time.sleep(config.sentinel_scan_interval)

        sentinel_thread = threading.Thread(target=sentinel_loop, daemon=True)
        sentinel_thread.start()
        notify("哨兵上线", f"扫描间隔 {config.sentinel_scan_interval} 秒", "info")
        logger.info("哨兵已启动")
    except Exception as e:
        logger.warning(f"哨兵启动失败: {e}")

    # ── 3. 飞书 bot 进站（接收消息 + 实时数据 + LLM 回复）──
    llm = get_client()
    from managed_agents.skills.market_skills import MarketSkills
    from managed_agents.skills.news_skills import NewsSkills

    markets = MarketSkills()
    news = NewsSkills()

    def handle_message(chat_id: str, user_text: str) -> str | None:
        try:
            # 注入实时行情数据到 LLM 上下文
            data_context = ""
            try:
                h = markets.get_sector_hotspots()
                sectors = h.get("sectors", [])[:5]
                data_context += "实时热点前5: " + ", ".join(
                    f"{s['name']}({s['count']}股涨停)" for s in sectors
                ) + "\n"
            except Exception:
                pass

            # 热点个股列表
            try:
                hs = markets.get_hotspots()
                stocks = hs.get("top_stocks", [])[:12]
                if stocks:
                    data_context += "强势个股:\n" + "\n".join(
                        f"• {s['code']} {s['name']} 题材:{s.get('reason','')[:20]}"
                        for s in stocks
                    ) + "\n"
            except Exception:
                pass

            try:
                nb = markets.get_northbound()
                data_context += f"北向资金: 沪股通{nb.get('latest_hgt',0):+.1f}亿 深股通{nb.get('latest_sgt',0):+.1f}亿 合计{nb.get('total',0):+.1f}亿 最新时间{nb.get('latest_time','')}\n"
            except Exception:
                pass
            try:
                n = news.get_flash_news(limit=5)
                lines = []
                for item in n.get("news", []):
                    t = item.get("title") or item.get("content", "")[:40]
                    if t.strip():
                        lines.append(f"• {t}")
                if lines:
                    data_context += "最新快讯:\n" + "\n".join(lines[:3]) + "\n"
            except Exception:
                pass

            prompt = (
                "你是A股交易助手。以下是当前实时行情数据：\n\n"
                f"{data_context}\n"
                "规则：基于以上实时数据回答用户问题。回复简洁直接，不超过3句话。\n"
                "你有实时热点板块和强势个股数据。当用户问个股推荐时，基于热点板块中的领涨股给出具体建议，说明推荐逻辑（题材+个股名称代码）。\n"
                f"用户消息：{user_text}"
            )
            resp = llm.call([{"role": "user", "content": prompt}])
            return resp[:8000]
        except Exception as e:
            logger.error(f"LLM 回复失败: {e}")
            return "系统繁忙，请稍后再试"

    start_bot(config.feishu_app_id, config.feishu_app_secret, handle_message)

    logger.info("飞书全栈服务运行中，Ctrl+C 退出")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_bot()
        if scheduler:
            scheduler.stop()
        if sentinel:
            sentinel_running = False
        notify("飞书全栈下线", "bot + 哨兵 + 调度器已停止", "info", force=True)
        logger.info("飞书全栈已退出")
        logger.info("飞书机器人已退出")


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def cmd_backtest(args):
    """Agent 决策链回测."""
    if args.action == "run":
        bt_config = BacktestConfig(
            target_date=args.date,
            stock_pool=args.pool or DEFAULT_POOL,
            momentum_threshold=args.momentum,
        )
        tester = DecisionChainBacktester(bt_config)
        report = tester.run()
        report.print()

        if args.output:
            report.save(args.output)
            print(f"报告已保存: {args.output}")

    elif args.action == "batch":
        from datetime import timedelta
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")
        pool = args.pool or DEFAULT_POOL

        all_reports = []
        current = start
        while current <= end:
            # 跳过周末
            if current.weekday() < 5:
                date_str = current.strftime("%Y-%m-%d")
                print(f"\n>>> 回测 {date_str} ...")
                try:
                    bt_config = BacktestConfig(
                        target_date=date_str, stock_pool=pool,
                        momentum_threshold=args.momentum,
                    )
                    tester = DecisionChainBacktester(bt_config)
                    report = tester.run()
                    all_reports.append(report)
                except Exception as e:
                    print(f"  {date_str} 失败: {e}")
            current += timedelta(days=1)

        # 汇总
        if all_reports:
            win_rates = [r.summary.get("win_rate", 0) for r in all_reports]
            avg_corr = sum(r.summary.get("confidence_return_correlation", 0) for r in all_reports) / len(all_reports)
            print(f"\n{'='*60}")
            print(f"  批量回测汇总 ({len(all_reports)} 个交易日)")
            print(f"  平均胜率: {sum(win_rates)/len(win_rates):.1%}")
            print(f"  平均置信度相关性: {avg_corr:.3f}")
            print(f"{'='*60}")

            if args.output:
                combined = {
                    "period": f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}",
                    "days": len(all_reports),
                    "avg_win_rate": round(sum(win_rates) / len(win_rates), 3),
                    "avg_correlation": round(avg_corr, 3),
                    "reports": [r.to_dict() for r in all_reports],
                }
                import json
                Path(args.output).write_text(
                    json.dumps(combined, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
                print(f"汇总已保存: {args.output}")

    elif args.action == "report":
        report = AttributionReport(target_date="")
        # 从 JSON 加载并打印
        import json
        data = json.loads(Path(args.report).read_text(encoding="utf-8"))
        report.summary = data.get("summary", {})
        report.attributions = [
            SignalAttribution(
                symbol=a["symbol"],
                signal=a["signal"],
                forward_returns=a["forward_returns"],
                verdict=a["verdict"],
            ) for a in data.get("attributions", [])
        ]
        report.target_date = data.get("target_date", "")
        report.elapsed_ms = data.get("elapsed_ms", 0)
        report.steps = {}
        for name, step in data.get("chain", {}).items():
            report.steps[name] = ChainStepResult(**step)
        report.print()

def main():
    parser = argparse.ArgumentParser(description="Managed Agents for A-Stock")
    sub = parser.add_subparsers(dest="command")

    # --- sentinel ---
    sentinel_parser = sub.add_parser("sentinel", help="启动哨兵盯盘")
    sentinel_parser.add_argument("--interval", type=int, default=120, help="扫描间隔(秒)")

    # --- feishu ---
    sub.add_parser("feishu", help="启动飞书机器人（双向消息）")

    # --- researcher ---
    researcher_parser = sub.add_parser("researcher", help="研究员分析")
    researcher_sub = researcher_parser.add_subparsers(dest="action")
    res_analyze = researcher_sub.add_parser("analyze", help="个股全方位基本面分析")
    res_analyze.add_argument("code", help="股票代码")

    # --- strategist ---
    strategist_parser = sub.add_parser("strategist", help="策略师复盘")
    strategist_sub = strategist_parser.add_subparsers(dest="action")
    strategist_sub.add_parser("review", help="收盘复盘")
    strategist_sub.add_parser("briefing", help="生成早盘简报")

    # --- coordinator ---
    coord_parser = sub.add_parser("coordinator", help="多Agent编排")

    # --- backtest ---
    backtest_parser = sub.add_parser("backtest", help="Agent决策链回测")
    backtest_sub = backtest_parser.add_subparsers(dest="action")
    bt_run = backtest_sub.add_parser("run", help="单日回测")
    bt_run.add_argument("--date", "-d", required=True, help="目标日期 YYYY-MM-DD")
    bt_run.add_argument("--pool", "-p", nargs="*", help="股票池")
    bt_run.add_argument("--momentum", "-m", type=float, default=3.0, help="动量阈值%% (默认3%%)")
    bt_run.add_argument("--output", "-o", help="输出 JSON 路径")
    bt_batch = backtest_sub.add_parser("batch", help="批量回测")
    bt_batch.add_argument("--start", "-s", required=True, help="起始日期 YYYY-MM-DD")
    bt_batch.add_argument("--end", "-e", required=True, help="结束日期 YYYY-MM-DD")
    bt_batch.add_argument("--pool", "-p", nargs="*", help="股票池")
    bt_batch.add_argument("--momentum", "-m", type=float, default=3.0, help="动量阈值%% (默认3%%)")
    bt_batch.add_argument("--output", "-o", help="汇总输出 JSON 路径")
    bt_report = backtest_sub.add_parser("report", help="查看回测报告")
    bt_report.add_argument("report", help="报告 JSON 文件路径")
    coord_sub = coord_parser.add_subparsers(dest="action")
    coord_run = coord_sub.add_parser("run", help="运行工作流")
    coord_run.add_argument("workflow", help="工作流名称 (morning_briefing/intraday_alert/daily_review/stock_deep_dive)")
    coord_run.add_argument("--input", "-i", help="输入数据 (如股票代码)")
    coord_sub.add_parser("list", help="列出所有工作流")

    # --- memory ---
    mem_parser = sub.add_parser("memory", help="记忆管理")
    mem_sub = mem_parser.add_subparsers(dest="action")
    mem_list = mem_sub.add_parser("list", help="列出记忆")
    mem_list.add_argument("--tier", choices=["user", "project", "session"], help="记忆层级")
    mem_search = mem_sub.add_parser("search", help="搜索记忆")
    mem_search.add_argument("query", help="搜索关键词")

    # --- session ---
    session_parser = sub.add_parser("session", help="Session 管理")
    session_sub = session_parser.add_subparsers(dest="session_cmd")

    create_parser = session_sub.add_parser("create", help="创建新 Session")
    create_parser.add_argument("agent", help="Agent 名称")
    create_parser.add_argument("task", help="任务描述")

    run_parser = session_sub.add_parser("run", help="执行 Session")
    run_parser.add_argument("session_id", help="Session ID")
    run_parser.add_argument("--sync", action="store_true", help="同步执行 (阻塞等待)")

    session_sub.add_parser("list", help="列出所有 Session")

    status_parser = session_sub.add_parser("status", help="查看 Session 状态")
    status_parser.add_argument("session_id", help="Session ID")

    resume_parser = session_sub.add_parser("resume", help="恢复 Session (加载历史上下文)")
    resume_parser.add_argument("session_id", help="Session ID")
    resume_parser.add_argument("task", nargs="?", help="新任务 (可选)")

    history_parser = session_sub.add_parser("history", help="查看 Session 对话历史")
    history_parser.add_argument("session_id", help="Session ID")

    args = parser.parse_args()

    if args.command == "sentinel":
        run_sentinel(interval=args.interval)

    elif args.command == "feishu":
        run_feishu_bot()

    elif args.command == "researcher":
        cmd_researcher(args)

    elif args.command == "strategist":
        cmd_strategist(args)

    elif args.command == "coordinator":
        cmd_coordinator(args)

    elif args.command == "backtest":
        cmd_backtest(args)

    elif args.command == "memory":
        cmd_memory(args)

    elif args.command == "session":
        if args.session_cmd == "create":
            cmd_session_create(args)
        elif args.session_cmd == "run":
            cmd_session_run(args)
        elif args.session_cmd == "list":
            cmd_session_list(args)
        elif args.session_cmd == "status":
            cmd_session_status(args)
        elif args.session_cmd == "resume":
            cmd_session_resume(args)
        elif args.session_cmd == "history":
            cmd_session_history(args)
        else:
            session_parser.print_help()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
