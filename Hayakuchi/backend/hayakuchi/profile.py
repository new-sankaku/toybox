"""Levelと累計成績の保存

配信をまたいで積み上がることが、繰り返し使う理由になる。
保存先はLocalのJSONのみで、外部へは送信しない。
"""
import json
from dataclasses import asdict,dataclass,field
from pathlib import Path
from typing import Dict,Optional


@dataclass
class LevelRules:
 base_exp:int=400
 exponent:float=1.35
 unlock_every:int=3
 max_difficulty:int=5

 @classmethod
 def from_dict(cls,data:Optional[Dict])->"LevelRules":
  data=data or {}
  default=cls()
  return cls(
   base_exp=int(data.get("base_exp",default.base_exp)),
   exponent=float(data.get("exponent",default.exponent)),
   unlock_every=int(data.get("unlock_every",default.unlock_every)),
   max_difficulty=int(data.get("max_difficulty",default.max_difficulty)),
  )


@dataclass
class Profile:
 level:int=1
 exp:int=0
 total_score:int=0
 plays:int=0
 clears:int=0
 best_scores:Dict[str,int]=field(default_factory=dict)


def required_exp(level:int,rules:LevelRules)->int:
 """次のLevelまでに必要な経験値"""
 if level<1:
  raise ValueError("level must be positive")
 return int(round(rules.base_exp*level**rules.exponent))


def unlocked_difficulty(level:int,rules:LevelRules)->int:
 """現在のLevelで出題できる最大難易度"""
 if rules.unlock_every<=0:
  return rules.max_difficulty
 return min(rules.max_difficulty,1+(level-1)//rules.unlock_every)


def apply_result(
 profile:Profile,
 phrase_id:str,
 score:int,
 cleared:bool,
 rules:LevelRules,
)->int:
 """得点を反映し、上がったLevel数を返す"""
 profile.plays+=1
 profile.total_score+=score
 profile.exp+=score
 if cleared:
  profile.clears+=1
 if score>profile.best_scores.get(phrase_id,0):
  profile.best_scores[phrase_id]=score
 gained=0
 while profile.exp>=required_exp(profile.level,rules):
  profile.exp-=required_exp(profile.level,rules)
  profile.level+=1
  gained+=1
 return gained


def load_profile(path:Path)->Profile:
 """保存済みProfileを読み込む。無ければ初期値を返す"""
 if not path.exists():
  return Profile()
 with path.open("r",encoding="utf-8") as handle:
  payload=json.load(handle)
 return Profile(
  level=int(payload["level"]),
  exp=int(payload["exp"]),
  total_score=int(payload["total_score"]),
  plays=int(payload["plays"]),
  clears=int(payload["clears"]),
  best_scores={str(key):int(value) for key,value in payload.get("best_scores",{}).items()},
 )


def save_profile(path:Path,profile:Profile)->None:
 """Profileを保存する"""
 path.parent.mkdir(parents=True,exist_ok=True)
 temporary=path.with_suffix(path.suffix+".tmp")
 with temporary.open("w",encoding="utf-8") as handle:
  json.dump(asdict(profile),handle,ensure_ascii=False,indent=2)
 temporary.replace(path)
