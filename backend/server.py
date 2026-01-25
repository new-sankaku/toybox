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
from providers.health_monitor import get_health_monitor
from providers.registry import register_all_providers
from handlers.language import register_language_routes
from handlers.navigator import register_navigator_routes
from handlers.project_settings import register_project_settings_routes
from handlers.brushup import register_brushup_routes
from handlers.trace import register_trace_routes
from datastore import DataStore
from config import get_config
from agents import create_agent_runner
from asset_scanner import get_testdata_path


def create_app():
    config=get_config()
    app=Flask(__name__)
    CORS(app,origins=config.server.cors_origins)

    sio=socketio.Server(
        cors_allowed_origins=config.server.cors_origins,
        async_mode='eventlet',
        logger=config.server.debug,
        engineio_logger=False
    )

    app_wsgi=socketio.WSGIApp(sio,app)
    data_store=DataStore()
    data_store.set_sio(sio)
    data_store.start_simulation()


    agent_runner=None
    if config.agent.mode=="api":
        agent_runner=create_agent_runner(
            mode=config.agent.mode,
            api_key=config.agent.anthropic_api_key,
            model=config.agent.model,
            max_tokens=config.agent.max_tokens,
        )
        if agent_runner and hasattr(agent_runner,'set_data_store'):
            agent_runner.set_data_store(data_store)

    register_project_routes(app,data_store,sio)
    register_agent_routes(app,data_store,sio)
    register_checkpoint_routes(app,data_store,sio)
    register_metrics_routes(app,data_store)
    register_quality_settings_routes(app,data_store)
    register_static_config_routes(app)
    register_auto_approval_routes(app,data_store)
    register_intervention_routes(app,data_store,sio)
    register_websocket_handlers(sio,data_store)
    register_navigator_routes(app,sio)


    upload_folder=os.path.join(os.path.dirname(__file__),'uploads')
    output_folder=os.path.join(os.path.dirname(__file__),'outputs')
    register_file_upload_routes(app,data_store,upload_folder)
    register_project_tree_routes(app,data_store,output_folder)
    register_ai_provider_routes(app)
    register_ai_service_routes(app)
    register_language_routes(app)

    register_all_providers()
    health_monitor=get_health_monitor()
    health_monitor.set_socketio(sio)
    health_monitor.start()
    register_project_settings_routes(app,data_store)
    register_brushup_routes(app,data_store,sio)
    register_trace_routes(app,data_store,sio)

    @app.route('/health')
    def health():
        return {
            'status':'ok',
            'service':'aiagentgame2-backend',
            'agent_mode':config.agent.mode,
        }

    testdata_path=get_testdata_path()

    @app.route('/testdata/<path:filepath>')
    def serve_testdata(filepath):
        try:
            return send_from_directory(testdata_path,filepath)
        except Exception as e:
            print(f"[Server] Error serving {filepath}: {e}")
            abort(404)

    app.data_store=data_store
    app.agent_runner=agent_runner
    app.config_obj=config
    app.sio=sio
    app.wsgi_app_wrapper=app_wsgi

    return app,sio


def run_server(app,sio,host='127.0.0.1',port=8765,debug=False):
    import eventlet

    print(f"Server running at http://{host}:{port}")
    print(f"WebSocket available at ws://{host}:{port}")

    listener=eventlet.listen((host,port))
    eventlet.wsgi.server(listener,app.wsgi_app_wrapper,log_output=debug)
