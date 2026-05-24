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
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, time as dt_time
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

# 用户消息去重（同一 chat+文本 5秒内忽略）
_USER_MSG_DEDUP: dict[str, float] = {}
_MSG_DEDUP_LOCK = threading.Lock()
_MSG_DEDUP_WINDOW = 30.0  # 30秒，仅防手滑双击

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
    """启动飞书全栈服务 — bot 进站 + 哨兵盯盘 + 调度器定时推送.

    Bot 在线 24h 随时回复用户消息；
    哨兵/调度器 15:05 停服，次日 8:55 自动唤醒，避免盘后空转。
    """
    # ── PID 锁文件：防重复启动（原子创建 + tasklist 验证）──
    this_pid = os.getpid()
    _pid_file = Path(tempfile.gettempdir()) / "feishu_bot.pid"

    # 已有锁文件 → 检查 PID 是否存活
    if _pid_file.exists():
        try:
            old_pid = int(_pid_file.read_text().strip())
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {old_pid}", "/NH"],
                capture_output=True, timeout=5
            )
            stdout = r.stdout.decode("gbk", errors="replace").lower()
            if f"{old_pid}" in stdout and "python" in stdout:
                print(f"Bot 已在运行 (PID {old_pid})，跳过启动")
                return
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
        _pid_file.unlink(missing_ok=True)

    # 原子创建锁文件（'x' 模式：文件已存在则抛 FileExistsError）
    try:
        fd = os.open(str(_pid_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(this_pid).encode())
        os.close(fd)
    except FileExistsError:
        print(f"Bot 已在运行，跳过启动")
        return

    import atexit
    atexit.register(lambda: _pid_file.unlink(missing_ok=True))

    from managed_agents.api.client import get_client
    from managed_agents.im.router import MessageRouter
    from managed_agents.im.feishu_adapter import FeishuAdapter

    config = get_config()
    logger.info("启动飞书全栈服务...")

    # ── IM 路由器（统一消息通道，后续加微信/钉钉只在此注册）──
    router = MessageRouter()
    feishu = FeishuAdapter(config.feishu_app_id, config.feishu_app_secret)
    router.register(feishu)
    logger.info(f"IM 路由器就绪，平台: {router.platforms}")

    # ── 1. 调度器（定时任务：盘前/盘中/盘后）──
    def _start_scheduler():
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
        return scheduler

    # ── 2. 哨兵线程 ──
    _sentinel_running = False
    _sentinel_thread = None

    def _start_sentinel():
        nonlocal _sentinel_running, _sentinel_thread
        try:
            sentinel = Sentinel()
            _sentinel_running = True

            def loop():
                while _sentinel_running:
                    try:
                        result = sentinel.scan()
                        for alert in result.get("alerts", []):
                            level = {"普通": "info", "关注": "warn", "紧急": "alert"}.get(alert["level"], "info")
                            notify(alert["title"], alert.get("detail", ""), level)
                    except Exception as e:
                        logger.warning(f"哨兵扫描异常: {e}")
                    if Sentinel._is_trading_time():
                        time.sleep(config.sentinel_scan_interval)
                    else:
                        s = sleep_until_next_session()
                        if s > 0:
                            logger.info(f"哨兵盘后休眠 {s/3600:.1f}h")
                            time.sleep(s)
                        else:
                            time.sleep(config.sentinel_scan_interval)

            _sentinel_thread = threading.Thread(target=loop, daemon=True)
            _sentinel_thread.start()
            notify("哨兵上线", f"扫描间隔 {config.sentinel_scan_interval} 秒", "info")
            logger.info("哨兵已启动")
        except Exception as e:
            logger.warning(f"哨兵启动失败: {e}")

    def _stop_sentinel():
        nonlocal _sentinel_running
        _sentinel_running = False

    # ── 3. 消息处理器（路由 / 上下文 / 历史 / 记忆）──
    from managed_agents.im.trader_handler import TraderHandler
    llm = get_client()
    handler = TraderHandler(llm)

    # ── 启动 Bot（24h 在线，永不停止）──
    router.set_route_fn(lambda msg: handler.handle_message(msg.chat_id, msg.text, msg.chat_type))
    router.start_all()
    logger.info("飞书全栈服务运行中，Ctrl+C 退出")

    # ── 日间循环：调度器+哨兵每天重启，bot 始终在线 ──
    scheduler = None
    try:
        while True:
            now = datetime.now()
            # 交易日盘中 → 启动调度器 + 哨兵
            if now.weekday() < 5 and dt_time(9, 0) <= now.time() < dt_time(15, 5):
                if scheduler is None:
                    scheduler = _start_scheduler()
                    _start_sentinel()
                time.sleep(15)
            # 盘后（15:05+）→ 停调度器 + 哨兵，深度休眠
            elif now.weekday() < 5 and now.time() >= dt_time(15, 5):
                if scheduler is not None:
                    scheduler.stop()
                    scheduler = None
                    _stop_sentinel()
                    notify("哨兵+调度器已停止", "盘后自动关闭，次日 8:55 唤醒", "info")
                    logger.info("盘后停服，bot 仍在线可回复消息")
                s = sleep_until_next_session()
                if s > 0:
                    logger.info(f"距下次开盘还有 {s/3600:.1f}h，深度休眠中")
                    time.sleep(s)
            # 非交易日 → 直接深度休眠
            else:
                if scheduler is not None:
                    scheduler.stop()
                    scheduler = None
                    _stop_sentinel()
                s = sleep_until_next_session()
                if s > 0:
                    logger.info(f"非交易日，休眠 {s/3600:.1f}h 至下次开盘")
                    time.sleep(s)

    except KeyboardInterrupt:
        pass

    # 用户 Ctrl+C 退出时才停 bot
    router.stop_all()
    notify("飞书全栈下线", "bot 已停止", "info", force=True)
    logger.info("飞书全栈已退出")


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

def cmd_feishu_send(args):
    """发送飞书消息。"""
    from managed_agents.utils.feishu_bot import send_message
    config = get_config()
    ok = send_message(args.chat_id, args.text, config.feishu_app_id, config.feishu_app_secret)
    if ok:
        print(f"已发送到 {args.chat_id}")
    else:
        print("发送失败")
        sys.exit(1)


def cmd_claude_poll(args):
    """查看 Claude 收件箱中待处理的消息。"""
    inbox_dir = Path(__file__).parent.parent / "managed_agents_data" / "claude_inbox"
    if not inbox_dir.exists():
        print("收件箱为空")
        return

    files = sorted(inbox_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        print("收件箱为空")
        return

    print(f"Claude 收件箱 ({len(files)} 条待处理):\n")
    for f in files:
        msg = json.loads(f.read_text(encoding="utf-8"))
        from datetime import datetime as _dt
        ts = _dt.fromtimestamp(msg["time"]).strftime("%m-%d %H:%M:%S")
        print(f"  [{ts}] {f.stem}")
        print(f"  Chat: {msg['chat_id']}")
        print(f"  内容: {msg['text'][:200]}")
        print()


def cmd_claude_process(args):
    """处理 Claude 收件箱中的消息并通过飞书回复。"""
    from managed_agents.utils.feishu_bot import send_message
    config = get_config()
    inbox_dir = Path(__file__).parent.parent / "managed_agents_data" / "claude_inbox"
    if not inbox_dir.exists():
        print("收件箱为空")
        return

    files = sorted(inbox_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        print("收件箱为空")
        return

    print(f"Claude 收件箱 ({len(files)} 条待处理):\n")
    for f in files:
        msg = json.loads(f.read_text(encoding="utf-8"))
        from datetime import datetime as _dt
        ts = _dt.fromtimestamp(msg["time"]).strftime("%m-%d %H:%M:%S")
        print(f"  {'='*50}")
        print(f"  [{ts}] ID: {f.stem}")
        print(f"  Chat: {msg['chat_id']}")
        print(f"  内容: {msg['text']}")
        print()

    print(f"\n使用以下命令回复:")
    print(f"  python -m managed_agents.main feishu-send <chat_id> \"回复内容\"")
    print(f"  或直接回复指定消息:")
    print(f"  python -m managed_agents.main claude-respond <msg_id> \"回复内容\"")
    print(f"  回复后删除对应文件: rm {inbox_dir}/<msg_id>.json")


def cmd_claude_respond(args):
    """回复指定收件箱消息并删除待处理文件。"""
    from managed_agents.utils.feishu_bot import send_message
    config = get_config()
    inbox_dir = Path(__file__).parent.parent / "managed_agents_data" / "claude_inbox"
    msg_file = inbox_dir / f"{args.msg_id}.json"
    if not msg_file.exists():
        print(f"消息 {args.msg_id} 不存在")
        sys.exit(1)

    msg = json.loads(msg_file.read_text(encoding="utf-8"))
    ok = send_message(msg["chat_id"], args.text, config.feishu_app_id, config.feishu_app_secret)
    if ok:
        msg_file.unlink()
        print(f"✓ 已回复并删除 {args.msg_id}.json")
    else:
        print("发送失败，文件保留")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════
# Douyin Monitor
# ═══════════════════════════════════════════════════════════════════

def cmd_douyin(args):
    from managed_agents.douyin.crawler import DouyinCrawler
    from managed_agents.douyin.api_client import DouyinAPI
    from managed_agents.skills.douyin_skills import DouyinSkills

    if args.douyin_cmd == "monitor":
        api = DouyinAPI()
        if not api.health_check():
            print("Douyin API 不可达, 请确认服务已启动 (远端的 http://<server>:8000 或本地的端口映射)")
            sys.exit(1)
        crawler = DouyinCrawler(api)
        crawler.run_forever(args.interval or None)

    elif args.douyin_cmd == "scan-user":
        skills = DouyinSkills()
        print(skills.scan_user(args.sec_user_id, args.nickname))

    elif args.douyin_cmd == "analyze-video":
        skills = DouyinSkills()
        print(skills.analyze_video(args.url))

    elif args.douyin_cmd == "list":
        skills = DouyinSkills()
        print(skills.list_users())

    elif args.douyin_cmd == "user-info":
        skills = DouyinSkills()
        print(skills.get_user_info(args.sec_user_id))

    else:
        print("未知命令. 可用: monitor, scan-user, analyze-video, list, user-info")


def main():
    parser = argparse.ArgumentParser(description="Managed Agents for A-Stock")
    sub = parser.add_subparsers(dest="command")

    # --- sentinel ---
    sentinel_parser = sub.add_parser("sentinel", help="启动哨兵盯盘")
    sentinel_parser.add_argument("--interval", type=int, default=120, help="扫描间隔(秒)")

    # --- feishu ---
    sub.add_parser("feishu", help="启动飞书机器人（双向消息）")

    # --- claude inbox ---
    sub.add_parser("claude-poll", help="查看 Claude 收件箱待处理消息")
    sub.add_parser("claude-process", help="查看收件箱中所有消息（含回复指引）")
    claude_respond = sub.add_parser("claude-respond", help="回复收件箱消息")
    claude_respond.add_argument("msg_id", help="消息 ID（文件名不含 .json）")
    claude_respond.add_argument("text", help="回复内容")

    # --- feishu send ---
    feishu_send = sub.add_parser("feishu-send", help="发送飞书消息")
    feishu_send.add_argument("chat_id", help="目标群聊/用户 chat_id")
    feishu_send.add_argument("text", help="消息内容")

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

    # --- douyin monitor ---
    dy_parser = sub.add_parser("douyin", help="抖音带货监控")
    dy_sub = dy_parser.add_subparsers(dest="douyin_cmd")
    dy_sub.add_parser("monitor", help="启动抖音监控轮询").add_argument(
        "--interval", type=int, default=0, help="轮询间隔(秒), 默认使用配置值")
    dy_scan = dy_sub.add_parser("scan-user", help="扫描指定用户")
    dy_scan.add_argument("sec_user_id", help="抖音用户 sec_user_id")
    dy_scan.add_argument("--nickname", "-n", default="", help="用户昵称")
    dy_analyze = dy_sub.add_parser("analyze-video", help="分析单个视频")
    dy_analyze.add_argument("url", help="抖音分享链接")
    dy_sub.add_parser("list", help="列出监控用户")
    dy_info = dy_sub.add_parser("user-info", help="获取用户信息")
    dy_info.add_argument("sec_user_id", help="抖音用户 sec_user_id")

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

    elif args.command == "claude-poll":
        cmd_claude_poll(args)

    elif args.command == "claude-process":
        cmd_claude_process(args)

    elif args.command == "claude-respond":
        cmd_claude_respond(args)

    elif args.command == "feishu-send":
        cmd_feishu_send(args)

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

    elif args.command == "douyin":
        cmd_douyin(args)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
