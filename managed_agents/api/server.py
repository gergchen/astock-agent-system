"""HTTP API Server — FastAPI 多租户 SaaS 入口.

启动:
    python -m managed_agents.api.server

API 端点:
    POST   /api/v1/tenants                  创建租户
    POST   /api/v1/sessions                 创建会话
    GET    /api/v1/sessions/{id}            查询状态
    GET    /api/v1/sessions/{id}/history    对话历史
    GET    /api/v1/agents                   列出可用 Agent
    POST   /api/v1/team/cycle               触发一个完整交易周期
    WS     /api/v1/ws/alerts                实时告警推送
    POST   /api/v1/chat/send                聊天面板发送消息
    GET    /chat                            聊天面板页面
"""

import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from managed_agents.agents.registry import AgentRegistry
from managed_agents.agents.roles.sentinel import Sentinel
from managed_agents.agents.roles.morning_analyst import MorningAnalyst
from managed_agents.agents.roles.researcher_trader import ResearcherTrader
from managed_agents.agents.roles.day_trader import DayTrader
from managed_agents.agents.roles.risk_officer import RiskOfficer
from managed_agents.agents.roles.portfolio_manager import PortfolioManager
from managed_agents.sessions.session_manager import SessionManager
from managed_agents.orchestra.coordinator import Coordinator
from managed_agents.orchestra.bus import EventBus
from managed_agents.deploy.tenants import get_tenant_manager
from astock_trade.utils.logging_setup import setup_logging, get_logger
from managed_agents.config import get_config
from managed_agents.im.trader_handler import TraderHandler
from managed_agents.api.client import get_client

setup_logging()
logger = get_logger("api_server")

# ── 尝试导入 FastAPI ──
try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import RedirectResponse
    from pydantic import BaseModel
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    logger.warning("FastAPI not installed. Install with: pip install fastapi uvicorn pydantic")


# ── 数据模型 ──
class TenantCreate(BaseModel):
    tenant_id: str
    name: str = ""
    agent_whitelist: list[str] = []


class SessionCreate(BaseModel):
    tenant_id: str
    agent_name: str
    task: str


class TaskRequest(BaseModel):
    task: str
    context: Optional[dict] = None


class ChatRequest(BaseModel):
    message: str


# ── 初始化 ──
def init_app():
    config = get_config()
    registry = AgentRegistry.get_instance()
    session_mgr = SessionManager.get_instance()

    # 尝试创建 broker
    broker = None
    from astock_trade.broker import create_broker
    try:
        broker = create_broker(broker_type="ths")
        logger.info("API server: 使用同花顺模拟交易")
    except Exception as e:
        logger.warning(f"API server: THS broker 初始化失败: {e}")

    agents = [Sentinel, MorningAnalyst, ResearcherTrader, DayTrader, RiskOfficer, PortfolioManager]
    for agent_cls in agents:
        try:
            if agent_cls is DayTrader:
                agent = DayTrader(broker=broker)
            elif agent_cls is RiskOfficer:
                agent = RiskOfficer(broker=broker)
            else:
                agent = agent_cls()
            registry.register(agent)
            session_mgr.register_agent(agent)
        except Exception as e:
            logger.warning(f"Failed to register {agent_cls.__name__}: {e}")

    tm = get_tenant_manager()
    # 创建默认租户
    if "default" not in [t.tenant_id for t in tm.list_all()]:
        tm.create("default", "Default Tenant")
        logger.info("Default tenant created")

    return config, registry, session_mgr, tm


config, registry, session_mgr, tenant_mgr = init_app()

# ── FastAPI App ──
app = FastAPI(
    title="Managed Agents API",
    description="A股多Agent量化交易 SaaS API — 哨兵盯盘 / 回测 / 多Agent编排 / 实时告警",
    version="0.2.0",
    contact={"name": "Astock Agent System", "url": "https://github.com/gergchen/astock-agent-system"},
)

# CORS — allow all origins for development
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass

# ── 聊天 Handler（VS Code 内嵌聊天面板用）──
_chat_handler: TraderHandler | None = None
def get_chat_handler() -> TraderHandler:
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = TraderHandler(get_client())
    return _chat_handler

# ── 挂载静态文件 ──
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    try:
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        logger.info(f"Static files mounted from {STATIC_DIR}")
    except Exception as e:
        logger.warning(f"Failed to mount static files: {e}")

# ── WebSocket 连接池 ──
ws_clients: list[WebSocket] = []

# 订阅事件总线，实时推送到 WebSocket
def _ws_alert_callback(channel: str, message: dict):
    for ws in ws_clients:
        try:
            # asyncio.create_task in sync context — schedule via next tick
            pass  # handled in WS poll loop
        except Exception:
            pass

EventBus.subscribe("*", _ws_alert_callback)


# ── 租户管理 ──
@app.post("/api/v1/tenants")
def create_tenant(body: TenantCreate):
    try:
        t = tenant_mgr.create(
            tenant_id=body.tenant_id,
            name=body.name,
            agent_whitelist=body.agent_whitelist,
        )
        return {"status": "ok", "tenant_id": t.tenant_id}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/v1/tenants")
def list_tenants():
    return [
        {"tenant_id": t.tenant_id, "name": t.name, "created_at": t.created_at}
        for t in tenant_mgr.list_all()
    ]


# ── Agent ──
@app.get("/api/v1/agents")
def list_agents(tenant_id: str = "default"):
    if tenant_id not in [t.tenant_id for t in tenant_mgr.list_all()]:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return registry.list_all()


# ── Session ──
@app.post("/api/v1/sessions")
def create_session(body: SessionCreate):
    if body.tenant_id not in [t.tenant_id for t in tenant_mgr.list_all()]:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant_mgr.can_use_agent(body.tenant_id, body.agent_name):
        raise HTTPException(status_code=403, detail=f"Agent '{body.agent_name}' not in whitelist")

    if not tenant_mgr.check_rate_limit(body.tenant_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    try:
        sid = session_mgr.create(body.agent_name, body.task)
        session_mgr.execute(sid)
        return {"session_id": sid, "status": "running"}
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/sessions/{session_id}")
def get_session(session_id: str):
    session = session_mgr.query(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@app.get("/api/v1/sessions/{session_id}/history")
def get_history(session_id: str):
    try:
        messages = session_mgr.get_history(session_id)
        return {"session_id": session_id, "messages": messages, "count": len(messages)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Transcript not found")


@app.post("/api/v1/sessions/{session_id}/messages")
def append_message(session_id: str, body: TaskRequest):
    session = session_mgr.query(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    result = session_mgr.resume(session_id, body.task)
    return {
        "session_id": session_id,
        "success": result.success,
        "output": result.output[:2000],
        "elapsed_ms": result.elapsed_ms,
    }


# ── 交易团队 ──
@app.post("/api/v1/team/cycle")
def trigger_cycle():
    coordinator = Coordinator()
    try:
        results = coordinator.run_full_cycle()
        return {
            "status": "completed",
            "results": [
                {
                    "phase": r.phase,
                    "agent": r.agent_name,
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ],
        }
    finally:
        coordinator.shutdown()


# ── WebSocket 实时告警 ──
@app.websocket("/api/v1/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            cmd = json.loads(data)
            if cmd.get("action") == "subscribe":
                channels = cmd.get("channels", ["alerts"])
                for ch in channels:
                    msgs = EventBus.peek(ch, limit=5)
                    for m in msgs:
                        await websocket.send_json({"channel": ch, "message": m})
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.remove(websocket)


# ── 聊天面板（VS Code 内嵌）──
VSCODE_CHAT_ID = "vscode_chat_internal"

@app.post("/api/v1/chat/send")
def chat_send(body: ChatRequest):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")
    try:
        handler = get_chat_handler()
        reply = handler.handle_message(
            chat_id=VSCODE_CHAT_ID,
            user_text=body.message.strip(),
            chat_type="p2p",
        )
        return {"reply": reply or "(空回复)"}
    except Exception as e:
        logger.error(f"Chat API error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat")
def chat_page():
    return RedirectResponse(url="/static/chat.html")


# ── 监控面板数据 ──
@app.get("/api/v1/dashboard")
def dashboard():
    """监控面板 — 系统运行状态全览."""
    from datetime import time as dt_time
    from managed_agents.orchestra.scheduler import TRADING_SCHEDULE, _get_period
    from astock_trade.bus import peek, list_channels
    now = datetime.now()

    # 交易时段
    period = _get_period(now.time())
    is_trading = now.weekday() < 5 and dt_time(9, 0) <= now.time() < dt_time(15, 0)

    # 信号 & 执行（从消息总线读取）
    signals = peek("from_researcher", limit=5)
    results = peek("from_trader", limit=10)

    # 账户（如果 broker 有）
    account_data = {}
    try:
        from astock_trade.broker import create_broker
        broker = create_broker()
        if broker:
            acct = broker.get_account()
            account_data = {
                "cash": acct.cash,
                "frozen": acct.frozen,
                "total_assets": acct.total_assets,
                "positions": [
                    {"symbol": p.symbol, "volume": p.volume, "pnl": p.pnl,
                     "market_value": p.market_value, "current_price": p.current_price}
                    for p in (acct.positions or [])
                ],
            }
    except Exception:
        account_data = {"error": "Broker not available"}

    return {
        "status": "ok",
        "server_time": now.isoformat(timespec="seconds"),
        "trading_day": is_trading,
        "current_period": period or "non_trading",
        "agents": registry.list_all(),
        "signals": signals,
        "trade_results": results,
        "account": account_data,
    }


@app.get("/api/v1/dashboard/timeline")
def dashboard_timeline(limit: int = 20):
    """活动时间线 — 信号 + 交易 + 通知合并输出."""
    from astock_trade.bus import (
        peek, list_channels
    )
    events = []

    # 交易信号
    for s in peek("from_researcher", limit=10):
        events.append({
            "time": s.get("timestamp", ""),
            "type": "signal",
            "summary": f"[{s.get('sector','')}] {s.get('direction','')} 置信度{s.get('confidence',0):.0%}",
            "detail": s.get("reason", ""),
        })

    # 执行结果
    for r in peek("from_trader", limit=10):
        ok = r.get("success", False)
        res = r.get("result", {})
        events.append({
            "time": res.get("timestamp", r.get("timestamp", "")),
            "type": "trade",
            "summary": f"{'✅' if ok else '❌'} {res.get('symbol','')} {res.get('direction','')} {res.get('price','')}x{res.get('volume','')}",
            "detail": f"status={res.get('status','')}" if ok else f"error={r.get('error','')}",
        })

    events.sort(key=lambda e: e["time"], reverse=True)
    return {"events": events[:limit]}


# ── 健康检查 ──
@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "agents": len(registry.list_all()),
        "tenants": len(tenant_mgr.list_all()),
        "timestamp": datetime.now().isoformat(),
    }


# ── 根路径 — 监控面板 ──
@app.get("/")
def root():
    return RedirectResponse(url="/static/dashboard.html")


# ── 统一异常处理 ──
try:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": type(exc).__name__},
        )
except Exception:
    pass


def main():
    if not HAS_FASTAPI:
        print("FastAPI not installed. Run: pip install fastapi uvicorn pydantic")
        sys.exit(1)
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="info")


if __name__ == "__main__":
    main()
