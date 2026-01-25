"""APIキーリポジトリ"""
from typing import Optional,List,Dict,Any
from datetime import datetime
from sqlalchemy.orm import Session
from models.tables import ApiKeyStore
from security import encrypt_api_key,decrypt_api_key,generate_key_hint


class ApiKeyRepository:
 def __init__(self,session:Session):
  self.session = session

 def get(self,provider_id:str)->Optional[ApiKeyStore]:
  return self.session.query(ApiKeyStore).filter(
   ApiKeyStore.provider_id == provider_id
  ).first()

 def get_all(self)->List[ApiKeyStore]:
  return self.session.query(ApiKeyStore).all()

 def get_all_hints(self)->Dict[str,Dict[str,Any]]:
  keys = self.get_all()
  return {
   key.provider_id:{
    "hint":key.key_hint,
    "isValid":key.is_valid,
    "lastValidatedAt":key.last_validated_at.isoformat() if key.last_validated_at else None,
   }
   for key in keys
  }

 def save(self,provider_id:str,api_key:str)->ApiKeyStore:
  encrypted = encrypt_api_key(api_key)
  hint = generate_key_hint(api_key)
  existing = self.get(provider_id)
  if existing:
   existing.encrypted_key = encrypted
   existing.key_hint = hint
   existing.is_valid = False
   existing.updated_at = datetime.now()
   self.session.flush()
   return existing
  else:
   new_key = ApiKeyStore(
    provider_id=provider_id,
    encrypted_key=encrypted,
    key_hint=hint,
    is_valid=False,
   )
   self.session.add(new_key)
   self.session.flush()
   return new_key

 def delete(self,provider_id:str)->bool:
  existing = self.get(provider_id)
  if existing:
   self.session.delete(existing)
   self.session.flush()
   return True
  return False

 def get_decrypted_key(self,provider_id:str)->Optional[str]:
  key_store = self.get(provider_id)
  if key_store:
   return decrypt_api_key(key_store.encrypted_key)
  return None

 def update_validation_status(
  self,
  provider_id:str,
  is_valid:bool
 )->Optional[ApiKeyStore]:
  key_store = self.get(provider_id)
  if key_store:
   key_store.is_valid = is_valid
   key_store.last_validated_at = datetime.now()
   self.session.flush()
  return key_store
