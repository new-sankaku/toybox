"""点数計算

正確さ・速さ・連鎖・難易度の4要素で決める。係数は全てConfigから与える。

正確さは二乗で効かせる。早口言葉は「ほぼ言えた」と「言い切った」の差が
体験上大きいため、線形だと僅差になり達成感が出ない。
言い直しは減点だが零点にはしない。挑戦をやめさせないことを優先する。
"""
from dataclasses import dataclass
from typing import Dict,Optional


@dataclass
class ScoreRules:
 base_per_difficulty:int=100
 accuracy_weight:int=500
 accuracy_exponent:float=2.0
 speed_weight:float=0.1
 target_ms_per_mora:float=200.0
 combo_weight:int=10
 streak_step:float=0.1
 streak_cap:int=10
 restart_rate:float=0.8

 @classmethod
 def from_dict(cls,data:Optional[Dict])->"ScoreRules":
  data=data or {}
  default=cls()
  return cls(
   base_per_difficulty=int(data.get("base_per_difficulty",default.base_per_difficulty)),
   accuracy_weight=int(data.get("accuracy_weight",default.accuracy_weight)),
   accuracy_exponent=float(data.get("accuracy_exponent",default.accuracy_exponent)),
   speed_weight=float(data.get("speed_weight",default.speed_weight)),
   target_ms_per_mora=float(data.get("target_ms_per_mora",default.target_ms_per_mora)),
   combo_weight=int(data.get("combo_weight",default.combo_weight)),
   streak_step=float(data.get("streak_step",default.streak_step)),
   streak_cap=int(data.get("streak_cap",default.streak_cap)),
   restart_rate=float(data.get("restart_rate",default.restart_rate)),
  )


@dataclass
class ScoreBreakdown:
 base:int
 accuracy:int
 speed:int
 combo:int
 multiplier:float
 total:int

 def to_dict(self)->Dict:
  return {
   "base":self.base,
   "accuracy":self.accuracy,
   "speed":self.speed,
   "combo":self.combo,
   "multiplier":self.multiplier,
   "total":self.total,
  }


def calculate(
 difficulty:int,
 accuracy:float,
 duration_ms:float,
 mora_count:int,
 max_combo:int,
 streak:int,
 restarts:int,
 abandoned:bool,
 rules:ScoreRules,
)->ScoreBreakdown:
 """1回の挑戦の得点を算出する"""
 if abandoned:
  return ScoreBreakdown(base=0,accuracy=0,speed=0,combo=0,multiplier=0.0,total=0)
 base=rules.base_per_difficulty*difficulty
 accuracy_points=int(round(rules.accuracy_weight*accuracy**rules.accuracy_exponent))
 target_ms=rules.target_ms_per_mora*mora_count
 speed_points=int(round(max(0.0,target_ms-duration_ms)*rules.speed_weight))
 combo_points=rules.combo_weight*max_combo
 multiplier=1.0+min(streak,rules.streak_cap)*rules.streak_step
 multiplier*=rules.restart_rate**max(0,restarts)
 total=int(round((base+accuracy_points+speed_points+combo_points)*multiplier))
 return ScoreBreakdown(
  base=base,
  accuracy=accuracy_points,
  speed=speed_points,
  combo=combo_points,
  multiplier=round(multiplier,3),
  total=total,
 )
