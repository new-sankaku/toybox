import argparse
import os

try:
 from dotenv import load_dotenv
 load_dotenv()
except ImportError:
 pass

from config import get_config
from middleware.logger import setup_logging,get_logger


def main():
 config=get_config()

 parser=argparse.ArgumentParser(description='ToyBox Backend Server')
 parser.add_argument('--port',type=int,default=config.server.port,help='Port to run the server on')
 parser.add_argument('--host',type=str,default=config.server.host,help='Host to bind to')
 parser.add_argument('--debug',action='store_true',default=config.server.debug,help='Enable debug mode')
 parser.add_argument('--mode',type=str,choices=['testdata','api'],default=None,
         help='Agent mode (overrides AGENT_MODE env)')
 parser.add_argument('--reload',action='store_true',help='Enable auto-reload')

 args=parser.parse_args()

 if args.mode:
  os.environ['AGENT_MODE']=args.mode
  from config import reload_config
  reload_config()
  config=get_config()

 log_dir=os.path.join(os.path.dirname(__file__),"logs")
 logger=setup_logging(log_dir=log_dir,log_level=10 if args.debug else 20)

 logger.info("="*50)
 logger.info("  ToyBox Backend Server")
 logger.info("="*50)
 logger.info(f"  Host: {args.host}")
 logger.info(f"  Port: {args.port}")
 logger.info(f"  Agent Mode: {config.agent.mode}")
 logger.info(f"  Debug: {args.debug}")
 logger.info("="*50)

 import uvicorn
 uvicorn.run(
  "app:create_app",
  host=args.host,
  port=args.port,
  reload=args.reload or args.debug,
  factory=True,
  log_level="debug" if args.debug else"info",
 )


if __name__=='__main__':
 main()
