import os
from flask import Flask,send_from_directory,abort
from flask_cors import CORS
import socketio

from handlers.project import register_project_routes
from handlers.agent import register_agent_routes
from handlers.checkpoint import register_checkpoint_routes
from handlers.metrics import register_metrics_routes
from handlers.websocket import register_websocket_handlers
from handlers.quality_settings import register_quality_settings_routes
from handlers.static_config import register_static_config_routes
from handlers.auto_approval import register_auto_approval_routes
from handlers.intervention import register_intervention_routes
from handlers.file_upload import register_file_upload_routes
from handlers.project_tree import register_project_tree_routes
from handlers.ai_provider import register_ai_provider_routes
from handlers.ai_service import register_ai_service_routes
from handlers.backup import register_backup_routes
from handlers.admin import register_admin_routes
from providers.health_monitor import get_health_monitor
from providers.registry import register_all_providers
from handlers.language import register_language_routes
from handlers.navigator import register_navigator_routes
from handlers.project_settings import register_project_settings_routes
from handlers.brushup import register_brushup_routes
from handlers.trace import register_trace_routes
from handlers.recovery import register_recovery_routes
from handlers.openapi import register_openapi_routes
from handlers.system_prompt import register_system_prompt_routes
from handlers.global_cost_settings import register_global_cost_settings_routes
from handlers.cost_reports import register_cost_reports_routes
from container import Container
from models.database import init_db
from config import get_config
from agents import create_agent_runner
from asset_scanner import get_testdata_path
from middleware.error_handler import register_error_handlers
from middleware.rate_limiter import init_rate_limiter
from middleware.logger import setup_logging,get_logger
from services.llm_job_queue import get_llm_job_queue


def create_app():
    config=get_config()
    app=Flask(__name__)
    app.config['MAX_CONTENT_LENGTH']=4*1024*1024*1024
    CORS(app,origins=config.server.cors_origins)

    log_dir=os.path.join(os.path.dirname(__file__),"logs")
    logger=setup_logging(log_dir=log_dir,log_level=20 if not config.server.debug else 10)
    logger.info("Starting server initialization...")

    register_error_handlers(app)
    init_rate_limiter(app,default_limit=120,default_window=60)

    sio=socketio.Server(
        cors_allowed_origins=config.server.cors_origins,
        async_mode='eventlet',
        logger=config.server.debug,
        engineio_logger=False
    )

    app_wsgi=socketio.WSGIApp(sio,app)

    db_path=os.path.join(os.path.dirname(__file__),"data","testdata.db" if config.agent.mode=="testdata" else"production.db")

    container=Container()
    container.db_path.override(db_path)
    container.sio.override(sio)
    event_bus=container.event_bus()
    websocket_emitter=container.websocket_emitter()
    websocket_emitter.set_sio(sio)

    init_db()
    container.project_service().init_sample_data_if_empty()
    container.simulation_service().start_simulation()

    app.config['DB_PATH']=db_path
    backup_service=container.backup_service()
    backup_service.create_startup_backup()
    archive_service=container.archive_service()
    recovery_service=container.recovery_service()
    recovery_result=recovery_service.recover_interrupted_agents()
    if recovery_result["recovered_agents"]:
        logger.info(f"Recovered {len(recovery_result['recovered_agents'])} interrupted agents")

    agent_runner=None
    agent_execution_service=container.agent_execution_service()

    llm_job_queue=None
    if config.agent.mode=="api":
        agent_runner=create_agent_runner(
            mode=config.agent.mode,
            api_key=config.agent.anthropic_api_key,
            model=config.agent.model,
            max_tokens=config.agent.max_tokens,
        )
        if agent_runner:
            agent_runner.set_services(container.trace_service(),container.agent_service())
            agent_execution_service.set_agent_runner(agent_runner)
            health_monitor=get_health_monitor()
            if hasattr(agent_runner,'set_health_monitor'):
                agent_runner.set_health_monitor(health_monitor)
        llm_job_queue=get_llm_job_queue()
        llm_job_queue.start()
        logger.info("LLM Job Queue started")
    logger.info(f"Agent mode: {config.agent.mode}")

    register_project_routes(app,container.project_service(),container.agent_service(),event_bus)
    register_agent_routes(app,container.project_service(),container.agent_service(),container.trace_service(),event_bus)
    register_checkpoint_routes(app,container.project_service(),container.workflow_service())
    register_metrics_routes(app,container.project_service(),container.agent_service(),container.workflow_service(),event_bus)
    register_quality_settings_routes(app,container.project_service(),container.workflow_service())
    register_static_config_routes(app)
    register_auto_approval_routes(app,container.project_service(),container.workflow_service())
    register_intervention_routes(app,container.project_service(),container.agent_service(),container.intervention_service(),event_bus)
    register_websocket_handlers(sio,container.project_service(),container.agent_service(),container.workflow_service(),container.intervention_service(),container.subscription_manager())
    register_navigator_routes(app,sio)


    upload_folder=os.path.join(os.path.dirname(__file__),'uploads')
    output_folder=os.path.join(os.path.dirname(__file__),'outputs')
    register_file_upload_routes(app,container.project_service(),container.intervention_service(),upload_folder)
    register_project_tree_routes(app,container.project_service(),output_folder)
    register_ai_provider_routes(app)
    register_ai_service_routes(app)
    register_language_routes(app)
    register_backup_routes(app,backup_service,archive_service)
    register_admin_routes(app,backup_service,archive_service)

    register_all_providers()
    health_monitor=get_health_monitor()
    health_monitor.set_socketio(sio)
    health_monitor.start()
    register_project_settings_routes(app,container.project_service())
    register_brushup_routes(app,container.project_service(),sio)
    register_trace_routes(app,container.project_service(),container.agent_service(),container.trace_service(),sio)
    register_recovery_routes(app,container.agent_service())
    register_openapi_routes(app)
    register_system_prompt_routes(app,container.project_service(),container.agent_service(),container.trace_service())
    register_global_cost_settings_routes(app,sio)
    register_cost_reports_routes(app)

    @app.route('/health')
    def health():
        return {
            'status':'ok',
            'service':'aiagentgame2-backend',
            'agent_mode':config.agent.mode,
        }

    @app.route('/api/system/stats',methods=['GET'])
    def system_stats():
        from middleware.rate_limiter import get_limiter
        limiter=get_limiter()
        return {
            'backup_info':backup_service.get_backup_info(),
            'archive_stats':archive_service.get_data_statistics(),
            'rate_limiter':limiter.get_stats() if limiter else {},
        }

    testdata_path=get_testdata_path()

    @app.route('/testdata/<path:filepath>')
    def serve_testdata(filepath):
        try:
            return send_from_directory(testdata_path,filepath)
        except Exception as e:
            logger.error(f"Error serving {filepath}: {e}")
            abort(404)

    app.agent_runner=agent_runner
    app.agent_execution_service=agent_execution_service
    app.backup_service=backup_service
    app.archive_service=archive_service
    app.llm_job_queue=llm_job_queue
    app.recovery_service=recovery_service
    app.config_obj=config
    app.sio=sio
    app.wsgi_app_wrapper=app_wsgi
    app.container=container

    logger.info("Server initialization completed")
    return app,sio


def run_server(app,sio,host='127.0.0.1',port=8765,debug=False):
    import eventlet

    logger=get_logger()
    logger.info(f"Server running at http://{host}:{port}")
    logger.info(f"WebSocket available at ws://{host}:{port}")

    listener=eventlet.listen((host,port))
    eventlet.wsgi.server(listener,app.wsgi_app_wrapper,log_output=debug)
