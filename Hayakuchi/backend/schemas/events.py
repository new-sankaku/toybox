"""OverlayとControl画面へ配信するEventの定義

WebSocketで流れる型はここに集約する。Overlay側のRender処理はこの定義にのみ依存する。
"""
from enum import Enum
from typing import List,Optional

from pydantic import BaseModel,Field

EVENT_STATE="state"
EVENT_PHRASE="phrase"
EVENT_PROGRESS="progress"
EVENT_RESULT="result"
EVENT_LEVEL="level"


class Phase(str,Enum):
 IDLE="idle"
 READY="ready"
 LISTENING="listening"
 RESULT="result"


class MoraState(str,Enum):
 OK="ok"
 ERROR="error"
 PENDING="pending"


class StateEvent(BaseModel):
 type:str=EVENT_STATE
 phase:Phase


class PhraseEvent(BaseModel):
 type:str=EVENT_PHRASE
 phrase_id:str
 display:str
 mora:List[str]
 difficulty:int


class ProgressEvent(BaseModel):
 type:str=EVENT_PROGRESS
 lit_mora:int
 mora_states:List[MoraState]
 first_error_mora:Optional[int]=None
 elapsed_ms:float


class ResultEvent(BaseModel):
 type:str=EVENT_RESULT
 phrase_id:str
 passed:bool
 grade:str
 accuracy:float=Field(ge=0.0,le=1.0)
 duration_ms:float
 mora_states:List[MoraState]
 first_error_mora:Optional[int]=None
 reference:str
 hypothesis:str
 overridden:bool=False


class LevelEvent(BaseModel):
 type:str=EVENT_LEVEL
 level_db:float
 floor_db:float
 speaking:bool


class SelectCommand(BaseModel):
 type:str="select"
 phrase_id:str


class StartCommand(BaseModel):
 type:str="start"


class OverrideCommand(BaseModel):
 type:str="override"
 passed:bool
