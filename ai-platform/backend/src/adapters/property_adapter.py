"""
物业管理系统适配器 — 将物业管理 API 封装为 MCP 工具。

暴露的工具包括：报修申请、巡检、能耗、
安防、保洁、停车和合同。
"""

from __future__ import annotations

from typing import Any

from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class PropertyAdapter(BusinessSystemAdapter):
    """物业管理系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        """初始化物业适配器并注册报修、巡检、能耗等工具。

        Args:
            base_url: 物业后端 API 基础 URL。
            timeout: HTTP 请求超时时间（秒）。
        """
        super().__init__(
            system_type="property",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        """注册物业报修、巡检、能耗、安防、停车等 MCP 工具定义。"""
        self._tools = [
            ToolDefinition(
                name="create_repair_request",
                description="提交报修申请",
                category="property",
                tags=["报修", "创建", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "报修位置"},
                        "category": {"type": "string", "description": "维修类别: electrical/plumbing/hvac/structural"},
                        "description": {"type": "string", "description": "故障描述"},
                        "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                    },
                    "required": ["location", "category", "description"],
                },
                required_permissions=["property:repair:write"],
            ),
            ToolDefinition(
                name="query_repair_status",
                description="查询报修单状态",
                category="property",
                tags=["报修", "查询", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {"type": "string", "description": "报修单号"},
                        "status": {"type": "string", "description": "状态筛选"},
                    },
                },
                required_permissions=["property:repair:read"],
            ),
            ToolDefinition(
                name="query_inspection_records",
                description="查询巡检记录",
                category="property",
                tags=["巡检", "查询", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "area": {"type": "string", "description": "巡检区域"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                },
                required_permissions=["property:inspection:read"],
            ),
            ToolDefinition(
                name="query_energy_consumption",
                description="查询能耗数据（水、电、燃气）",
                category="property",
                tags=["能耗", "查询", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "building_id": {"type": "string", "description": "楼宇ID"},
                        "energy_type": {"type": "string", "enum": ["water", "electricity", "gas"]},
                        "period": {"type": "string", "description": "期间 YYYY-MM"},
                    },
                    "required": ["period"],
                },
                required_permissions=["property:energy:read"],
            ),
            ToolDefinition(
                name="query_security_records",
                description="查询安防记录",
                category="property",
                tags=["安防", "查询", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "area": {"type": "string", "description": "安防区域"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                },
                required_permissions=["property:security:read"],
            ),
            ToolDefinition(
                name="query_parking_status",
                description="查询停车场状态",
                category="property",
                tags=["停车", "查询", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "parking_lot_id": {"type": "string", "description": "停车场ID"},
                    },
                },
                required_permissions=["property:parking:read"],
            ),
            ToolDefinition(
                name="query_property_contracts",
                description="查询物业合同",
                category="property",
                tags=["合同", "查询", "物业"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "contract_number": {"type": "string", "description": "合同编号"},
                        "status": {"type": "string", "description": "合同状态"},
                    },
                },
                required_permissions=["property:contract:read"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        """将物业工具调用路由到对应的后端 HTTP 接口。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具参数字典。
            credential: 解密后的后端认证凭据。

        Returns:
            包含物业 API 响应数据或错误信息的 ``ToolResult``。
        """
        get_tools = {
            "query_repair_status": "/api/repairs",
            "query_inspection_records": "/api/inspections",
            "query_energy_consumption": "/api/energy",
            "query_security_records": "/api/security",
            "query_parking_status": "/api/parking",
            "query_property_contracts": "/api/contracts",
        }
        if tool_name in get_tools:
            data = await self._http_request("GET", get_tools[tool_name], credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "create_repair_request":
            data = await self._http_request("POST", "/api/repairs", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
