"""
百货系统适配器 — 将百货管理 API 封装为 MCP 工具。

暴露的工具包括：柜位/展位、品牌、合同、租金、销售、
客流和坪效。
"""

from __future__ import annotations
from typing import Any


from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class DepartmentStoreAdapter(BusinessSystemAdapter):
    """百货管理系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        """初始化百货适配器并注册柜位、品牌、销售等工具。

        Args:
            base_url: 百货后端 API 基础 URL。
            timeout: HTTP 请求超时时间（秒）。
        """
        super().__init__(
            system_type="department_store",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        """注册百货柜位、品牌、合同、租金、客流等 MCP 工具定义。"""
        self._tools = [
            ToolDefinition(
                name="query_counters",
                description="查询柜位信息，支持按楼层、品牌筛选",
                category="department_store",
                tags=["柜位", "查询", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "floor": {"type": "string", "description": "楼层"},
                        "brand_id": {"type": "string", "description": "品牌ID"},
                        "status": {"type": "string", "description": "柜位状态"},
                    },
                },
                required_permissions=["dept_store:counter:read"],
            ),
            ToolDefinition(
                name="query_brands",
                description="查询品牌信息",
                category="department_store",
                tags=["品牌", "查询", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "品牌名称（模糊匹配）"},
                        "category": {"type": "string", "description": "品牌类别"},
                    },
                },
                required_permissions=["dept_store:brand:read"],
            ),
            ToolDefinition(
                name="query_contracts",
                description="查询合同信息（租赁合同、联营合同）",
                category="department_store",
                tags=["合同", "查询", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "contract_number": {"type": "string", "description": "合同编号"},
                        "brand_id": {"type": "string", "description": "品牌ID"},
                        "status": {"type": "string", "description": "合同状态"},
                    },
                },
                required_permissions=["dept_store:contract:read"],
            ),
            ToolDefinition(
                name="query_rent",
                description="查询租金收取情况",
                category="department_store",
                tags=["租金", "查询", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "counter_id": {"type": "string", "description": "柜位ID"},
                        "period": {"type": "string", "description": "期间 YYYY-MM"},
                    },
                },
                required_permissions=["dept_store:rent:read"],
            ),
            ToolDefinition(
                name="query_sales_data",
                description="查询销售数据，支持按柜位、品牌、日期筛选",
                category="department_store",
                tags=["销售", "查询", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "counter_id": {"type": "string", "description": "柜位ID"},
                        "brand_id": {"type": "string", "description": "品牌ID"},
                        "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    },
                    "required": ["start_date", "end_date"],
                },
                required_permissions=["dept_store:sales:read"],
            ),
            ToolDefinition(
                name="query_foot_traffic",
                description="查询客流数据",
                category="department_store",
                tags=["客流", "查询", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "entrance_id": {"type": "string", "description": "入口ID"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                    "required": ["start_date", "end_date"],
                },
                required_permissions=["dept_store:traffic:read"],
            ),
            ToolDefinition(
                name="query_sales_efficiency",
                description="查询坪效（单位面积销售额）分析",
                category="department_store",
                tags=["坪效", "分析", "百货"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "floor": {"type": "string", "description": "楼层"},
                        "period": {"type": "string", "description": "期间 YYYY-MM"},
                    },
                    "required": ["period"],
                },
                required_permissions=["dept_store:efficiency:read"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        """将百货工具调用路由到对应的后端 HTTP 接口。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具参数字典。
            credential: 解密后的后端认证凭据。

        Returns:
            包含百货 API 响应数据或错误信息的 ``ToolResult``。
        """
        route_map: dict[str, Any] = {
            "query_counters": ("GET", "/api/counters"),
            "query_brands": ("GET", "/api/brands"),
            "query_contracts": ("GET", "/api/contracts"),
            "query_rent": ("GET", "/api/rent"),
            "query_sales_data": ("GET", "/api/sales"),
            "query_foot_traffic": ("GET", "/api/traffic"),
            "query_sales_efficiency": ("GET", "/api/efficiency"),
        }
        if tool_name in route_map:
            method: str
            path: str
            method, path = route_map[tool_name]
            data: dict[str, Any] = await self._http_request(
                method, path, credential, params=arguments
            )
            return ToolResult(success=True, data=data)
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
