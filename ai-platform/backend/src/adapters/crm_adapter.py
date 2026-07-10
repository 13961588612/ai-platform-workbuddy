"""
CRM 系统适配器 — 将 CRM 系统 API 封装为 MCP 工具。

暴露的工具包括：会员管理、积分、等级/级别、标签、
客户画像、营销活动和客户旅程追踪。
"""

from __future__ import annotations
from typing import Any


from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class CRMAdapter(BusinessSystemAdapter):
    """CRM（客户关系管理）系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        """初始化 CRM 适配器并注册会员、积分等工具。

        Args:
            base_url: CRM 后端 API 基础 URL。
            timeout: HTTP 请求超时时间（秒）。
        """
        super().__init__(
            system_type="crm",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        """注册 CRM 会员、积分、标签、营销活动等 MCP 工具定义。"""
        self._tools = [
            ToolDefinition(
                name="query_member",
                description="查询会员信息，支持按手机号、卡号、姓名筛选",
                category="crm",
                tags=["会员", "查询", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string", "description": "手机号"},
                        "card_number": {"type": "string", "description": "会员卡号"},
                        "name": {"type": "string", "description": "姓名"},
                    },
                },
                required_permissions=["crm:member:read"],
            ),
            ToolDefinition(
                name="query_member_points",
                description="查询会员积分余额及明细",
                category="crm",
                tags=["积分", "查询", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "会员ID"},
                        "include_history": {
                            "type": "boolean",
                            "description": "是否包含积分变动明细",
                        },
                    },
                    "required": ["member_id"],
                },
                required_permissions=["crm:points:read"],
            ),
            ToolDefinition(
                name="adjust_member_points",
                description="调整会员积分（手动加扣分）",
                category="crm",
                tags=["积分", "调整", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "会员ID"},
                        "amount": {
                            "type": "integer",
                            "description": "积分变动数量（正数加分，负数扣分）",
                        },
                        "reason": {"type": "string", "description": "调整原因"},
                    },
                    "required": ["member_id", "amount", "reason"],
                },
                required_permissions=["crm:points:write"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="query_member_tier",
                description="查询会员等级信息",
                category="crm",
                tags=["等级", "查询", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "会员ID"},
                    },
                    "required": ["member_id"],
                },
                required_permissions=["crm:tier:read"],
            ),
            ToolDefinition(
                name="update_member_tags",
                description="更新会员标签",
                category="crm",
                tags=["标签", "更新", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "会员ID"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "标签列表",
                        },
                        "operation": {
                            "type": "string",
                            "enum": ["add", "remove", "replace"],
                            "description": "操作类型",
                        },
                    },
                    "required": ["member_id", "tags", "operation"],
                },
                required_permissions=["crm:tags:write"],
            ),
            ToolDefinition(
                name="query_member_profile",
                description="查询会员画像（消费偏好、活跃度等）",
                category="crm",
                tags=["画像", "查询", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "会员ID"},
                    },
                    "required": ["member_id"],
                },
                required_permissions=["crm:profile:read"],
            ),
            ToolDefinition(
                name="query_marketing_campaigns",
                description="查询营销活动列表",
                category="crm",
                tags=["营销活动", "查询", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "活动状态: planned/active/ended",
                        },
                        "campaign_type": {"type": "string", "description": "活动类型"},
                    },
                },
                required_permissions=["crm:campaign:read"],
            ),
            ToolDefinition(
                name="query_customer_journey",
                description="查询客户旅程（消费记录、触点、生命周期阶段）",
                category="crm",
                tags=["客户旅程", "查询", "CRM"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "member_id": {"type": "string", "description": "会员ID"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                    "required": ["member_id"],
                },
                required_permissions=["crm:journey:read"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        """将 CRM 工具调用路由到对应的后端 HTTP 接口。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具参数字典。
            credential: 解密后的后端认证凭据。

        Returns:
            包含 CRM API 响应数据或错误信息的 ``ToolResult``。
        """
        get_tools: dict[str, Any] = {
            "query_member": "/api/members",
            "query_member_points": "/api/members/points",
            "query_member_tier": "/api/members/tier",
            "query_member_profile": "/api/members/profile",
            "query_marketing_campaigns": "/api/campaigns",
            "query_customer_journey": "/api/members/journey",
        }
        if tool_name in get_tools:
            data: dict[str, Any] = await self._http_request(
                "GET", get_tools[tool_name], credential, params=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "adjust_member_points":
            data: dict[str, Any] = await self._http_request(
                "POST", "/api/members/points/adjust", credential, json_body=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "update_member_tags":
            data: dict[str, Any] = await self._http_request(
                "PUT", "/api/members/tags", credential, json_body=arguments
            )
            return ToolResult(success=True, data=data)
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
