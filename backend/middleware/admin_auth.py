import os
from functools import wraps
from typing import Callable, TypeVar, Any
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from flask import request as flask_request
from middleware.logger import get_logger

security = HTTPBearer(auto_error=False)

F = TypeVar("F", bound=Callable[..., Any])


def get_admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", "")


async def require_admin_auth_fastapi(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)
) -> None:
    token = get_admin_token()
    if not token:
        get_logger().warning("ADMIN_TOKEN is not configured")
        raise HTTPException(status_code=503, detail="Admin authentication is not configured")
    if not credentials:
        raise HTTPException(status_code=401, detail="認証が必要です")
    if credentials.credentials != token:
        raise HTTPException(status_code=401, detail="認証に失敗しました")


def require_admin_auth(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        token = get_admin_token()
        if not token:
            get_logger().warning("ADMIN_TOKEN is not configured")
            from flask import jsonify

            return jsonify({"error": "Admin authentication is not configured"}), 503
        auth_header = flask_request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            from flask import jsonify

            return jsonify({"error": "認証が必要です"}), 401
        provided_token = auth_header[7:]
        if provided_token != token:
            from flask import jsonify

            return jsonify({"error": "認証に失敗しました"}), 401
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
