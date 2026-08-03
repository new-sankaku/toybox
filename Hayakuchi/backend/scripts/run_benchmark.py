"""判定Engine Benchmarkの実行Script

使用方法:
 python scripts/run_benchmark.py
 python scripts/run_benchmark.py --engine ctc_ja --condition clean --limit 20
"""
import argparse
import sys
from pathlib import Path

BACKEND_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BACKEND_ROOT))

from hayakuchi.config import load_config
from hayakuchi.report import write_report
from hayakuchi.runner import run_benchmark
from middleware.logger import get_logger,setup_logging


def parse_args()->argparse.Namespace:
 parser=argparse.ArgumentParser(description="Hayakuchi judgement engine benchmark")
 parser.add_argument("--config",default=str(BACKEND_ROOT/"config"/"benchmark.yaml"))
 parser.add_argument("--engine",action="append",dest="engines")
 parser.add_argument("--condition",action="append",dest="conditions")
 parser.add_argument("--limit",type=int,default=None)
 parser.add_argument("--stem",default="benchmark")
 return parser.parse_args()


def main()->int:
 args=parse_args()
 config=load_config(Path(args.config))
 setup_logging(log_dir=str(config.log_dir),log_file="benchmark.log")
 logger=get_logger()
 try:
  result=run_benchmark(
   config,
   engine_ids=args.engines,
   condition_ids=args.conditions,
   limit=args.limit,
  )
 except Exception:
  logger.exception("benchmark failed")
  return 1
 written=write_report(result,config.output_dir,args.stem)
 logger.info(f"report written: {written['markdown']}")
 logger.info(f"result written: {written['json']}")
 return 0


if __name__=="__main__":
 sys.exit(main())
