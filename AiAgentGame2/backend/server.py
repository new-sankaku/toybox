"""
Flask + Socket.IO Server
"""

from flask import Flask
from flask_cors import CORS
import socketio

from handlers.project import register_project_routes
from handlers.agent import register_agent_routes
from handlers.checkpoint import register_checkpoint_routes
from handlers.metrics import register_metrics_routes
from handlers.websocket import register_websocket_handlers
from mock_data import MockDataStore


def create_app():
    """Create and configure Flask app with Socket.IO"""

    # Flask app
    app = Flask(__name__)
    CORS(app, origins="*")

    # Socket.IO server with CORS
    sio = socketio.Server(
        cors_allowed_origins="*",
        async_mode='eventlet',
        logger=True,
        engineio_logger=False
    )

    # Wrap Flask app with Socket.IO
    app_wsgi = socketio.WSGIApp(sio, app)

    # Initialize mock data store
    data_store = MockDataStore()

    # Register REST API routes
    register_project_routes(app, data_store, sio)
    register_agent_routes(app, data_store, sio)
    register_checkpoint_routes(app, data_store, sio)
    register_metrics_routes(app, data_store)

    # Register WebSocket handlers
    register_websocket_handlers(sio, data_store)

    # Health check endpoint
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'aiagentgame2-mock-backend'}

    # Store references
    app.data_store = data_store
    app.sio = sio
    app.wsgi_app_wrapper = app_wsgi

    return app, sio


def run_server(app, sio, host='127.0.0.1', port=8765, debug=False):
    """Run the server with eventlet"""
    import eventlet

    print(f"Server running at http://{host}:{port}")
    print(f"WebSocket available at ws://{host}:{port}")

    listener = eventlet.listen((host, port))
    eventlet.wsgi.server(listener, app.wsgi_app_wrapper, log_output=debug)
