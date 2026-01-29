from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any


class ApiError(Exception):
    def __init__(
        self, message: str, code: str = "ERROR", status_code: int = 500, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ValidationError(ApiError):
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message, code="VALIDATION_ERROR", status_code=400, details={"field": field, **(details or {})}
        )


class NotFoundError(ApiError):
    def __init__(self, resource: str, resource_id: Optional[str] = None):
        message = f"{resource}が見つかりません"
        if resource_id:
            message = f"{resource} (ID: {resource_id}) が見つかりません"
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=404,
            details={"resource": resource, "resource_id": resource_id},
        )


class ServerError(ApiError):
    def __init__(self, message: str = "サーバー内部エラーが発生しました", details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, code="SERVER_ERROR", status_code=500, details=details)


class RateLimitExceededError(ApiError):
    def __init__(
        self,
        message: str = "リクエスト制限を超過しました。しばらく待ってから再試行してください",
        retry_after: Optional[int] = None,
    ):
        super().__init__(
            message=message, code="RATE_LIMIT_EXCEEDED", status_code=429, details={"retry_after": retry_after}
        )


def register_fastapi_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError):
        response = {
            "error": {
                "code": error.code,
                "message": error.message,
            }
        }
        if error.details:
            response["error"]["details"] = error.details
        return JSONResponse(status_code=error.status_code, content=response)

    @app.exception_handler(Exception)
    async def handle_generic_exception(request: Request, error: Exception):
        from middleware.logger import get_logger

        logger = get_logger()
        logger.error(f"Unhandled exception: {str(error)}", exc_info=True)
        response = {
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "予期しないエラーが発生しました",
            }
        }
        if app.debug:
            response["error"]["debug_message"] = str(error)
        return JSONResponse(status_code=500, content=response)


def register_error_handlers(app) -> None:
    pass
