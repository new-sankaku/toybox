"""Game Serverの起動Script

配信者PCのMic入力を判定し、OverlayとControl画面へWebSocketで配信する。

使用方法:
 python scripts/run_game.py
 python scripts/run_game.py --source-file data/probe/sample.wav

OBS Browser Source: http://127.0.0.1:8790/overlay.html
配信者用操作画面:   http://127.0.0.1:8790/
"""
import argparse
import sys
from pathlib import Path

BACKEND_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BACKEND_ROOT))

import uvicorn

from hayakuchi.config import load_game_config
from hayakuchi.dataset import load_phrases
from hayakuchi.engines import create_engine
from middleware.logger import get_logger,setup_logging
from server.app import create_app


def parse_args()->argparse.Namespace:
 parser=argparse.ArgumentParser(description="Hayakuchi game server")
 parser.add_argument("--config",default=str(BACKEND_ROOT/"config"/"game.yaml"))
 parser.add_argument("--source-file",default=None,help="Micの代わりにWAVを実時間で流す")
 parser.add_argument("--loop",action="store_true",help="WAVを繰り返し再生する")
 parser.add_argument("--host",default=None)
 parser.add_argument("--port",type=int,default=None)
 return parser.parse_args()


def main()->int:
 args=parse_args()
 config=load_game_config(Path(args.config))
 setup_logging(log_dir=str(config.log_dir),log_file="game.log")
 logger=get_logger()
 source=dict(config.source)
 if args.source_file is not None:
  source={"type":"file","path":args.source_file,"loop":args.loop}
 phrases=load_phrases(config.phrases_path)
 engine=create_engine(config.engine)
 logger.info(f"loading engine: {config.engine['id']}")
 engine.prepare()
 app=create_app(
  engine=engine,
  phrases=phrases,
  game_config=config.game,
  source_definition=source,
  web_root=config.web_root,
  base_dir=config.base_dir,
 )
 host=args.host or config.host
 port=args.port or config.port
 logger.info(f"overlay: http://{host}:{port}/overlay.html")
 logger.info(f"control: http://{host}:{port}/")
 uvicorn.run(app,host=host,port=port,log_config=None)
 return 0


if __name__=="__main__":
 sys.exit(main())
