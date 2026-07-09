"""
储值卡系统适配器 — 将储值卡 API 封装为 MCP 工具。

暴露的工具包括：发卡、充值、消费、
退款、余额查询、卡券管理、规则引擎和对账。
"""

from __future__ import annotations
from typing import Any


from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class ValueCardAdapter(BusinessSystemAdapter):
    """储值卡系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        """初始化储值卡适配器并注册发卡、充值、对账等工具。

        Args:
            base_url: 储值卡后端 API 基础 URL。
            timeout: HTTP 请求超时时间（秒）。
        """
        super().__init__(
            system_type="valuecard",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        """注册储值卡发卡、充值、余额、退款、对账等 MCP 工具定义。"""
        self._tools = [
            ToolDefinition(
                name="issue_card",
                description="发行储值卡",
                category="valuecard",
                tags=["发卡", "创建", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_type": {"type": "string", "description": "卡类型: standard/gift/virtual"},
                        "initial_value": {"type": "number", "description": "初始面值"},
                        "customer_name": {"type": "string", "description": "持卡人姓名"},
                        "customer_phone": {"type": "string", "description": "持卡人手机号"},
                    },
                    "required": ["card_type", "initial_value"],
                },
                required_permissions=["valuecard:issue:write"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="recharge_card",
                description="储值卡充值",
                category="valuecard",
                tags=["充值", "操作", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_number": {"type": "string", "description": "卡号"},
                        "amount": {"type": "number", "description": "充值金额"},
                        "payment_method": {"type": "string", "description": "支付方式"},
                    },
                    "required": ["card_number", "amount"],
                },
                required_permissions=["valuecard:recharge:write"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="query_balance",
                description="查询储值卡余额",
                category="valuecard",
                tags=["余额", "查询", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_number": {"type": "string", "description": "卡号"},
                    },
                    "required": ["card_number"],
                },
                required_permissions=["valuecard:balance:read"],
            ),
            ToolDefinition(
                name="query_consumption_records",
                description="查询储值卡消费记录",
                category="valuecard",
                tags=["消费", "查询", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_number": {"type": "string", "description": "卡号"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                    "required": ["card_number"],
                },
                required_permissions=["valuecard:consumption:read"],
            ),
            ToolDefinition(
                name="refund_card",
                description="储值卡退款",
                category="valuecard",
                tags=["退款", "操作", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_number": {"type": "string", "description": "卡号"},
                        "amount": {"type": "number", "description": "退款金额"},
                        "reason": {"type": "string", "description": "退款原因"},
                    },
                    "required": ["card_number", "amount", "reason"],
                },
                required_permissions=["valuecard:refund:write"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="query_card_coupons",
                description="查询卡券信息（关联的优惠券、代金券）",
                category="valuecard",
                tags=["卡券", "查询", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_number": {"type": "string", "description": "卡号"},
                        "status": {"type": "string", "description": "卡券状态: active/used/expired"},
                    },
                },
                required_permissions=["valuecard:coupon:read"],
            ),
            ToolDefinition(
                name="query_card_rules",
                description="查询储值卡规则引擎配置（折扣、积分规则等）",
                category="valuecard",
                tags=["规则引擎", "查询", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "card_type": {"type": "string", "description": "卡类型"},
                    },
                },
                required_permissions=["valuecard:rules:read"],
            ),
            ToolDefinition(
                name="reconciliation",
                description="储值卡对账（核对消费与充值记录）",
                category="valuecard",
                tags=["对账", "储值卡"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "period": {"type": "string", "description": "对账期间 YYYY-MM"},
                    },
                    "required": ["period"],
                },
                required_permissions=["valuecard:reconciliation:execute"],
                requires_approval=True,
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        """将储值卡工具调用路由到对应的后端 HTTP 接口。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具参数字典。
            credential: 解密后的后端认证凭据。

        Returns:
            包含储值卡 API 响应数据或错误信息的 ``ToolResult``。
        """
        get_tools: dict[str, Any] = {
            "query_balance": "/api/cards/balance",
            "query_consumption_records": "/api/cards/consumption",
            "query_card_coupons": "/api/cards/coupons",
            "query_card_rules": "/api/cards/rules",
        }
        if tool_name in get_tools:
            data: dict[str, Any] = await self._http_request("GET", get_tools[tool_name], credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "issue_card":
            data: dict[str, Any] = await self._http_request("POST", "/api/cards/issue", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "recharge_card":
            data: dict[str, Any] = await self._http_request("POST", "/api/cards/recharge", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "refund_card":
            data: dict[str, Any] = await self._http_request("POST", "/api/cards/refund", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "reconciliation":
            data: dict[str, Any] = await self._http_request("POST", "/api/cards/reconciliation", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
