"""
零售（超市）系统适配器 — 将超市管理 API 封装为 MCP 工具。

暴露的工具包括：商品、库存、促销、POS/收银、
会员、供应链和采购。
"""

from __future__ import annotations

from typing import Any

from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class RetailAdapter(BusinessSystemAdapter):
    """超市/零售管理系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        super().__init__(
            system_type="retail",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        self._tools = [
            ToolDefinition(
                name="query_products",
                description="查询商品信息，支持按条码、名称、分类筛选",
                category="retail",
                tags=["商品", "查询", "超市"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "barcode": {"type": "string", "description": "商品条码"},
                        "name": {"type": "string", "description": "商品名称（模糊匹配）"},
                        "category": {"type": "string", "description": "商品分类"},
                    },
                },
                required_permissions=["retail:product:read"],
            ),
            ToolDefinition(
                name="query_inventory",
                description="查询库存信息，支持按门店、商品筛选",
                category="retail",
                tags=["库存", "查询", "超市"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "store_id": {"type": "string", "description": "门店ID"},
                        "product_id": {"type": "string", "description": "商品ID"},
                        "low_stock_only": {"type": "boolean", "description": "仅显示低库存商品"},
                    },
                },
                required_permissions=["retail:inventory:read"],
            ),
            ToolDefinition(
                name="query_promotions",
                description="查询促销活动列表",
                category="retail",
                tags=["促销", "查询", "超市"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "store_id": {"type": "string", "description": "门店ID"},
                        "active_only": {"type": "boolean", "description": "仅显示进行中的活动"},
                    },
                },
                required_permissions=["retail:promotion:read"],
            ),
            ToolDefinition(
                name="query_sales_report",
                description="查询销售报表，支持按门店、日期范围筛选",
                category="retail",
                tags=["收银", "报表", "超市"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "store_id": {"type": "string", "description": "门店ID"},
                        "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                    },
                    "required": ["start_date", "end_date"],
                },
                required_permissions=["retail:sales:read"],
            ),
            ToolDefinition(
                name="query_supply_chain",
                description="查询供应链信息（供应商、采购单）",
                category="retail",
                tags=["供应链", "采购", "超市"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "supplier_id": {"type": "string", "description": "供应商ID"},
                        "po_number": {"type": "string", "description": "采购单号"},
                        "status": {"type": "string", "description": "采购单状态"},
                    },
                },
                required_permissions=["retail:supply:read"],
            ),
            ToolDefinition(
                name="create_purchase_order",
                description="创建采购订单",
                category="retail",
                tags=["采购", "创建", "超市"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "supplier_id": {"type": "string", "description": "供应商ID"},
                        "store_id": {"type": "string", "description": "收货门店ID"},
                        "items": {"type": "array", "items": {"type": "object"}, "description": "采购商品列表"},
                    },
                    "required": ["supplier_id", "store_id", "items"],
                },
                required_permissions=["retail:purchase:write"],
                requires_approval=True,
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        if tool_name == "query_products":
            data = await self._http_request("GET", "/api/products", credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "query_inventory":
            data = await self._http_request("GET", "/api/inventory", credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "query_promotions":
            data = await self._http_request("GET", "/api/promotions", credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "query_sales_report":
            data = await self._http_request("GET", "/api/sales/report", credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "query_supply_chain":
            data = await self._http_request("GET", "/api/supply-chain", credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "create_purchase_order":
            data = await self._http_request("POST", "/api/purchase-orders", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        else:
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
