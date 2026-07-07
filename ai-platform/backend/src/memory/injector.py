"""
MemoryInjector — 将记忆编织到 Agent 运行生命周期中的中间件。

实现两个钩子：

- **before_agent_run**：加载静态记忆（人格 + 事实），通过两阶段 Qdrant 搜索
  检索动态记忆 Top-K，并按以下顺序组装完整上下文：
    1. System prompt（Agent 的 ``system_prompt``）
    2. 静态记忆（personality.md + facts/*.yaml）
    3. 动态记忆 Top-K（按 importance 排序）
    4. 对话历史（会话消息）

- **after_agent_run**：调用 LLM（通过 LLMGateway）使用轻量级提取 prompt
  从对话中识别值得记忆的内容。只有 ``importance > 0.3`` 的提取记忆会被
  持久化（A19）。

注入器设计为非阻塞的：记忆检索和提取失败会被记录日志，但不会中断 Agent 运行。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.config import get_settings
from src.agent.config import MemoryConfig
from src.llm.gateway import get_llm_gateway
from src.llm.models import LLMMessage, LLMRequest, LLMRole
from src.memory.manager import MemoryManager, get_memory_manager
from src.memory.models import ExtractedMemory, MemoryType

logger = structlog.get_logger("memory.injector")

# 提取 prompt 中包含的最近消息最大数量
_MAX_EXTRACTION_MESSAGES: int = 20

# 用于记忆提取的 LLM 模型（轻量级、快速）
_EXTRACTION_MODEL: str = "deepseek-v4-flash"

# 记忆提取的 system prompt
_EXTRACTION_SYSTEM_PROMPT = """\
你是一个记忆提取助手。分析以下对话，提取值得长期记住的记忆点。

提取规则：
1. 用户偏好（preference）：语言、风格、格式偏好等
2. 重要决策（decision）：用户做出的明确决定或确认
3. 会话摘要（summary）：对话的关键要点
4. 上下文发现（context）：有助于未来对话的背景信息
5. 事实知识（fact）：用户提到的明确事实

只提取真正有价值的记忆，避免琐碎信息。importance 评分：
- 0.9-1.0：关键信息，必须记住（如用户明确要求记住的事）
- 0.6-0.8：有价值的信息（如偏好、重要决策）
- 0.3-0.5：可能有用的上下文
- 低于0.3：不值得记住，不要提取

请以JSON数组格式输出，每个元素包含 memory_type, content, importance 三个字段。
如果没有值得提取的记忆，返回空数组 []。

输出格式：
[
  {"memory_type": "preference", "content": "用户偏好中文回复", "importance": 0.7},
  {"memory_type": "decision", "content": "用户确认选择方案A", "importance": 0.8}
]
"""


@dataclass
class AgentRunContext:
    """
    在 Agent 运行生命周期中传递的上下文对象。

    MemoryInjector 在运行前用记忆丰富此上下文，运行后从结果中提取记忆。
    """

    agent_id: str
    agent_name: str
    user_id: str
    session_id: str | None
    query: str = ""
    system_prompt: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    # 每个 agent 的记忆配置（来自 agent.yaml）；None 则使用全局设置
    memory_config: MemoryConfig | None = None
    # 由 before_agent_run 填充
    assembled_context: str = ""
    static_memory: str = ""
    dynamic_memories: list[dict[str, Any]] = field(default_factory=list)
    # 运行后填充
    assistant_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryInjector:
    """
    在 Agent 运行前注入记忆上下文，运行后提取记忆的中间件。

    用法::

        injector = get_memory_injector()

        # 在 agent 运行之前
        context = AgentRunContext(
            agent_id="hr-assistant",
            agent_name="hr-assistant",
            user_id="u123",
            session_id="web-abc",
            query="我有几天年假？",
            system_prompt="你是HR助手...",
        )
        await injector.before_agent_run(context)

        # ... 使用 context.assembled_context 运行 agent ...

        # 在 agent 运行之后
        context.assistant_response = agent_reply
        await injector.after_agent_run(context)
    """

    def __init__(
        self,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self._settings = get_settings()
        self._memory_manager: MemoryManager = memory_manager or get_memory_manager()
        self._dynamic_enabled: bool = self._settings.AGENT_MEMORY_DYNAMIC_ENABLED
        self._default_top_k: int = self._settings.AGENT_MEMORY_TOP_K

    # ==================================================================
    # before_agent_run
    # ==================================================================

    async def before_agent_run(self, context: AgentRunContext) -> AgentRunContext:
        """
        在 Agent 运行之前用静态和动态记忆丰富上下文。

        组装顺序：
        1. System prompt
        2. 静态记忆（personality.md + facts/*.yaml）
        3. 动态记忆 Top-K（两阶段检索，按 importance 排序）
        4. 对话历史

        记忆加载失败会被记录日志，但不会阻止运行 —— 上下文会使用可用的
        内容进行组装。

        Args:
            context: 要丰富的运行上下文。

        Returns:
            相同的上下文对象，其 ``assembled_context``、``static_memory``
            和 ``dynamic_memories`` 已被填充。
        """
        parts: list[str] = []

        # 解析每个 agent 的记忆配置（回退到全局设置）
        mc = context.memory_config
        static_enabled = mc.static_enabled if mc else True
        dynamic_enabled = mc.dynamic_enabled if mc else self._dynamic_enabled
        top_k = mc.top_k if mc else self._default_top_k

        # 1. System prompt
        if context.system_prompt:
            parts.append(context.system_prompt.strip())

        # 2. 静态记忆
        if static_enabled:
            static_text = self._load_static(context.agent_name)
            context.static_memory = static_text
            if static_text:
                parts.append(static_text.strip())

        # 3. 动态记忆 Top-K
        if dynamic_enabled:
            dynamic_text, dynamic_entries = await self._retrieve_dynamic(
                context, top_k
            )
            context.dynamic_memories = dynamic_entries
            if dynamic_text:
                parts.append(dynamic_text.strip())

        # 4. 对话历史
        history_text = self._format_history(context.messages)
        if history_text:
            parts.append(history_text.strip())

        context.assembled_context = "\n\n---\n\n".join(p for p in parts if p)

        logger.debug(
            "Memory context assembled",
            agent_name=context.agent_name,
            user_id=context.user_id,
            session_id=context.session_id,
            static_length=len(context.static_memory),
            dynamic_count=len(context.dynamic_memories),
            total_length=len(context.assembled_context),
        )
        return context

    # ==================================================================
    # after_agent_run
    # ==================================================================

    async def after_agent_run(self, context: AgentRunContext) -> None:
        """
        从对话中提取值得记忆的内容并持久化。

        调用 LLM（通过 LLMGateway）使用轻量级提取 prompt。
        只有 ``importance > 0.3`` 的记忆会被写入动态记忆。

        如果 agent 的 ``MemoryConfig``（``write_back = False``）或全局设置
        中禁用了动态记忆，则跳过写回。

        提取失败会被记录日志但不会抛出异常 —— 记忆写回是尽力而为的操作。

        Args:
            context: 运行上下文，其 ``assistant_response`` 已被填充。
        """
        mc = context.memory_config
        dynamic_enabled = mc.dynamic_enabled if mc else self._dynamic_enabled
        write_back = mc.write_back if mc else True

        if not dynamic_enabled or not write_back:
            return

        if not context.assistant_response.strip():
            return

        # 构建用于提取的对话记录
        transcript = self._build_transcript(context)
        if not transcript.strip():
            return

        # 调用 LLM 进行提取
        try:
            extracted = await self._extract_memories(transcript)
        except Exception:
            logger.exception(
                "Memory extraction LLM call failed",
                agent_name=context.agent_name,
                session_id=context.session_id,
            )
            return

        if not extracted:
            logger.debug(
                "No memories extracted",
                agent_name=context.agent_name,
                session_id=context.session_id,
            )
            return

        # 持久化提取的记忆
        written = await self._memory_manager.write_extracted_memories(
            agent_name=context.agent_name,
            user_id=context.user_id,
            session_id=context.session_id,
            extracted=extracted,
        )

        logger.info(
            "Memories extracted and written",
            agent_name=context.agent_name,
            user_id=context.user_id,
            session_id=context.session_id,
            extracted=len(extracted),
            written=written,
        )

    # ==================================================================
    # 内部：静态记忆
    # ==================================================================

    def _load_static(self, agent_name: str) -> str:
        """为 agent 加载静态记忆，并检查热重载。"""
        try:
            self._memory_manager.check_static_reload(agent_name)
            return self._memory_manager.load_static_memory(agent_name)
        except Exception:
            logger.exception(
                "Failed to load static memory",
                agent_name=agent_name,
            )
            return ""

    # ==================================================================
    # 内部：动态记忆检索
    # ==================================================================

    async def _retrieve_dynamic(
        self, context: AgentRunContext, top_k: int
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        检索动态记忆 Top-K 并将其格式化为上下文文本。

        返回 (格式化文本, 原始条目) 的元组。
        """
        try:
            results = await self._memory_manager.retrieve_dynamic_memory(
                query=context.query,
                agent_name=context.agent_name,
                user_id=context.user_id,
                session_id=context.session_id,
                top_k=top_k,
            )
        except Exception:
            logger.exception(
                "Dynamic memory retrieval failed",
                agent_name=context.agent_name,
                session_id=context.session_id,
            )
            return "", []

        if not results:
            return "", []

        # 按 importance 排序（已按综合分数排序，但为上下文展示按
        # importance 重新排序）
        sorted_results = sorted(
            results, key=lambda r: r.entry.importance, reverse=True
        )

        entries: list[dict[str, Any]] = []
        lines: list[str] = ["# 相关记忆"]
        for r in sorted_results:
            entry = r.entry
            entries.append(
                {
                    "id": entry.id,
                    "memory_type": entry.memory_type.value,
                    "content": entry.content,
                    "importance": entry.importance,
                    "scope": entry.scope,
                    "similarity": r.similarity,
                    "composite_score": r.composite_score,
                }
            )
            scope_label = "用户级" if entry.is_user_level else "会话级"
            lines.append(
                f"- [{entry.memory_type.value}] ({scope_label}, 重要度:{entry.importance:.2f}) "
                f"{entry.content}"
            )

        return "\n".join(lines), entries

    # ==================================================================
    # 内部：对话历史
    # ==================================================================

    @staticmethod
    def _format_history(messages: list[dict[str, Any]]) -> str:
        """将对话历史格式化为上下文文本。"""
        if not messages:
            return ""
        lines: list[str] = ["# 对话历史"]
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            role_label = {
                "user": "用户",
                "assistant": "助手",
                "system": "系统",
                "tool": "工具",
            }.get(role, role)
            lines.append(f"{role_label}: {content}")
        return "\n".join(lines)

    # ==================================================================
    # 内部：LLM 提取
    # ==================================================================

    def _build_transcript(self, context: AgentRunContext) -> str:
        """
        为提取 LLM 构建对话记录。

        包含最近的若干条消息加上最新的助手响应。
        """
        lines: list[str] = []

        # 包含最近的历史（有限制）
        recent = context.messages[-_MAX_EXTRACTION_MESSAGES:]
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"[{role}] {content}")

        # 始终包含当前的查询和响应
        if context.query:
            lines.append(f"[user] {context.query}")
        if context.assistant_response:
            lines.append(f"[assistant] {context.assistant_response}")

        return "\n".join(lines)

    async def _extract_memories(self, transcript: str) -> list[ExtractedMemory]:
        """
        调用 LLM 从对话记录中提取记忆点。

        使用 LLMGateway 配合轻量级提取 prompt。响应被解析为记忆对象
        的 JSON 数组。
        """
        gateway = get_llm_gateway()

        messages = [
            LLMMessage(
                role=LLMRole.SYSTEM,
                content=_EXTRACTION_SYSTEM_PROMPT,
            ),
            LLMMessage(
                role=LLMRole.USER,
                content=f"请分析以下对话并提取记忆点：\n\n{transcript}",
            ),
        ]

        request = LLMRequest(
            messages=messages,
            model=_EXTRACTION_MODEL,
            temperature=0.3,
            max_tokens=2048,
            stream=False,
            user_id="memory-extractor",
            session_id="",
        )

        response = await gateway.chat(request)
        raw_content = response.content.strip()

        # 从 LLM 响应中解析 JSON 数组
        return self._parse_extraction_response(raw_content)

    @staticmethod
    def _parse_extraction_response(raw: str) -> list[ExtractedMemory]:
        """
        将 LLM 提取响应解析为 ExtractedMemory 列表。

        处理常见的 LLM 输出问题：markdown 代码块、尾部文本和部分 JSON。
        """
        if not raw:
            return []

        # 如果存在则去除 markdown 代码块
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # 移除第一行（```json 或 ```）和最后一行的 ```
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        # 找到 JSON 数组边界
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.debug("No JSON array found in extraction response", raw=raw[:200])
            return []

        json_str = cleaned[start : end + 1]
        try:
            items = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Failed to parse extraction JSON",
                error=str(exc),
                raw=raw[:200],
            )
            return []

        if not isinstance(items, list):
            return []

        results: list[ExtractedMemory] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            memory_type_str = item.get("memory_type", "context")
            content = item.get("content", "")
            importance = item.get("importance", 0.5)
            if not content or not isinstance(content, str):
                continue
            try:
                importance = float(importance)
            except (ValueError, TypeError):
                importance = 0.5
            importance = max(0.0, min(1.0, importance))
            try:
                memory_type = MemoryType(memory_type_str)
            except ValueError:
                memory_type = MemoryType.CONTEXT
            results.append(
                ExtractedMemory(
                    memory_type=memory_type,
                    content=content.strip(),
                    importance=importance,
                )
            )

        return results


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_memory_injector: MemoryInjector | None = None


def get_memory_injector() -> MemoryInjector:
    """返回单例 MemoryInjector 实例。"""
    global _memory_injector
    if _memory_injector is None:
        _memory_injector = MemoryInjector()
    return _memory_injector
