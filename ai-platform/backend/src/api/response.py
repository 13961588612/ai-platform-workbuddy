"""统一的 API 响应辅助函数。

所有 API 响应遵循以下格式：
{
    "code": 0,         # 0 = 成功，非零 = 错误
    "data": {...},     # 响应数据（错误时为 null）
    "message": "...",  # 人类可读的消息
    "traceId": "..."   # 请求 trace ID，用于关联追踪
}
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def success(
    data: Any = None,
    message: str = "success",
    trace_id: str = "",
) -> dict[str, Any]:
    """构建成功响应字典。"""
    return {
        "code": 0,
        "data": data,
        "message": message,
        "traceId": trace_id,
    }


def error(
    code: int,
    message: str,
    trace_id: str = "",
    data: Any = None,
) -> dict[str, Any]:
    """构建错误响应字典。"""
    return {
        "code": code,
        "data": data,
        "message": message,
        "traceId": trace_id,
    }


def success_response(
    data: Any = None,
    message: str = "success",
    trace_id: str = "",
) -> JSONResponse:
    """构建 HTTP 200 的成功 JSONResponse。"""
    return JSONResponse(
        status_code=200,
        content=success(data, message, trace_id),
    )


def error_response(
    code: int,
    message: str,
    http_status: int = 400,
    trace_id: str = "",
    data: Any = None,
) -> JSONResponse:
    """构建自定义 HTTP 状态的错误 JSONResponse。"""
    return JSONResponse(
        status_code=http_status,
        content=error(code, message, trace_id, data),
    )
