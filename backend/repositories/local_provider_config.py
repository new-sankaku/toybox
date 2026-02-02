"""ローカルプロバイダー設定リポジトリ"""
from typing import Optional,List,Dict,Any
from datetime import datetime
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from models.tables import LocalProviderConfig
from middleware.logger import get_logger


class LocalProviderConfigRepository:
 def __init__(self,session:Session):
  self.session=session

 def get(self,provider_id:str)->Optional[LocalProviderConfig]:
  return self.session.query(LocalProviderConfig).filter(
   LocalProviderConfig.provider_id==provider_id
  ).first()

 def get_all(self)->List[LocalProviderConfig]:
  return self.session.query(LocalProviderConfig).all()

 def get_validated_urls(self)->List[str]:
  configs=self.session.query(LocalProviderConfig).filter(
   LocalProviderConfig.is_validated==True
  ).all()
  return [c.base_url for c in configs]

 def get_validated_hosts(self)->List[str]:
  urls=self.get_validated_urls()
  hosts=[]
  for url in urls:
   try:
    parsed=urlparse(url)
    host=parsed.hostname or""
    port=parsed.port
    if port:
     hosts.append(f"{host}:{port}")
    else:
     hosts.append(host)
   except Exception as e:
    get_logger().debug(f"URL parse error in get_validated_hosts: {e}")
    continue
  return hosts

 def save(self,provider_id:str,base_url:str,is_validated:bool=False)->LocalProviderConfig:
  existing=self.get(provider_id)
  if existing:
   existing.base_url=base_url
   existing.is_validated=is_validated
   if is_validated:
    existing.last_validated_at=datetime.now()
   existing.updated_at=datetime.now()
   self.session.flush()
   return existing
  else:
   new_config=LocalProviderConfig(
    provider_id=provider_id,
    base_url=base_url,
    is_validated=is_validated,
    last_validated_at=datetime.now() if is_validated else None,
   )
   self.session.add(new_config)
   self.session.flush()
   return new_config

 def mark_validated(self,provider_id:str,is_validated:bool=True)->Optional[LocalProviderConfig]:
  config=self.get(provider_id)
  if config:
   config.is_validated=is_validated
   config.last_validated_at=datetime.now()
   config.updated_at=datetime.now()
   self.session.flush()
  return config

 def delete(self,provider_id:str)->bool:
  existing=self.get(provider_id)
  if existing:
   self.session.delete(existing)
   self.session.flush()
   return True
  return False

 def is_url_validated(self,url:str)->bool:
  try:
   parsed=urlparse(url)
   host=parsed.hostname or""
   port=parsed.port
   if port:
    target_host=f"{host}:{port}"
   else:
    target_host=host
   validated_hosts=self.get_validated_hosts()
   return target_host in validated_hosts
  except Exception as e:
   get_logger().debug(f"URL validation check failed: {e}")
   return False
