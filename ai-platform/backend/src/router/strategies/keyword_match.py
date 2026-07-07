"""KeywordMatchStrategy — 基于关键词匹配进行路由。

将用户输入文本与每个 Agent 的 routing.keywords 列表进行匹配。
关键词出现在文本中的第一个 Agent 胜出（按优先级排序）。
"""

from __future__ import annotations

from typing import Any

from src.router.models import RouteResult, SessionContext, UserRequest
from src.router.strategies.base import RoutingStrategy
from src.utils.logging import get_logger

logger = get_logger("router.keyword_match")


class KeywordMatchStrategy(RoutingStrategy):
    """
    基于关键词匹配 Agent 路由配置进行路由。

    按 routing.priority 降序遍历候选列表，
    检查 Agent 的任意关键词是否出现在用户输入文本中。
    """

    @property
    def name(self) -> str:
        return "keyword_matching"

    @property
    def priority(self) -> int:
        return 2

    async def route(
        self,
        request: UserRequest,
        candidates: list[Any],
        session_ctx: SessionContext,
    ) -> RouteResult | None:
        """将用户输入与 Agent 关键词进行匹配。"""
        text = request.text.lower()

        # 按路由优先级排序（越高越优先）
        sorted_candidates = sorted(
            [c for c in candidates if c.routing.enabled and c.routing.keywords],
            key=lambda c: c.routing.priority,
            reverse=True,
        )

        for candidate in sorted_candidates:
            if self.match_keywords(text, [kw.lower() for kw in candidate.routing.keywords]):
                logger.info(
                    "Keyword match",
                    agent_id=candidate.agent_id,
                    matched_keywords=[
                        kw for kw in candidate.routing.keywords
                        if kw.lower() in text
                    ],
                )
                return RouteResult(
                    agent_id=candidate.agent_id,
                    strategy_used=self.name,
                    confidence=0.9,
                    metadata={
                        "reason": "keyword_match",
                        "matched_keywords": [
                            kw for kw in candidate.routing.keywords
                            if kw.lower() in text
                        ],
                    },
                )

        return None

    def is_applicable(
        self,
        request: UserRequest,
        session_ctx: SessionContext,
    ) -> bool:
        """当用户提供了输入文本时适用。"""
        return len(request.text.strip()) > 0

    def match_keywords(self, text: str, keywords: list[str]) -> bool:
        """
        检查任意关键词是否出现在文本中。

        Args:
            text: 小写化后的用户输入文本。
            keywords: 要匹配的小写关键词列表。

        Returns:
            如果在文本中找到任意关键词则返回 True。
        """
        return any(kw in text for kw in keywords if kw)
