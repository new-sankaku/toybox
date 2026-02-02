
"""AI Provider/Service configuration loader"""
import os
import yaml
from typing import Dict,List,Any,Optional

_config:Optional[Dict[str,Any]]=None

def _load_config()->Dict[str,Any]:
 global _config
 if _config is not None:
  return _config
 config_path=os.path.join(os.path.dirname(__file__),'config','ai_providers.yaml')
 with open(config_path,'r',encoding='utf-8') as f:
  _config=yaml.safe_load(f)
 return _config

def get_service_types()->List[str]:
 return _load_config().get('service_types',[])

def get_service_labels()->Dict[str,str]:
 return _load_config().get('service_labels',{})

def get_provider_type_mapping()->Dict[str,str]:
 return _load_config().get('provider_type_mapping',{})

def get_reverse_provider_type_mapping()->Dict[str,str]:
 mapping=get_provider_type_mapping()
 return {v:k for k,v in mapping.items()}

def get_defaults()->Dict[str,Dict[str,str]]:
 result={}
 for cat in get_usage_categories():
  stype=cat.get('service_type','')
  if stype and stype not in result:
   d=cat.get('default',{})
   result[stype]={'provider':d.get('provider',''),'model':d.get('model','')}
 return result

def get_providers()->Dict[str,Dict[str,Any]]:
 return _load_config().get('providers',{})

def get_usage_categories()->List[Dict[str,Any]]:
 return _load_config().get('usage_categories',[])

def get_providers_for_service(service_type:str)->List[Dict[str,Any]]:
 result=[]
 for provider_id,provider in get_providers().items():
  if service_type in provider.get('service_types',[]):
   result.append({
    'id':provider_id,
    'label':provider['label'],
    'models':provider.get('models',[]),
    'defaultModel':provider.get('default_model','')
   })
 return result

def build_default_ai_services()->Dict[str,Dict[str,Any]]:
 result={}
 defaults=get_defaults()
 for stype in get_service_types():
  d=defaults.get(stype,{})
  result[stype]={
   "enabled":True,
   "provider":d.get("provider",""),
   "model":d.get("model","")
  }
 return result

def get_pricing_config()->Dict[str,Any]:
 return _load_config().get('pricing',{})

def get_model_pricing(provider_id:str,model_id:str)->Optional[Dict[str,Any]]:
 providers=get_providers()
 provider=providers.get(provider_id)
 if not provider:
  return None
 models=provider.get('models',[])
 for m in models:
  if m.get('id')==model_id:
   return m.get('pricing')
 return None

def get_all_model_pricing()->Dict[str,Dict[str,Any]]:
 result={}
 for pid,pdata in get_providers().items():
  for m in pdata.get('models',[]):
   mid=m.get('id','')
   pricing=m.get('pricing')
   if pricing:
    result[mid]={
     'provider':pid,
     'pricing':pricing
    }
 return result
