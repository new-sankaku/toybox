"""Local Server

Overlay（OBS Browser Source）とControl（配信者用操作画面）へWebSocketでEventを配る。
外部Serviceへは一切接続しない。
"""
import asyncio
import json
from pathlib import Path
from typing import Dict,List,Optional,Set

from fastapi import FastAPI,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hayakuchi.audio_source import create_source
from hayakuchi.dataset import Phrase
from hayakuchi.game import GameConfig,GameSession
from middleware.logger import get_logger


class Broadcaster:
 """接続中のClientへEventを配る"""

 def __init__(self):
  self._clients:Set[WebSocket]=set()
  self._lock=asyncio.Lock()

 async def add(self,client:WebSocket)->None:
  async with self._lock:
   self._clients.add(client)

 async def remove(self,client:WebSocket)->None:
  async with self._lock:
   self._clients.discard(client)

 async def publish(self,event:BaseModel)->None:
  payload=event.model_dump(mode="json")
  async with self._lock:
   targets=list(self._clients)
  for client in targets:
   try:
    await client.send_json(payload)
   except (WebSocketDisconnect,RuntimeError):
    await self.remove(client)


def create_app(
 engine,
 phrases:Dict[str,Phrase],
 game_config:GameConfig,
 source_definition:Dict,
 web_root:Path,
 base_dir:Path,
 profile_path:Path,
)->FastAPI:
 """Game Sessionを内包したApplicationを組み立てる"""
 logger=get_logger()
 broadcaster=Broadcaster()
 session=GameSession(engine,phrases,game_config,broadcaster.publish,profile_path)
 app=FastAPI(title="Hayakuchi")
 app.state.session=session

 @app.on_event("startup")
 async def startup()->None:
  frame_size=int(game_config.sample_rate*game_config.vad.frame_ms/1000.0)
  source=create_source(source_definition,game_config.sample_rate,frame_size,base_dir)
  await session.select()
  app.state.loop_task=asyncio.create_task(_run(source))
  logger.info(f"game loop started with source={source_definition.get('type')}")

 async def _run(source)->None:
  try:
   await session.run(source)
  except asyncio.CancelledError:
   raise
  except Exception:
   logger.exception("game loop stopped")

 @app.on_event("shutdown")
 async def shutdown()->None:
  task=getattr(app.state,"loop_task",None)
  if task is not None:
   task.cancel()

 @app.get("/api/phrases")
 async def list_phrases()->List[Dict]:
  return [
   {
    "phrase_id":phrase.id,
    "display":phrase.display,
    "difficulty":phrase.difficulty,
    "mora_count":len(phrase.mora),
   }
   for phrase in sorted(phrases.values(),key=lambda item:(item.difficulty,item.id))
  ]

 @app.websocket("/ws")
 async def websocket(client:WebSocket)->None:
  await client.accept()
  await broadcaster.add(client)
  for event in session.snapshot():
   await client.send_json(event.model_dump(mode="json"))
  try:
   while True:
    command=json.loads(await client.receive_text())
    await _handle(command)
  except WebSocketDisconnect:
   await broadcaster.remove(client)
  except Exception:
   logger.exception("websocket handler failed")
   await broadcaster.remove(client)

 async def _handle(command:Dict)->None:
  kind=command.get("type")
  if kind=="select":
   await session.select(command.get("phrase_id"))
  elif kind=="override":
   await session.override(bool(command["passed"]))
  elif kind=="retry":
   await session.retry()
  elif kind=="giveup":
   await session.give_up()
  else:
   raise ValueError(f"unknown command: {kind}")

 @app.get("/")
 async def index()->FileResponse:
  return FileResponse(web_root/"control.html")

 app.mount("/",StaticFiles(directory=str(web_root),html=True),name="web")
 return app
