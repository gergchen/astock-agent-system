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

setup_logging()
logger = get_logger("api_server")

# ── 尝试导入 FastAPI ──
try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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


# ── 初始化 ──
def init_app():
    config = get_config()
    registry = AgentRegistry.get_instance()
    session_mgr = SessionManager.get_instance()

    # 根据配置创建 broker
    broker = None
    if config.broker_type == "ths":
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


# ── 健康检查 ──
@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "agents": len(registry.list_all()),
        "tenants": len(tenant_mgr.list_all()),
        "timestamp": datetime.now().isoformat(),
    }


# ── 根路径 — 状态页 ──
@app.get("/")
def root():
    return {
        "service": "Managed Agents API",
        "version": "0.2.0",
        "status": "running",
        "endpoints": {
            "health": "GET /api/v1/health",
            "tenants": "GET/POST /api/v1/tenants",
            "agents": "GET /api/v1/agents",
            "sessions": "POST /api/v1/sessions",
            "session_detail": "GET /api/v1/sessions/{id}",
            "session_history": "GET /api/v1/sessions/{id}/history",
            "team_cycle": "POST /api/v1/team/cycle",
            "ws_alerts": "WS /api/v1/ws/alerts",
            "docs": "GET /docs",
        },
        "timestamp": datetime.now().isoformat(),
    }


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
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")


if __name__ == "__main__":
    main()
