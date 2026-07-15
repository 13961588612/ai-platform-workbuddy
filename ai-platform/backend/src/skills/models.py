"""
Skills 子系统 Pydantic 模型。

上层封装遵循 Agent Skills Spec（文件夹 + SKILL.md）；
底层工具调用参数遵循 MCP inputSchema / JSON Schema 2020-12。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from src.skills.schema import normalize_input_schema


class SkillSource(str, Enum):
    """Skill 来源。"""

    CUSTOM = "custom"
    MCP = "mcp"
    BUILTIN = "builtin"
    PACKAGE = "package"  # Agent Skills Spec 技能包


class SkillStatus(str, Enum):
    """Skill 生命周期状态。"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


class SkillCategory(str, Enum):
    """Skill 业务分类。"""

    FINANCE = "finance"
    RETAIL = "retail"
    DEPARTMENT_STORE = "department_store"
    HR = "hr"
    PROPERTY = "property"
    CRM = "crm"
    VALUECARD = "valuecard"
    BUILT_IN = "built_in"


class Skill(BaseModel):
    """
    平台内 Skill 规范表示。

    Agent Skills Spec 技能包在注册时仅填充元数据（渐进式披露阶段一）；
    调用 ``load_body()`` 后填充 body 与附件列表（阶段二）。
    """

    skill_id: str
    name: str
    description: str = ""
    category: str = SkillCategory.BUILT_IN
    tags: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)  # 内存字段，源自 inputSchema
    required_permissions: list[str] = Field(default_factory=list)
    handler: str = ""
    timeout: int = 30
    version: str = "1.0.0"
    status: SkillStatus = SkillStatus.ACTIVE
    source: SkillSource = SkillSource.CUSTOM
    priority: float = 1.0
    requires_approval: bool = False
    mcp_server: str | None = None
    call_count: int = 0
    last_called_at: datetime | None = None
    embedding: list[float] | None = None

    # Agent Skills Spec 技能包字段
    package_name: str = ""  # 目录名，如 member-profile-by-vip-id
    package_dir: str = ""  # 技能包根目录绝对路径
    body: str | None = None  # SKILL.md 正文，懒加载前为 None
    body_loaded: bool = False
    scripts: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)

    def get_input_schema(self) -> dict[str, Any]:
        """返回规范化后的 MCP inputSchema。"""
        return normalize_input_schema(self.parameters)

    def is_package_skill(self) -> bool:
        """是否为 Agent Skills Spec 文件夹技能包。"""
        return bool(self.package_dir)

    def load_body(self, body: str, attachments: dict[str, list[str]] | None = None) -> None:
        """填充 SKILL.md 正文与附件路径（渐进式披露阶段二）。"""
        self.body = body
        self.body_loaded = True
        if attachments:
            self.scripts = attachments.get("scripts", [])
            self.references = attachments.get("references", [])
            self.assets = attachments.get("assets", [])

    def get_instruction_context(self) -> str:
        """
        返回注入 Agent 上下文的技能说明文本。

        若正文未加载，仅返回 description。
        """
        if self.body_loaded and self.body:
            parts: list[Any] = [self.body]
            if self.references:
                parts.append("\n## 参考资料\n" + "\n".join(f"- {p}" for p in self.references))
            if self.scripts:
                parts.append("\n## 可执行脚本\n" + "\n".join(f"- {p}" for p in self.scripts))
            return "\n".join(parts)
        return self.description

    def read_reference_file(self, relative_path: str) -> str | None:
        """按需读取 references/ 或 scripts/ 下的附件内容。"""
        if not self.package_dir:
            return None
        target: Any = Path(self.package_dir) / relative_path
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            return None

    def index_text(self) -> str:
        """返回用于向量索引的文本（元数据阶段即可生成）。"""
        parts: list[Any] = [
            self.name,
            self.description,
            " ".join(self.tags),
            self.category,
        ]
        schema: Any = self.parameters
        properties: dict[str, Any] = (
            schema.get("properties", {}) if isinstance(schema, dict) else {}
        )
        for param_name, param_def in properties.items():
            if isinstance(param_def, dict):
                parts.append(f"{param_name} {param_def.get('description', '')}")
        return " ".join(parts)


class SkillScore(BaseModel):
    """Skill 及其检索分数。"""

    skill: Skill
    score: float = 0.0
    # 查询与 Skill 向量的语义相似度（综合分权重 0.5）
    semantic_similarity: float = 0.0
    # 历史调用频次归一化分（综合分权重 0.2）
    usage_frequency: float = 0.0
    # 最近使用时间衰减加分（综合分权重 0.15）
    recency_bonus: float = 0.0
    # 业务分类是否匹配（综合分权重 0.15）
    category_match: float = 0.0

    def compute_composite(self) -> float:
        """计算综合分数。"""
        self.score = (
            0.5 * self.semantic_similarity
            + 0.2 * self.usage_frequency
            + 0.15 * self.recency_bonus
            + 0.15 * self.category_match
        )
        return self.score


class SkillCreateRequest(BaseModel):
    """API 创建 Skill 请求体。"""

    skill_id: str
    name: str
    description: str = ""
    category: str = SkillCategory.BUILT_IN
    tags: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    handler: str
    timeout: int = 30
    version: str = "1.0.0"
    priority: float = 1.0
    requires_approval: bool = False


class SkillUpdateRequest(BaseModel):
    """API 部分更新 Skill 请求体。"""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    parameters: dict[str, Any] | None = None
    required_permissions: list[str] | None = None
    handler: str | None = None
    timeout: int | None = None
    version: str | None = None
    status: SkillStatus | None = None
    priority: float | None = None
    requires_approval: bool | None = None


class SkillListResponse(BaseModel):
    """分页 Skill 列表。"""

    items: list[Skill]
    total: int
    page: int = 1
    page_size: int = 20
