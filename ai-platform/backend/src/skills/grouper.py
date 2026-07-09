"""
SkillGrouper — 按业务系统对 Skills 进行分类和分组。

提供基于分类的过滤以优化 Qdrant 检索：当某个
分类包含超过 50 个 Skill 时，检索器会向 Qdrant
传递 payload 过滤器以限制搜索范围，降低延迟。
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog

from src.skills.models import SkillCategory

if TYPE_CHECKING:
    from src.skills.models import Skill

logger = structlog.get_logger(__name__)

# 阈值：如果分类中的 Skill 数量超过此值，启用分类过滤。
CATEGORY_FILTER_THRESHOLD = 50

# 从分类到其子标签/二级关键词的映射。
# 当 ``category`` 字段未显式设置时，
# 用于从标签推断 Skill 的分类。
_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    SkillCategory.FINANCE: {
        "报销", "预算", "报表", "审批", "发票", "凭证", "对账", "财务",
    },
    SkillCategory.RETAIL: {
        "商品", "库存", "促销", "收银", "会员", "供应链", "采购", "超市",
    },
    SkillCategory.DEPARTMENT_STORE: {
        "柜位", "品牌", "合同", "租金", "销售", "客流", "坪效", "百货",
    },
    SkillCategory.HR: {
        "请假", "薪资", "组织架构", "招聘", "培训", "考勤", "绩效", "人事",
    },
    SkillCategory.PROPERTY: {
        "报修", "巡检", "能耗", "安防", "保洁", "停车", "合同", "物业",
    },
    SkillCategory.CRM: {
        "会员", "积分", "等级", "标签", "画像", "营销活动", "客户旅程", "CRM",
    },
    SkillCategory.VALUECARD: {
        "发卡", "充值", "消费", "退款", "余额查询", "卡券", "规则引擎", "对账", "储值卡",
    },
    SkillCategory.BUILT_IN: {
        "搜索", "计算", "文档", "通知", "日历", "数据导出", "通用",
    },
}


class SkillGrouper:
    """按分类对 Skills 进行分组，并计算检索过滤提示。"""

    def __init__(self) -> None:
        """初始化分组器（各分类 Skill 计数为空）。"""
        self._category_counts: dict[str, int] = {}

    def update_counts(self, skills: list[Skill]) -> None:
        """根据 *skills* 重新计算每个分类的 Skill 数量。"""
        counts: dict[str, int] = {}
        for skill in skills:
            counts[skill.category] = counts.get(skill.category, 0) + 1
        self._category_counts = counts
        logger.debug("SkillGrouper counts updated", counts=counts)

    def get_count(self, category: str) -> int:
        """返回 *category* 中的 Skill 数量。"""
        return self._category_counts.get(category, 0)

    def should_filter_by_category(self, category: str) -> bool:
        """如果 *category* 的 Skill 足够多，返回 True 表示需要 payload 过滤。"""
        return self.get_count(category) > CATEGORY_FILTER_THRESHOLD

    def infer_category(self, skill: Skill) -> str:
        """从 *skill* 的标签和描述推断其分类。

        如果 skill 已有非默认分类，直接返回。
        否则，尝试将标签与关键词映射匹配。
        """
        if skill.category and skill.category != SkillCategory.BUILT_IN:
            return skill.category

        tag_set: set[Any] = set(skill.tags)
        # 同时从名称/描述中提取单词以进行更广泛的匹配
        words: set[Any] = set()
        for text in (skill.name, skill.description):
            for char_group in text:
                words.add(char_group)
        tag_set |= words

        best_category: Any = SkillCategory.BUILT_IN
        best_overlap: int = 0
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            overlap: Any = len(tag_set & keywords)
            if overlap > best_overlap:
                best_overlap: Any = overlap
                best_category: Any = cat

        return best_category

    def get_candidate_categories(
        self,
        user_categories: list[str] | None,
    ) -> list[str] | None:
        """确定用户的候选分类集合。

        返回 ``None`` 表示"搜索所有分类"（不过滤），
        或返回一个分类列表以限制 Qdrant 搜索范围。
        """
        if not user_categories:
            return None

        # 仅当至少有一个分类超过阈值时才过滤
        big_categories: list[Any] = [
            cat for cat in user_categories if self.should_filter_by_category(cat)
        ]
        if not big_categories:
            return None

        # 如果用户只能访问部分分类，始终过滤
        if len(user_categories) <= 3:
            return user_categories

        return big_categories if big_categories else None

    def all_categories(self) -> list[str]:
        """返回所有已知的分类标识符。"""
        return list(_CATEGORY_KEYWORDS.keys())
