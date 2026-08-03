import os
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Optional

_logger:Optional[logging.Logger]=None
_initialized=False


def setup_logging(
 log_dir:str="logs",
 log_level:int=logging.INFO,
 log_file:str="hayakuchi.log",
 backup_count:int=7,
 rotation_when:str="midnight",
)->logging.Logger:
 """Logger初期化。File出力とConsole出力を併用する"""
 global _logger,_initialized
 if _initialized and _logger:
  return _logger
 Path(log_dir).mkdir(parents=True,exist_ok=True)
 logger=logging.getLogger("hayakuchi")
 logger.setLevel(log_level)
 if logger.handlers:
  logger.handlers.clear()
 log_format=logging.Formatter(
  "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s",
  datefmt="%Y-%m-%d %H:%M:%S"
 )
 log_path=os.path.join(log_dir,log_file)
 file_handler=TimedRotatingFileHandler(
  log_path,
  when=rotation_when,
  interval=1,
  backupCount=backup_count,
  encoding="utf-8"
 )
 file_handler.setLevel(log_level)
 file_handler.setFormatter(log_format)
 logger.addHandler(file_handler)
 console_handler=logging.StreamHandler()
 console_handler.setLevel(log_level)
 console_handler.setFormatter(log_format)
 logger.addHandler(console_handler)
 _logger=logger
 _initialized=True
 logger.info(f"Logging initialized: {log_path}")
 return logger


def get_logger()->logging.Logger:
 """初期化済みLoggerを取得する"""
 global _logger
 if _logger is None:
  return setup_logging()
 return _logger
