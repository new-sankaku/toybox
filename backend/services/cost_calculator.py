from typing import Dict,Any,Optional
from config_loader import get_pricing_config
from middleware.logger import get_logger

class CostCalculator:
 def __init__(self):
  self._pricing_config=None

 def _get_pricing(self)->Dict[str,Any]:
  if self._pricing_config is None:
   self._pricing_config=get_pricing_config()
  return self._pricing_config

 def calculate_llm_cost(self,model_id:str,input_tokens:int,output_tokens:int)->float:
  pricing=self._get_pricing()
  model_info=pricing.get("models",{}).get(model_id)
  if not model_info:
   get_logger().warning(f"No pricing found for model: {model_id}")
   return 0.0
  model_pricing=model_info.get("pricing",{})
  input_cost_per_1k=model_pricing.get("input_1k",0.0)
  output_cost_per_1k=model_pricing.get("output_1k",0.0)
  input_cost=(input_tokens/1000)*input_cost_per_1k
  output_cost=(output_tokens/1000)*output_cost_per_1k
  return input_cost+output_cost

 def calculate_image_cost(self,model_id:str,count:int=1)->float:
  pricing=self._get_pricing()
  model_info=pricing.get("models",{}).get(model_id)
  if not model_info:
   return 0.0
  model_pricing=model_info.get("pricing",{})
  per_image=model_pricing.get("per_image",0.0)
  return per_image*count

 def calculate_audio_cost(self,model_id:str,seconds:int=0)->float:
  pricing=self._get_pricing()
  model_info=pricing.get("models",{}).get(model_id)
  if not model_info:
   return 0.0
  model_pricing=model_info.get("pricing",{})
  per_second=model_pricing.get("per_second",0.0)
  return per_second*seconds

 def calculate_music_cost(self,model_id:str,seconds:int=0)->float:
  pricing=self._get_pricing()
  model_info=pricing.get("models",{}).get(model_id)
  if not model_info:
   return 0.0
  model_pricing=model_info.get("pricing",{})
  per_second=model_pricing.get("per_second",0.0)
  return per_second*seconds

 def get_model_pricing_info(self,model_id:str)->Optional[Dict[str,Any]]:
  pricing=self._get_pricing()
  return pricing.get("models",{}).get(model_id)

_calculator_instance:Optional[CostCalculator]=None

def get_cost_calculator()->CostCalculator:
 global _calculator_instance
 if _calculator_instance is None:
  _calculator_instance=CostCalculator()
 return _calculator_instance
