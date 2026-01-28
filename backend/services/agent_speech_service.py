import random
from typing import Optional,Dict,List
from config_loader import load_yaml_config
from middleware.logger import get_logger


class AgentSpeechService:
 _instance=None

 def __new__(cls):
  if cls._instance is None:
   cls._instance=super().__new__(cls)
   cls._instance._initialized=False
  return cls._instance

 def __init__(self):
  if self._initialized:
   return
  self._reload_config()
  self._recent_comments:Dict[str,List[str]]={}
  self._weight_map:Dict[str,Dict[str,float]]={}
  self._initialized=True

 def _reload_config(self)->None:
  self._personality_config=load_yaml_config("agent_personality.yaml")
  self._comments_config=load_yaml_config("agent_comments.yaml")
  self._personalities=self._personality_config.get("personalities",{})
  self._agent_personalities=self._personality_config.get("agent_personalities",{})
  self._selection=self._personality_config.get("comment_selection",{})
  self._pools=self._comments_config.get("comment_pools",{})

 def get_personality(self,agent_type:str)->str:
  return self._agent_personalities.get(agent_type,"cheerful")

 def get_pool_comment(self,agent_type:str,condition:str)->Optional[str]:
  personality=self.get_personality(agent_type)
  variation_chance=self._selection.get("personality_variation_chance",0.1)
  if random.random()<variation_chance:
   available=[p for p in self._personalities if p!=personality]
   if available:
    personality=random.choice(available)
  pool=self._pools.get(condition,{}).get(personality,[])
  if not pool:
   pool=self._pools.get(condition,{}).get("cheerful",[])
  if not pool:
   return None
  no_repeat=self._selection.get("no_repeat_window",5)
  cache_key=f"{agent_type}:{condition}"
  recent=self._recent_comments.get(cache_key,[])
  candidates=[c for c in pool if c not in recent]
  if not candidates:
   candidates=pool
   self._recent_comments[cache_key]=[]
   recent=[]
  weight_key=f"{agent_type}:{condition}"
  weights=self._weight_map.get(weight_key,{})
  decay=self._selection.get("weight_decay",0.5)
  weighted_candidates=[]
  for c in candidates:
   w=weights.get(c,1.0)
   weighted_candidates.append((c,w))
  total=sum(w for _,w in weighted_candidates)
  if total<=0:
   comment=random.choice(candidates)
  else:
   r=random.random()*total
   cumulative=0.0
   comment=candidates[0]
   for c,w in weighted_candidates:
    cumulative+=w
    if r<=cumulative:
     comment=c
     break
  recent.append(comment)
  if len(recent)>no_repeat:
   recent=recent[-no_repeat:]
  self._recent_comments[cache_key]=recent
  if weight_key not in self._weight_map:
   self._weight_map[weight_key]={}
  self._weight_map[weight_key][comment]=weights.get(comment,1.0)*decay
  return comment

 def get_comment_instruction(self,agent_type:str)->str:
  policy=self._personality_config.get("comment_policy",{})
  guideline=policy.get("guideline","")
  max_length=policy.get("max_length",50)
  start=policy.get("delimiter_start","[COMMENT]")
  end=policy.get("delimiter_end","[/COMMENT]")
  personality=self.get_personality(agent_type)
  personality_desc=self._personalities.get(personality,{}).get("description","")
  return f"""出力の冒頭に{start}一言コメント{end}を記述してください。
あなたの性格:{personality_desc}
{guideline}
{max_length}文字以内。コメントの後に本来の成果物を出力してください。"""


def get_agent_speech_service()->AgentSpeechService:
 return AgentSpeechService()
