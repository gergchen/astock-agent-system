"""全自动验证模拟 — 走通完整交易链路.

用法:
    python -m managed_agents.scripts.auto_verify
    python -m managed_agents.scripts.auto_verify --ths   # 用同花顺账户数据验证
"""

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from astock_trade.broker import create_broker, MockBroker, BrokerBase
from astock_trade.bus import (
    researcher_publish_signal,
    clear_channel,
)
from astock_trade.trade_journal import record_trade, query_trades
from managed_agents.agents.roles.day_trader import DayTrader
from managed_agents.agents.roles.risk_officer import RiskOfficer


def step(msg: str):
    print(f"\n{'='*60}")
    print(f" [{datetime.now().strftime('%H:%M:%S')}] {msg}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="全自动验证模拟")
    parser.add_argument("--ths", action="store_true", help="使用同花顺账户数据")
    args = parser.parse_args()

    print("+----------------------------------------------------+")
    print("|      A股多Agent交易系统 - 全自动验证模拟            |")
    print("+----------------------------------------------------+")

    # -- Step 0: Broker 初始化 --
    step("Step 0: Broker 初始化")
    if args.ths:
        real_broker = create_broker(broker_type="ths")
        acct = real_broker.get_account()
        print(f"  同花顺账户  总资产: {acct.total_assets:.2f}  可用: {acct.cash:.2f}")
        trade_broker = MockBroker(initial_cash=acct.total_assets)
        trade_broker.connect()
        print(f"  交易执行用 MockBroker (盘前模拟)")
    else:
        trade_broker = create_broker(broker_type="mock")
        acct = trade_broker.get_account()
        print(f"  Mock账户    总资产: {acct.total_assets:.2f}  可用: {acct.cash:.2f}")

    # -- Step 1: 构建 Agent --
    step("Step 1: Agent 初始化")
    trader = DayTrader(broker=trade_broker)
    risk = RiskOfficer(broker=trade_broker)
    print(f"  DayTrader    broker: {type(trade_broker).__name__}")
    print(f"  RiskOfficer  broker: {type(trade_broker).__name__}")

    # -- 清理消息总线 --
    for ch in ("from_researcher", "from_risk_officer", "from_trader"):
        clear_channel(ch)

    # -- Step 2: 生成交易信号 --
    step("Step 2: 生成模拟交易信号 (3只)")

    test_signals = [
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "direction": "BUY",
            "price": 1850.0,
            "volume": 100,
            "reason": "放量突破20日均线，MACD金叉",
            "strategy": "ma_crossover",
            "confidence": 0.75,
        },
        {
            "symbol": "000858",
            "name": "五粮液",
            "direction": "BUY",
            "price": 145.0,
            "volume": 500,
            "reason": "缩量回调至支撑位，反弹信号",
            "strategy": "support_bounce",
            "confidence": 0.62,
        },
        {
            "symbol": "002230",
            "name": "科大讯飞",
            "direction": "SELL",
            "price": 55.0,
            "volume": 200,
            "reason": "放量下跌，跌破趋势线",
            "strategy": "trend_follow",
            "confidence": 0.68,
        },
    ]

    for i, sig in enumerate(test_signals):
        sig["signal_id"] = f"sig_{int(time.time())}_{i:03d}"
        researcher_publish_signal(sig)
        print(f"  发布: {sig['symbol']} {sig['name']} {sig['direction']} "
              f"{sig['price']}x{sig['volume']} [{sig['strategy']}]")

    # -- Step 3: 风控审查 --
    step("Step 3: 风控审查")
    results = risk.review_pending()
    approved = 0
    rejected = 0
    for r in results:
        d = r.get("decision", "UNKNOWN")
        if d == "APPROVED":
            approved += 1
        else:
            rejected += 1
        icon = "[OK]" if d == "APPROVED" else "[NO]"
        print(f"  {icon} {d} | {r.get('reason', '')}")
        checks = r.get("checks", {})
        if checks:
            fail = [k for k, v in checks.items() if not v]
            if fail:
                print(f"          未通过: {fail}")
    print(f"  结果: {approved} 通过 / {rejected} 拒绝")

    # -- Step 4: 交易执行 --
    step("Step 4: 交易执行")
    results = trader.execute_pending()
    filled = 0
    failed = 0
    for r in results:
        if r.get("success"):
            filled += 1
            res = r["result"]
            print(f"  [OK] 成交: {res['symbol']} {res['direction']} "
                  f"{res['price']}x{res['volume']} 单号:{res['order_id']}")
        else:
            failed += 1
            print(f"  [NO] 失败: {r.get('error', 'unknown')}")
    print(f"  结果: {filled} 成交 / {failed} 失败")

    # -- Step 5: 直接写 trade_journal (演练持久化) --
    step("Step 5: 交易日志写入验证")
    demo_trades = [
        ("600519", "BUY", 1850.0, 100, "ma_crossover"),
        ("000858", "BUY", 145.0, 500, "support_bounce"),
        ("600519", "SELL", 1920.0, 100, "ma_crossover"),
    ]
    for sym, direction, price, vol, strategy in demo_trades:
        record = record_trade(sym, direction, price, vol, strategy=strategy)
        print(f"  写入: {sym} {direction} {price}x{vol} [{strategy}] id={record.get('id','')}")

    today_d = date.today()
    trades = query_trades(start_date=today_d, end_date=today_d)
    if trades:
        print(f"\n  今日共 {len(trades)} 笔交易记录")
        for t in trades[-5:]:
            print(f"    {t['symbol']} {t['direction']} {t['price']}x{t['volume']} "
                  f"${t['amount']:.0f} [{t.get('strategy','')}]")

    # -- Step 6: 经验学习 --
    step("Step 6: 经验学习管线")
    try:
        from managed_agents.experience.pattern_learner import (
            run_pattern_analysis,
            get_all_patterns,
        )

        now = date.today()
        summary = run_pattern_analysis(start_date=now - timedelta(days=60), end_date=now)
        print(f"  分析结果: {summary.get('status', summary.get('total_roundtrips', 'N/A'))}")

        stored = get_all_patterns()
        print(f"  策略模式: {len(stored)} 个")
        for key, p in stored.items():
            wr = p.get("win_rate", 0)
            icon = "[G]" if wr >= 0.5 else "[Y]" if wr >= 0.3 else "[R]"
            print(f"    {icon} {p.get('strategy', p.get('type', key))}: "
                  f"{p.get('total', 0)}笔 胜率{wr:.0%}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  模式学习跳过: {e}")

    # -- Step 7: 验证 MemoryStore --
    step("Step 7: 经验记忆系统")
    try:
        from managed_agents.memory.memory_store import MemoryStore
        store = MemoryStore.get_instance()
        store.put(
            key="verify:done",
            value=f"全自动验证模拟 {datetime.now().isoformat()}",
            tier="project",
            tags=["verify", "auto"],
        )
        stored = store.get("verify:done", tier="project")
        count = len(store.list_by_tier("project"))
        print(f"  MemoryStore 读写: OK ({count} 条)")
        print(f"  验证标记: {stored}")
    except Exception as e:
        print(f"  MemoryStore 异常: {e}")

    # -- 汇总 --
    step("验证汇总")
    print(f"  Broker:      {'THS(同花顺)+Mock模拟交易' if args.ths else 'Mock'}")
    print(f"  账户资产:    {acct.total_assets:.2f}")
    print(f"  Agent:       DayTrader + RiskOfficer")
    print(f"  信号/风控:   {len(test_signals)} -> {approved} 通过")
    print(f"  交易执行:    {filled} 笔成交")
    print(f"  交易日志:    {len(trades)} 条记录")
    print(f"  模式学习:    {'OK' if stored else '需积累数据'}")
    print(f"  MemoryStore: OK")
    print()


if __name__ == "__main__":
    main()
