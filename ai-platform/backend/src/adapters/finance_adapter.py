"""
财务系统适配器 — 将财务系统的 API 封装为 MCP 工具。

暴露的工具包括：报销单、预算、财务报表、
审批、发票、凭证和对账。
"""

from __future__ import annotations
from typing import Any


from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class FinanceAdapter(BusinessSystemAdapter):
    """财务业务系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        """初始化财务适配器并注册报销、预算、报表等工具。

        Args:
            base_url: 财务后端 API 基础 URL。
            timeout: HTTP 请求超时时间（秒）。
        """
        super().__init__(
            system_type="finance",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        """注册财务报销、预算、报表、发票、对账等 MCP 工具定义。"""
        self._tools = [
            ToolDefinition(
                name="query_expense_reports",
                description="查询报销单列表，支持按状态、日期范围、部门筛选",
                category="finance",
                tags=["报销", "查询", "财务"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "报销单状态: draft/pending/approved/rejected",
                        },
                        "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                        "department": {"type": "string", "description": "部门名称"},
                    },
                },
                required_permissions=["finance:expense:read"],
            ),
            ToolDefinition(
                name="create_expense_report",
                description="创建报销单",
                category="finance",
                tags=["报销", "创建", "财务"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "报销标题"},
                        "amount": {"type": "number", "description": "报销金额"},
                        "category": {"type": "string", "description": "费用类别"},
                        "description": {"type": "string", "description": "报销说明"},
                        "receipts": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "发票附件ID列表",
                        },
                    },
                    "required": ["title", "amount", "category"],
                },
                required_permissions=["finance:expense:write"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="query_budget",
                description="查询部门预算执行情况",
                category="finance",
                tags=["预算", "查询", "财务"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "department": {"type": "string", "description": "部门名称"},
                        "fiscal_year": {"type": "string", "description": "财政年度 YYYY"},
                        "fiscal_month": {"type": "integer", "description": "财政月份 1-12"},
                    },
                },
                required_permissions=["finance:budget:read"],
            ),
            ToolDefinition(
                name="query_financial_statements",
                description="查询财务报表（资产负债表/利润表/现金流量表）",
                category="finance",
                tags=["报表", "查询", "财务"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "statement_type": {
                            "type": "string",
                            "enum": ["balance_sheet", "income_statement", "cash_flow"],
                        },
                        "period": {"type": "string", "description": "报表期间 YYYY-MM"},
                    },
                    "required": ["statement_type", "period"],
                },
                required_permissions=["finance:statement:read"],
            ),
            ToolDefinition(
                name="query_invoices",
                description="查询发票信息",
                category="finance",
                tags=["发票", "查询", "财务"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "invoice_number": {"type": "string", "description": "发票号码"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                },
                required_permissions=["finance:invoice:read"],
            ),
            ToolDefinition(
                name="reconciliation",
                description="执行对账操作",
                category="finance",
                tags=["对账", "财务"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "账户ID"},
                        "period": {"type": "string", "description": "对账期间 YYYY-MM"},
                    },
                    "required": ["account_id", "period"],
                },
                required_permissions=["finance:reconciliation:execute"],
                requires_approval=True,
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        """将财务工具调用路由到对应的后端 HTTP 接口。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具参数字典。
            credential: 解密后的后端认证凭据。

        Returns:
            包含财务 API 响应数据或错误信息的 ``ToolResult``。
        """
        if tool_name == "query_expense_reports":
            data: dict[str, Any] = await self._http_request(
                "GET", "/api/expense-reports", credential, params=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "create_expense_report":
            data: dict[str, Any] = await self._http_request(
                "POST", "/api/expense-reports", credential, json_body=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "query_budget":
            data: dict[str, Any] = await self._http_request(
                "GET", "/api/budget", credential, params=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "query_financial_statements":
            data: dict[str, Any] = await self._http_request(
                "GET", "/api/statements", credential, params=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "query_invoices":
            data: dict[str, Any] = await self._http_request(
                "GET", "/api/invoices", credential, params=arguments
            )
            return ToolResult(success=True, data=data)
        elif tool_name == "reconciliation":
            data: dict[str, Any] = await self._http_request(
                "POST", "/api/reconciliation", credential, json_body=arguments
            )
            return ToolResult(success=True, data=data)
        else:
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
