"""
Skill CRUD API 路由。

端点：
  GET    /api/v1/skills            — 列出 Skill（分页，可筛选）
  GET    /api/v1/skills/{id}       — 获取 Skill 详情
  POST   /api/v1/skills            — 手动注册自定义 Skill
  PUT    /api/v1/skills/{id}       — 更新 Skill
  DELETE /api/v1/skills/{id}       — 注销 Skill
  POST   /api/v1/skills/{id}/enable   — 启用 Skill
  POST   /api/v1/skills/{id}/disable  — 禁用 Skill
  POST   /api/v1/skills/reindex    — 触发全量重建索引
  GET    /api/v1/skills/stats      — 注册表统计
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, status

from src.skills.models import (
    Skill,
    SkillCreateRequest,
    SkillListResponse,
    SkillSource,
    SkillStatus,
    SkillUpdateRequest,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# 单例注册表（在应用启动时注入；参见 main.py 中的 lifespan）
_registry: Any = None


def set_registry(registry: Any) -> None:
    """注入 SkillRegistry 实例（在应用启动时调用）。"""
    global _registry
    _registry = registry


def _api_response(code: int, data: Any, message: str) -> dict[str, Any]:
    """构建统一的 API 响应信封。"""
    return {
        "code": code,
        "data": data,
        "message": message,
        "traceId": str(uuid.uuid4()),
    }


@router.get("", response_model=dict)
async def list_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    source: str | None = None,
    keyword: str | None = None,
) -> dict[str, Any]:
    """分页列出 Skill，支持可选筛选。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    skills = _registry.list_all()

    # 筛选
    if category:
        skills = [s for s in skills if s.category == category]
    if status_filter:
        skills = [s for s in skills if s.status == status_filter]
    if source:
        skills = [s for s in skills if s.source == source]
    if keyword:
        kw_lower = keyword.lower()
        skills = [
            s for s in skills
            if kw_lower in s.name.lower() or kw_lower in s.description.lower()
        ]

    total = len(skills)
    start = (page - 1) * page_size
    end = start + page_size
    items = skills[start:end]

    response = SkillListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
    return _api_response(0, response.model_dump(mode="json"), "OK")


@router.get("/stats", response_model=dict)
async def get_skill_stats() -> dict[str, Any]:
    """返回注册表统计信息。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")
    return _api_response(0, _registry.stats(), "OK")


@router.get("/{skill_id}", response_model=dict)
async def get_skill(skill_id: str) -> dict[str, Any]:
    """按 ID 获取单个 Skill。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")
    skill = _registry.get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_id}' not found",
        )
    return _api_response(0, skill.model_dump(mode="json"), "OK")


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_skill(req: SkillCreateRequest) -> dict[str, Any]:
    """手动注册自定义 Skill。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    existing = _registry.get(req.skill_id)
    if existing:
        return _api_response(3001, None, f"Skill '{req.skill_id}' already exists")

    skill = Skill(
        skill_id=req.skill_id,
        name=req.name,
        description=req.description,
        category=req.category,
        tags=req.tags,
        parameters=req.parameters,
        required_permissions=req.required_permissions,
        handler=req.handler,
        timeout=req.timeout,
        version=req.version,
        status=SkillStatus.ACTIVE,
        source=SkillSource.CUSTOM,
        priority=req.priority,
        requires_approval=req.requires_approval,
    )
    await _registry.register(skill)
    return _api_response(0, skill.model_dump(mode="json"), "Skill created")


@router.put("/{skill_id}", response_model=dict)
async def update_skill(
    skill_id: str,
    req: SkillUpdateRequest,
) -> dict[str, Any]:
    """更新已有 Skill。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    skill = _registry.get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_id}' not found",
        )

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(skill, key, value)

    await _registry.register(skill)  # 重新注册（覆盖 + 重建索引）
    return _api_response(0, skill.model_dump(mode="json"), "Skill updated")


@router.delete("/{skill_id}", response_model=dict)
async def delete_skill(skill_id: str) -> dict[str, Any]:
    """注销 Skill。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    if not _registry.get(skill_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_id}' not found",
        )

    await _registry.unregister(skill_id)
    return _api_response(0, None, "Skill deleted")


@router.post("/{skill_id}/enable", response_model=dict)
async def enable_skill(skill_id: str) -> dict[str, Any]:
    """启用 Skill（将状态设置为 active）。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    skill = _registry.get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_id}' not found",
        )

    skill.status = SkillStatus.ACTIVE
    await _registry.register(skill)
    return _api_response(0, None, "Skill enabled")


@router.post("/{skill_id}/disable", response_model=dict)
async def disable_skill(skill_id: str) -> dict[str, Any]:
    """禁用 Skill（将状态设置为 inactive）。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    skill = _registry.get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_id}' not found",
        )

    skill.status = SkillStatus.INACTIVE
    await _registry.register(skill)
    return _api_response(0, None, "Skill disabled")


@router.post("/reindex", response_model=dict)
async def reindex_skills() -> dict[str, Any]:
    """触发对所有活跃 Skill 的全量重建索引，索引到 Qdrant。"""
    if _registry is None:
        return _api_response(9001, None, "SkillRegistry not initialized")

    count = await _registry.reindex_all()
    return _api_response(0, {"indexed": count}, "Reindex complete")
