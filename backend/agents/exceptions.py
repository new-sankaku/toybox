"""エージェント実行時の例外クラス"""


class AgentException(Exception):
 """エージェント例外の基底クラス"""
 def __init__(self,message:str,recoverable:bool=False):
  super().__init__(message)
  self.recoverable=recoverable


class ProviderUnavailableError(AgentException):
 """AIプロバイダーが利用不可"""
 def __init__(self,provider_id:str,reason:str=None):
  message=f"プロバイダー '{provider_id}' が利用できません"
  if reason:
   message+=f": {reason}"
  super().__init__(message,recoverable=True)
  self.provider_id=provider_id
  self.reason=reason


class ContextValidationError(AgentException):
 """コンテキスト検証エラー"""
 def __init__(self,message:str,missing_fields:list=None):
  super().__init__(message,recoverable=False)
  self.missing_fields=missing_fields or []


class CheckpointTimeoutError(AgentException):
 """チェックポイント承認タイムアウト"""
 def __init__(self,checkpoint_id:str,timeout_seconds:float):
  message=f"チェックポイント '{checkpoint_id}' が {timeout_seconds}秒でタイムアウトしました"
  super().__init__(message,recoverable=True)
  self.checkpoint_id=checkpoint_id
  self.timeout_seconds=timeout_seconds


class QualityCheckFailedError(AgentException):
 """品質チェック失敗"""
 def __init__(self,agent_type:str,issues:list,retry_count:int):
  message=f"エージェント '{agent_type}' の品質チェックが {retry_count} 回失敗しました"
  super().__init__(message,recoverable=retry_count<3)
  self.agent_type=agent_type
  self.issues=issues
  self.retry_count=retry_count


class MaxRetriesExceededError(AgentException):
 """最大リトライ回数超過"""
 def __init__(self,operation:str,max_retries:int):
  message=f"操作 '{operation}' が最大リトライ回数 ({max_retries}) を超えました"
  super().__init__(message,recoverable=False)
  self.operation=operation
  self.max_retries=max_retries


class RateLimitError(AgentException):
 """レート制限エラー"""
 def __init__(self,provider_id:str,retry_after:int=None):
  message=f"プロバイダー '{provider_id}' のレート制限に達しました"
  if retry_after:
   message+=f" ({retry_after}秒後に再試行可能)"
  super().__init__(message,recoverable=True)
  self.provider_id=provider_id
  self.retry_after=retry_after
