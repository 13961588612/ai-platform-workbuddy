"""使用 structlog 的结构化日志配置。

提供 JSON 格式的结构化日志，支持 trace ID 关联、
敏感数据脱敏、控制台输出以及可选的文件轮转落盘。
"""

from __future__ import annotations
from typing import Any

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

from src.config import LogLevel, get_settings

# 日志输出中应脱敏的字段
SENSITIVE_FIELDS = frozenset({
    "password",
    "token",
    "api_key",
    "apikey",
    "secret",
    "aes_key",
    "authorization",
    "refresh_token",
    "access_token",
    "credential",
})


def _mask_sensitive_data(
    _logger: Any,
    _method_name: str,
    event_dict: structlog.types.EventDict,
) -> structlog.types.EventDict:
    """将敏感字段替换为 '***' 的处理器。"""
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_FIELDS:
            event_dict[key] = "***"
        # 检查嵌套字典
        if isinstance(event_dict[key], dict):
            for nested_key in list(event_dict[key].keys()):
                if nested_key.lower() in SENSITIVE_FIELDS:
                    event_dict[key][nested_key] = "***"
    return event_dict


def _build_processors(use_json: bool) -> list[Any]:
    """组装 structlog 处理器链（含脱敏与渲染器）。

    Args:
        use_json: 为 ``True`` 时使用 JSON 渲染；否则使用控制台渲染。

    Returns:
        按执行顺序排列的 structlog 处理器列表。
    """
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _mask_sensitive_data,
    ]
    if use_json:
        processors.append(structlog.processors.JSONRenderer(ensure_ascii=False))
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    return processors


def _resolve_log_path(log_file: str) -> Path:
    """将日志文件路径解析为绝对 ``Path``。

    Args:
        log_file: 配置中的日志文件路径（相对或绝对）。

    Returns:
        绝对路径对象。
    """
    path: Path = Path(log_file)
    if not path.is_absolute():
        path: Any = Path.cwd() / path
    return path


def _has_file_handler(root: logging.Logger, log_path: Path) -> bool:
    """检查 root logger 是否已挂载指向同一文件的轮转 Handler。

    Args:
        root: Python 标准库 root logger。
        log_path: 目标日志文件的绝对路径。

    Returns:
        若已存在指向该文件的 ``RotatingFileHandler`` 则返回 ``True``。
    """
    target: Path = log_path.resolve()
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename).resolve() == target:
                return True
    return False


def _setup_file_handler(log_file: str, max_bytes: int, backup_count: int) -> Path | None:
    """为 root logger 添加轮转文件 Handler。"""
    log_path: Path = _resolve_log_path(log_file)
    root: Any = logging.getLogger()
    if _has_file_handler(root, log_path):
        return log_path

    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler: RotatingFileHandler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(file_handler)
    return log_path


def configure_logging(log_level: LogLevel | None = None, json_format: bool | None = None) -> None:
    """
    为应用配置 structlog。

    参数：
        log_level: 覆盖 settings 中的日志级别。
        json_format: 覆盖日志格式（True=JSON，False=控制台）。
    """
    settings: Settings = get_settings()
    level: Any = log_level or settings.LOG_LEVEL
    use_json: Any = json_format if json_format is not None else (settings.LOG_FORMAT == "json")

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.value),
        force=True,
    )

    structlog.configure(
        processors=_build_processors(use_json),
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    log_file: str = (settings.LOG_FILE or "").strip()
    if not log_file:
        return

    log_path: Path | None = _setup_file_handler(
        log_file,
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
    )
    if log_path is not None:
        get_logger("logging").info(
            "File logging enabled",
            log_file=str(log_path),
            max_bytes=settings.LOG_MAX_BYTES,
            backup_count=settings.LOG_BACKUP_COUNT,
        )


def get_logger(name: str = "ai-platform") -> structlog.stdlib.BoundLogger:
    """返回已配置的 structlog 日志器实例。"""
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """将键值对绑定到当前日志上下文（如 trace_id、user_id）。"""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """清除日志上下文中的所有上下文变量。"""
    structlog.contextvars.clear_contextvars()
