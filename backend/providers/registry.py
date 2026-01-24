"""プロバイダーレジストリ - プロバイダーの登録と取得を管理"""
from typing import Dict,Type,Optional,List,Any
from .base import AIProvider,AIProviderConfig


class ProviderRegistry:
 """プロバイダーレジストリ（シングルトン）"""
 _instance:Optional["ProviderRegistry"] = None
 _providers:Dict[str,Type[AIProvider]] = {}
 _instances:Dict[str,AIProvider] = {}

 def __new__(cls):
  if cls._instance is None:
   cls._instance = super().__new__(cls)
  return cls._instance

 @classmethod
 def register(cls,provider_class:Type[AIProvider])->None:
  """プロバイダークラスを登録"""
  temp = provider_class()
  cls._providers[temp.provider_id] = provider_class

 @classmethod
 def get(
  cls,
  provider_id:str,
  config:Optional[AIProviderConfig] = None
 )->Optional[AIProvider]:
  """プロバイダーインスタンスを取得"""
  if provider_id not in cls._providers:
   return None
  cache_key = f"{provider_id}:{id(config)}"
  if cache_key not in cls._instances:
   cls._instances[cache_key] = cls._providers[provider_id](config)
  return cls._instances[cache_key]

 @classmethod
 def get_fresh(
  cls,
  provider_id:str,
  config:Optional[AIProviderConfig] = None
 )->Optional[AIProvider]:
  """新しいプロバイダーインスタンスを取得（キャッシュなし）"""
  if provider_id not in cls._providers:
   return None
  return cls._providers[provider_id](config)

 @classmethod
 def list_providers(cls)->List[Dict[str,Any]]:
  """登録済みプロバイダー一覧"""
  result = []
  for provider_id,provider_class in cls._providers.items():
   temp = provider_class()
   result.append({
    "id":temp.provider_id,
    "name":temp.display_name,
    "models":[m.id for m in temp.get_available_models()]
   })
  return result

 @classmethod
 def is_registered(cls,provider_id:str)->bool:
  """プロバイダーが登録されているか"""
  return provider_id in cls._providers

 @classmethod
 def clear_cache(cls)->None:
  """インスタンスキャッシュをクリア"""
  cls._instances.clear()


def get_provider(
 provider_id:str,
 config:Optional[AIProviderConfig] = None
)->Optional[AIProvider]:
 """プロバイダー取得のショートカット"""
 return ProviderRegistry.get(provider_id,config)


def list_providers()->List[Dict[str,Any]]:
 """プロバイダー一覧取得のショートカット"""
 return ProviderRegistry.list_providers()


def register_all_providers()->None:
 """全プロバイダーを登録"""
 from .anthropic import AnthropicProvider
 from .openai_provider import OpenAIProvider
 from .google import GoogleProvider
 from .xai import XAIProvider
 from .mock import MockProvider

 ProviderRegistry.register(AnthropicProvider)
 ProviderRegistry.register(OpenAIProvider)
 ProviderRegistry.register(GoogleProvider)
 ProviderRegistry.register(XAIProvider)
 ProviderRegistry.register(MockProvider)
