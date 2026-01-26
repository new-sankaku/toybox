"""リトライ戦略モジュール"""
import asyncio
import random
from typing import Callable,TypeVar,Optional,Set
from dataclasses import dataclass,field
from .exceptions import (
 AgentException,
 ProviderUnavailableError,
 RateLimitError,
 MaxRetriesExceededError,
)

T=TypeVar("T")


@dataclass
class RetryConfig:
 max_retries:int=3
 base_delay:float=1.0
 max_delay:float=60.0
 exponential_base:float=2.0
 jitter:bool=True
 jitter_factor:float=0.5


@dataclass
class ProviderRetryConfig:
 """AI API接続エラー用の無限リトライ設定"""
 base_delay:float=30.0
 max_delay:float=300.0
 exponential_base:float=1.5
 jitter:bool=True
 jitter_factor:float=0.3


RETRYABLE_EXCEPTIONS:Set[type]={
 ProviderUnavailableError,
 RateLimitError,
 ConnectionError,
 TimeoutError,
}


def is_retryable_error(error:Exception)->bool:
 if isinstance(error,AgentException):
  return error.recoverable
 for exc_type in RETRYABLE_EXCEPTIONS:
  if isinstance(error,exc_type):
   return True
 error_str=str(error).lower()
 retryable_patterns=[
  "rate limit",
  "timeout",
  "connection",
  "temporarily unavailable",
  "service unavailable",
  "503",
  "429",
  "overloaded",
 ]
 return any(pattern in error_str for pattern in retryable_patterns)


def calculate_delay(
 attempt:int,
 config:RetryConfig,
 retry_after:Optional[int]=None
)->float:
 if retry_after:
  return float(retry_after)
 delay=config.base_delay*(config.exponential_base**attempt)
 delay=min(delay,config.max_delay)
 if config.jitter:
  jitter_range=delay*config.jitter_factor
  delay=delay+random.uniform(-jitter_range,jitter_range)
  delay=max(0.1,delay)
 return delay


def calculate_provider_delay(attempt:int,config:ProviderRetryConfig)->float:
 delay=config.base_delay*(config.exponential_base**min(attempt,10))
 delay=min(delay,config.max_delay)
 if config.jitter:
  jitter_range=delay*config.jitter_factor
  delay=delay+random.uniform(-jitter_range,jitter_range)
  delay=max(1.0,delay)
 return delay


def is_provider_unavailable_error(error:Exception)->bool:
 if isinstance(error,ProviderUnavailableError):
  return True
 if isinstance(error,(ConnectionError,TimeoutError)):
  return True
 error_str=str(error).lower()
 patterns=["connection","timeout","unavailable","503","overloaded","api key","authentication"]
 return any(p in error_str for p in patterns)


async def retry_with_backoff(
 operation:Callable[...,T],
 operation_name:str="operation",
 config:Optional[RetryConfig]=None,
 on_retry:Optional[Callable[[int,Exception,float],None]]=None,
 *args,
 **kwargs
)->T:
 config=config or RetryConfig()
 last_error:Optional[Exception]=None
 for attempt in range(config.max_retries+1):
  try:
   result=await operation(*args,**kwargs)
   return result
  except Exception as e:
   last_error=e
   if not is_retryable_error(e):
    raise
   if attempt>=config.max_retries:
    raise MaxRetriesExceededError(operation_name,config.max_retries) from e
   retry_after=None
   if isinstance(e,RateLimitError):
    retry_after=e.retry_after
   delay=calculate_delay(attempt,config,retry_after)
   if on_retry:
    on_retry(attempt+1,e,delay)
   await asyncio.sleep(delay)
 raise MaxRetriesExceededError(operation_name,config.max_retries) from last_error


def retry_sync_with_backoff(
 operation:Callable[...,T],
 operation_name:str="operation",
 config:Optional[RetryConfig]=None,
 on_retry:Optional[Callable[[int,Exception,float],None]]=None,
 *args,
 **kwargs
)->T:
 import time
 config=config or RetryConfig()
 last_error:Optional[Exception]=None
 for attempt in range(config.max_retries+1):
  try:
   result=operation(*args,**kwargs)
   return result
  except Exception as e:
   last_error=e
   if not is_retryable_error(e):
    raise
   if attempt>=config.max_retries:
    raise MaxRetriesExceededError(operation_name,config.max_retries) from e
   retry_after=None
   if isinstance(e,RateLimitError):
    retry_after=e.retry_after
   delay=calculate_delay(attempt,config,retry_after)
   if on_retry:
    on_retry(attempt+1,e,delay)
   time.sleep(delay)
 raise MaxRetriesExceededError(operation_name,config.max_retries) from last_error


async def retry_until_provider_available(
 operation:Callable[...,T],
 operation_name:str="API call",
 config:Optional[ProviderRetryConfig]=None,
 on_waiting:Optional[Callable[[int,Exception,float],None]]=None,
 on_recovered:Optional[Callable[[int],None]]=None,
 *args,
 **kwargs
)->T:
 """AI API接続エラー時に無限リトライする"""
 config=config or ProviderRetryConfig()
 attempt=0
 while True:
  try:
   result=await operation(*args,**kwargs)
   if attempt>0 and on_recovered:
    on_recovered(attempt)
   return result
  except Exception as e:
   if not is_provider_unavailable_error(e):
    raise
   delay=calculate_provider_delay(attempt,config)
   if on_waiting:
    on_waiting(attempt+1,e,delay)
   await asyncio.sleep(delay)
   attempt+=1


class RetryContext:
 """リトライコンテキスト（状態追跡用）"""
 def __init__(self,config:Optional[RetryConfig]=None):
  self.config=config or RetryConfig()
  self.attempt=0
  self.total_delay=0.0
  self.errors:list=[]

 def record_error(self,error:Exception,delay:float)->None:
  self.errors.append({
   "attempt":self.attempt,
   "error":str(error),
   "error_type":type(error).__name__,
   "delay":delay,
  })
  self.attempt+=1
  self.total_delay+=delay

 def should_retry(self)->bool:
  return self.attempt<self.config.max_retries

 def get_summary(self)->dict:
  return {
   "total_attempts":self.attempt,
   "total_delay_seconds":self.total_delay,
   "errors":[e["error_type"] for e in self.errors],
  }
