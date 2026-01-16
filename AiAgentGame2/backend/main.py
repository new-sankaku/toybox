#!/usr/bin/env python3
"""
AiAgentGame2 Mock Backend Server
LLM連携なしでフロントエンドとのI/F確認用
"""

# eventlet monkey_patch must be called before any other imports
import eventlet
eventlet.monkey_patch()

import argparse
import sys
from server import create_app, run_server


def main():
    parser = argparse.ArgumentParser(description='AiAgentGame2 Mock Backend Server')
    parser.add_argument('--port', type=int, default=8765, help='Port to run the server on')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    print(f"Starting AiAgentGame2 Mock Backend on {args.host}:{args.port}")

    app, socketio = create_app()
    run_server(app, socketio, host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()
