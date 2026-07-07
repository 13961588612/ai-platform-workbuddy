"""
Agent 记忆模块（v1.4）—— 双层记忆模型。

静态记忆：文件系统 YAML/MD 配置（人格 + 事实），支持热重载。
动态记忆：PostgreSQL ``agent_memory`` 表 + Qdrant ``agent_memory_index``
          集合，支持两阶段语义检索。

公共 API：
    - MemoryManager       — 静态加载/缓存 + 动态检索/写入/遗忘
    - StaticMemoryLoader  — 基于 mtime 热重载的 YAML/MD 文件解析
    - MemoryInjector      — agent 运行前后的中间件
    - MemoryEntry         — 单条记忆记录的 Pydantic schema
    - MemoryType          — 记忆分类枚举
"""

from src.memory.injector import MemoryInjector, get_memory_injector
from src.memory.manager import MemoryManager, get_memory_manager
from src.memory.models import (
    ExtractedMemory,
    MemoryEntry,
    MemorySearchResult,
    MemoryType,
)
from src.memory.static_loader import StaticMemoryLoader, get_static_memory_loader

__all__ = [
    "ExtractedMemory",
    "MemoryEntry",
    "MemoryInjector",
    "MemoryManager",
    "MemorySearchResult",
    "MemoryType",
    "StaticMemoryLoader",
    "get_memory_injector",
    "get_memory_manager",
    "get_static_memory_loader",
]
