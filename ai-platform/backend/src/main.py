"""
FastAPI 应用入口。

初始化 Agent Core 后端服务，包含：
- 结构化 JSON 日志（structlog）
- CORS 中间件
- 健康检查端点
- API 路由注册（后续任务中扩展）
- 后台服务的启动/关闭生命周期管理
"""

from __future__ import annotations
from typing import Any

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import get_settings
from src.utils.logging import configure_logging

# ===== 生命周期管理 =====


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    应用生命周期上下文管理器。

    处理后台服务的启动和关闭，包括：
    - 数据库连接池初始化
    - Redis 连接
    - Qdrant 客户端
    - APScheduler（推送调度、记忆遗忘）
    - ConfigWatcher（热重载）
    """
    settings: Settings = get_settings()
    logger: structlog.stdlib.BoundLogger = structlog.get_logger("lifespan")

    logger.info(
        "Application starting",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT.value,
    )

    # --- 启动阶段 ---
    # 初始化数据库
    from src.db.session import close_db, init_db

    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.warning("Database init deferred", error=str(exc))

    # 初始化 LLM Gateway
    from src.llm.gateway import get_llm_gateway

    try:
        gateway: LLMGateway = get_llm_gateway()
        gateway.initialize()
        logger.info("LLM Gateway initialized")
    except Exception as exc:
        logger.warning("LLM Gateway init deferred", error=str(exc))

    # 注册 Agent 运行时工厂（OpenHarness 等）
    try:
        from src.runtime.factory import register_default_runtimes

        register_default_runtimes()
        logger.info("Runtime factories registered")
    except Exception as exc:
        logger.warning("Runtime factory registration deferred", error=str(exc))

    # 初始化 ConfigManager
    from src.config_manager.manager import get_config_manager

    try:
        config_manager: ConfigManager = get_config_manager()
        await config_manager.initialize()
        logger.info("ConfigManager initialized")

        # 注册配置变更回调以更新 AgentRouter
        from src.router.agent_router import get_agent_router

        router: AgentRouter = get_agent_router()

        async def on_config_change(agent_id: str, change_type: str, config: Any) -> None:
            """配置变更时更新 AgentRouter 候选列表。"""
            if change_type == "deleted":
                router.remove_candidate(agent_id)
            elif config is not None:
                router.add_candidate(config)

        config_manager.on_config_change(on_config_change)

        # 设置初始路由候选项
        configs: dict[str, Any] = config_manager.list_configs()
        router.set_candidates(configs)
        logger.info("AgentRouter candidates set", count=len(configs))
    except Exception as exc:
        logger.warning("ConfigManager init deferred", error=str(exc))

    # 初始化 PushScheduler
    try:
        from src.push.scheduler import get_push_scheduler

        push_scheduler: PushScheduler = get_push_scheduler()
        await push_scheduler.start()
        logger.info("PushScheduler started")
    except Exception as exc:
        logger.warning("PushScheduler init deferred", error=str(exc))

    # 初始化 HITL 审批超时检查器
    try:
        from src.hitl.approval import get_approval_manager

        approval_manager: ApprovalManager = get_approval_manager()
        # 执行初始超时检查
        await approval_manager.check_timeouts()
        logger.info("HITL ApprovalManager initialized")
    except Exception as exc:
        logger.warning("HITL ApprovalManager init deferred", error=str(exc))

    # 从配置文件初始化 Skills 注册表和 MCP 管理器
    try:
        from src.bootstrap.skills_mcp import initialize_skills_and_mcp

        skills_mcp_stats: dict[str, Any] = await initialize_skills_and_mcp()
        logger.info("Skills and MCP initialized", **skills_mcp_stats)
    except Exception as exc:
        logger.warning("Skills/MCP init deferred", error=str(exc))

    # 同步从已加载配置中同步 Agent 实例（Skills/MCP 必须先就绪）
    try:
        from src.agent.manager import get_agent_manager
        from src.config_manager.manager import get_config_manager
        from src.llm.gateway import get_llm_gateway

        agent_manager: AgentManager = get_agent_manager()
        agent_manager.set_llm_gateway(get_llm_gateway())
        config_manager: ConfigManager = get_config_manager()
        synced: int = await agent_manager.sync_from_configs(config_manager.list_configs())
        logger.info("Agents synced from configs", count=synced)
    except Exception as exc:
        logger.warning("Agent sync deferred", error=str(exc))

    # 启动 Redis Stream 入站消费者（Gateway → Agent Core）
    try:
        from src.agent.manager import get_agent_manager
        from src.queue.inbound_worker import start_inbound_stream_worker

        agent_manager: AgentManager = get_agent_manager()
        agent_ids: list[Any] = [inst.id for inst in agent_manager.list_agents()]
        await start_inbound_stream_worker(agent_ids)
        logger.info("Inbound stream worker started", agent_streams=agent_ids)
    except Exception as exc:
        logger.warning("Inbound stream worker start deferred", error=str(exc))

    logger.info("Startup phase complete")

    yield

    # --- 关闭阶段 ---
    logger.info("Application shutting down")

    try:
        from src.queue.inbound_worker import stop_inbound_stream_worker

        await stop_inbound_stream_worker()
    except Exception as exc:
        logger.warning("Inbound stream worker shutdown error", error=str(exc))

    try:
        from src.bootstrap.skills_mcp import shutdown_skills_and_mcp

        await shutdown_skills_and_mcp()
    except Exception as exc:
        logger.warning("Skills/MCP shutdown error", error=str(exc))

    # 关闭 PushScheduler
    try:
        from src.push.scheduler import get_push_scheduler

        await get_push_scheduler().stop()
    except Exception as exc:
        logger.warning("PushScheduler shutdown error", error=str(exc))

    # 关闭 ConfigManager（停止 ConfigWatcher）
    try:
        from src.config_manager.manager import get_config_manager

        await get_config_manager().shutdown()
    except Exception as exc:
        logger.warning("ConfigManager shutdown error", error=str(exc))

    # 关闭所有 Agent 实例
    try:
        from src.agent.manager import get_agent_manager

        await get_agent_manager().shutdown_all()
    except Exception as exc:
        logger.warning("AgentManager shutdown error", error=str(exc))

    # 关闭数据库连接
    try:
        await close_db()
    except Exception as exc:
        logger.warning("Database close error", error=str(exc))

    logger.info("Shutdown complete")


# ===== 应用工厂 =====


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings: Settings = get_settings()

    # 配置日志
    configure_logging()

    app: FastAPI = FastAPI(
        title="AI Platform — Agent Core",
        description="企业内部 AI 平台后端服务 — Agent 生命周期管理、智能路由、LLM 网关、Skills 调度",
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ===== CORS =====
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ===== Trace ID 中间件 =====
    @app.middleware("http")
    async def add_trace_id(request: Request, call_next: Any) -> Any:
        """为每个请求注入 traceId 以支持分布式追踪。"""
        import uuid

        trace_id: Skill | None = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            service=settings.APP_NAME,
        )
        response: Any = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    # ===== 健康检查端点 =====
    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        """存活探针 —— 若进程运行中则返回 200。"""
        return {"status": "ok", "service": settings.APP_NAME}

    @app.get("/ready", tags=["system"])
    async def readiness_check() -> JSONResponse:
        """
        就绪探针 —— 检查依赖项连接性。

        若所有依赖项（PostgreSQL、Redis、Qdrant）均可达则返回 200；
        否则返回 503。
        """
        checks: dict[str, str] = {}
        all_healthy: bool = True

        # PostgreSQL 检查
        try:
            from sqlalchemy import text

            from src.db.session import get_engine

            engine: AsyncEngine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception:
            checks["postgres"] = "error"
            all_healthy: bool = False

        # Redis 检查
        try:
            import redis.asyncio as aioredis

            redis_client: Any = aioredis.from_url(settings.redis_url)
            await redis_client.ping()
            await redis_client.close()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
            all_healthy: bool = False

        # Qdrant 检查
        try:
            from qdrant_client import QdrantClient

            qdrant: QdrantClient = QdrantClient(url=settings.qdrant_url)
            qdrant.get_collections()
            checks["qdrant"] = "ok"
        except Exception:
            checks["qdrant"] = "error"
            all_healthy: bool = False

        http_status: Any = (
            status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return JSONResponse(
            status_code=http_status,
            content={
                "status": "ready" if all_healthy else "not_ready",
                "checks": checks,
            },
        )

    # ===== API 路由 =====
    from src.api.routes.admin import router as admin_router
    from src.api.routes.agent import router as agent_router
    from src.api.routes.auth import router as auth_router
    from src.api.routes.mcp import router as mcp_router
    from src.api.routes.push import router as push_router
    from src.api.routes.session import router as session_router
    from src.api.routes.skill import router as skill_router

    app.include_router(agent_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(session_router, prefix="/api/v1")
    app.include_router(skill_router, prefix="/api/v1/skills", tags=["skills"])
    app.include_router(mcp_router, prefix="/api/v1/mcp", tags=["mcp"])
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(push_router, prefix="/api/v1")

    # ===== 统一 API 响应格式 =====
    # 所有 API 响应遵循：{ code, data, message, traceId }

    return app


# ===== 创建应用实例 =====
app = create_app()


def main() -> None:
    """使用 uvicorn 运行应用（用于直接 python 执行）。"""
    import uvicorn

    settings: Settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS if not settings.DEBUG else 1,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.value.lower(),
    )


if __name__ == "__main__":
    main()
