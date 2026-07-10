"""Skill 参数模式工具 — 对齐 MCP inputSchema / JSON Schema 2020-12 / OpenAI function.parameters。"""

from __future__ import annotations
from typing import Any

from copy import deepcopy

# JSON Schema 2020-12 — MCP SEP-1613 默认方言
JSON_SCHEMA_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def normalize_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """将 inputSchema 规范化为 JSON Schema 2020-12，并补全 additionalProperties。"""
    if not schema:
        return {
            "$schema": JSON_SCHEMA_2020_12,
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    result: Any = deepcopy(schema)
    if "$schema" not in result:
        result["$schema"] = JSON_SCHEMA_2020_12
    _ensure_object_constraints(result)
    return result


def _ensure_object_constraints(node: dict[str, Any]) -> None:
    """递归为 object 节点补全 additionalProperties: false。"""
    if node.get("type") == "object" and "additionalProperties" not in node:
        node["additionalProperties"] = False

    properties: dict[str, Any] | None = node.get("properties")
    if not isinstance(properties, dict):
        return
    for prop_def in properties.values():
        if isinstance(prop_def, dict):
            _ensure_object_constraints(prop_def)


def resolve_input_schema(data: dict[str, Any]) -> dict[str, Any]:
    """从元数据 dict 解析 inputSchema（兼容旧字段 parameters）。"""
    raw: Any = data.get("inputSchema") or data.get("parameters") or {}
    if not isinstance(raw, dict):
        return normalize_input_schema({})
    return normalize_input_schema(raw)
