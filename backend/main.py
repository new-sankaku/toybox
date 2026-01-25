

import eventlet
eventlet.monkey_patch()

import argparse
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from server import create_app,run_server
from config import get_config


def main():
    config=get_config()

    parser=argparse.ArgumentParser(description='AiAgentGame2 Backend Server')
    parser.add_argument('--port',type=int,default=config.server.port,help='Port to run the server on')
    parser.add_argument('--host',type=str,default=config.server.host,help='Host to bind to')
    parser.add_argument('--debug',action='store_true',default=config.server.debug,help='Enable debug mode')
    parser.add_argument('--mode',type=str,choices=['testdata','api'],default=None,
                        help='Agent mode (overrides AGENT_MODE env)')

    args=parser.parse_args()

    if args.mode:
        os.environ['AGENT_MODE']=args.mode
        from config import reload_config
        reload_config()
        config=get_config()

    print("="*50)
    print("  AiAgentGame2 Backend Server")
    print("="*50)
    print(f"  Host: {args.host}")
    print(f"  Port: {args.port}")
    print(f"  Agent Mode: {config.agent.mode}")
    print(f"  Debug: {args.debug}")
    print("="*50)

    app,socketio=create_app()
    run_server(app,socketio,host=args.host,port=args.port,debug=args.debug)


if __name__=='__main__':
    main()
