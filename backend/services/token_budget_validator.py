from typing import Dict,Any,Optional,Protocol
from agents.exceptions import TokenBudgetExceededError
from middleware.logger import get_logger


class TokenUsageProvider(Protocol):
    def get_project_token_usage(self,project_id:str)->int:
        ...


class TokenBudgetConfigProvider(Protocol):
    def get_token_budget_settings(self)->Dict[str,Any]:
        ...


class DefaultTokenBudgetConfig:
    def get_token_budget_settings(self)->Dict[str,Any]:
        from config_loaders.workflow_config import get_token_budget_settings
        return get_token_budget_settings()


class TokenBudgetValidationResult:
    def __init__(
        self,
        is_valid:bool,
        used:int,
        limit:int,
        warning_threshold:int,
        is_warning:bool,
        enforcement:str
    ):
        self.is_valid=is_valid
        self.used=used
        self.limit=limit
        self.warning_threshold=warning_threshold
        self.is_warning=is_warning
        self.enforcement=enforcement


class TokenBudgetValidator:
    def __init__(self,config:Optional[TokenBudgetConfigProvider]=None):
        self._config=config or DefaultTokenBudgetConfig()

    def validate(
        self,
        project_id:str,
        used_tokens:int,
        budget_override:Optional[Dict[str,Any]]=None
    )->TokenBudgetValidationResult:
        budget=budget_override if budget_override else self._config.get_token_budget_settings()
        limit=budget.get("default_limit",500000)
        warning_pct=budget.get("warning_threshold_percent",80)
        enforcement=budget.get("enforcement","hard")
        warning_at=int(limit*warning_pct/100)
        is_warning=used_tokens>=warning_at
        is_over_limit=used_tokens>=limit
        is_valid=not (enforcement=="hard" and is_over_limit)
        return TokenBudgetValidationResult(
            is_valid=is_valid,
            used=used_tokens,
            limit=limit,
            warning_threshold=warning_at,
            is_warning=is_warning,
            enforcement=enforcement
        )

    def validate_and_raise(
        self,
        project_id:str,
        used_tokens:int,
        budget_override:Optional[Dict[str,Any]]=None
    )->TokenBudgetValidationResult:
        result=self.validate(project_id,used_tokens,budget_override)
        if result.is_warning:
            pct=int(result.used/result.limit*100)
            get_logger().warning(
                f"token budget warning: project={project_id} used={result.used}/{result.limit} ({pct}%)"
            )
        if not result.is_valid:
            raise TokenBudgetExceededError(project_id,result.used,result.limit)
        return result
