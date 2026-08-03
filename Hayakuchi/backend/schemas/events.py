"""OverlayとControl画面へ配信するEventの定義

WebSocketで流れる型はここに集約する。Overlay側のRender処理はこの定義にのみ依存する。
"""
from enum import Enum
from typing import Dict,List,Optional

from pydantic import BaseModel,Field

EVENT_STATE="state"
EVENT_PHRASE="phrase"
EVENT_PROGRESS="progress"
EVENT_RESULT="result"
EVENT_LEVEL="level"
EVENT_PROFILE="profile"


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
 mora_display:List[str]
 difficulty:int


class ProgressEvent(BaseModel):
 type:str=EVENT_PROGRESS
 lit_mora:int
 mora_states:List[MoraState]
 first_error_mora:Optional[int]=None
 combo:int=0
 restarted:bool=False
 hesitating:bool=False
 elapsed_ms:float=0.0


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
 streak:int=0
 score:int=0
 breakdown:Dict[str,float]=Field(default_factory=dict)
 max_combo:int=0
 restarts:int=0
 abandoned:bool=False
 best_score:int=0
 levels_gained:int=0
 overridden:bool=False


class ProfileEvent(BaseModel):
 type:str=EVENT_PROFILE
 level:int
 exp:int
 exp_to_next:int
 total_score:int
 plays:int
 clears:int
 unlocked_difficulty:int


class LevelEvent(BaseModel):
 type:str=EVENT_LEVEL
 level_db:float
 floor_db:float
 speaking:bool
 envelope:List[float]=Field(default_factory=list)


class SelectCommand(BaseModel):
 type:str="select"
 phrase_id:str


class StartCommand(BaseModel):
 type:str="start"


class OverrideCommand(BaseModel):
 type:str="override"
 passed:bool


class RetryCommand(BaseModel):
 type:str="retry"


class GiveUpCommand(BaseModel):
 type:str="giveup"
