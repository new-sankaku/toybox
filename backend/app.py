import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from core.websocket import SocketManager
from core.dependencies import set_data_store, set_socket_manager
from middleware.logger import setup_logging, get_logger
from middleware.error_handler import register_fastapi_error_handlers
from config import get_config
from datastore import DataStore
from agents import create_agent_runner
from asset_scanner import get_testdata_path
from providers.health_monitor import get_health_monitor
from providers.registry import register_all_providers
from services.agent_execution_service import AgentExecutionService
from services.backup_service import BackupService
from services.archive_service import ArchiveService
from services.llm_job_queue import get_llm_job_queue
from services.recovery_service import RecoveryService


def create_app() -> FastAPI:
    config = get_config()

    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    logger = setup_logging(log_dir=log_dir, log_level=20 if not config.server.debug else 10)

    socket_manager = SocketManager()
    socket_manager.register_handlers()
    set_socket_manager(socket_manager)

    data_store = DataStore()
    data_store.set_socket_manager(socket_manager)
    set_data_store(data_store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting server initialization...")

        data_store.start_simulation()

        db_path = os.path.join(
            os.path.dirname(__file__), "data", "testdata.db" if config.agent.mode == "testdata" else "production.db"
        )
        backup_service = BackupService(db_path=db_path, max_backups=10)
        backup_service.create_startup_backup()
        archive_service = ArchiveService(retention_days=30)
        recovery_service = RecoveryService(data_store=data_store, socket_manager=socket_manager)
        recovery_result = recovery_service.recover_interrupted_agents()
        if recovery_result["recovered_agents"]:
            logger.info(f"Recovered {len(recovery_result['recovered_agents'])} interrupted agents")

        agent_runner = None
        agent_execution_service = AgentExecutionService(data_store, socket_manager)

        llm_job_queue = None
        if config.agent.mode == "api":
            agent_runner = create_agent_runner(
                mode=config.agent.mode,
                api_key=config.agent.anthropic_api_key,
                model=config.agent.model,
                max_tokens=config.agent.max_tokens,
            )
            if agent_runner:
                agent_runner.set_data_store(data_store)
                agent_execution_service.set_agent_runner(agent_runner)
                health_monitor = get_health_monitor()
                if hasattr(agent_runner, "set_health_monitor"):
                    agent_runner.set_health_monitor(health_monitor)
            llm_job_queue = get_llm_job_queue()
            llm_job_queue.start()
            logger.info("LLM Job Queue started")
        logger.info(f"Agent mode: {config.agent.mode}")

        register_all_providers()
        health_monitor = get_health_monitor()
        health_monitor.set_socket_manager(socket_manager)
        health_monitor.start()

        app.state.data_store = data_store
        app.state.socket_manager = socket_manager
        app.state.agent_runner = agent_runner
        app.state.agent_execution_service = agent_execution_service
        app.state.backup_service = backup_service
        app.state.archive_service = archive_service
        app.state.llm_job_queue = llm_job_queue
        app.state.recovery_service = recovery_service
        app.state.config = config

        logger.info("Server initialization completed")
        yield

        logger.info("Shutting down...")
        data_store.stop_simulation()
        if llm_job_queue:
            llm_job_queue.stop()
        health_monitor.stop()

    app = FastAPI(title="ToyBox Backend", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.server.cors_origins.split(",") if config.server.cors_origins != "*" else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_fastapi_error_handlers(app)

    from routers import (
        project,
        agent,
        checkpoint,
        metrics,
        quality_settings,
        static_config,
        auto_approval,
        intervention,
        file_upload,
        project_tree,
        ai_provider,
        ai_service,
        backup,
        admin,
        language,
        navigator,
        project_settings,
        brushup,
        trace,
        recovery,
        openapi_spec,
        health,
        archive,
        api_keys,
        llm_job,
        provider_health,
    )

    app.include_router(project.router, prefix="/api", tags=["projects"])
    app.include_router(agent.router, prefix="/api", tags=["agents"])
    app.include_router(checkpoint.router, prefix="/api", tags=["checkpoints"])
    app.include_router(metrics.router, prefix="/api", tags=["metrics"])
    app.include_router(quality_settings.router, prefix="/api", tags=["quality"])
    app.include_router(static_config.router, prefix="/api", tags=["config"])
    app.include_router(auto_approval.router, prefix="/api", tags=["approval"])
    app.include_router(intervention.router, prefix="/api", tags=["intervention"])
    app.include_router(file_upload.router, prefix="/api", tags=["files"])
    app.include_router(project_tree.router, prefix="/api", tags=["files"])
    app.include_router(ai_provider.router, prefix="/api", tags=["ai"])
    app.include_router(ai_service.router, prefix="/api", tags=["ai"])
    app.include_router(backup.router, prefix="/api", tags=["backup"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(language.router, prefix="/api", tags=["i18n"])
    app.include_router(navigator.router, prefix="/api", tags=["navigator"])
    app.include_router(project_settings.router, prefix="/api", tags=["settings"])
    app.include_router(brushup.router, prefix="/api", tags=["brushup"])
    app.include_router(trace.router, prefix="/api", tags=["trace"])
    app.include_router(recovery.router, prefix="/api", tags=["recovery"])
    app.include_router(openapi_spec.router, prefix="/api", tags=["openapi"])
    app.include_router(health.router, tags=["health"])
    app.include_router(archive.router, prefix="/api", tags=["archive"])
    app.include_router(api_keys.router, prefix="/api", tags=["api-keys"])
    app.include_router(llm_job.router, prefix="/api", tags=["llm-jobs"])
    app.include_router(provider_health.router, prefix="/api", tags=["providers"])

    testdata_path = get_testdata_path()
    if os.path.exists(testdata_path):
        app.mount("/testdata", StaticFiles(directory=testdata_path), name="testdata")

    app.mount("/socket.io", socket_manager.get_app())

    return app
