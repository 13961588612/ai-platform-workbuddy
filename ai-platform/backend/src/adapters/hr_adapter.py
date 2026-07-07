"""
HR 系统适配器 — 将人力资源系统的 API 封装为 MCP 工具。

暴露的工具包括：假期管理、薪资、组织架构、
招聘、培训、考勤和绩效。
"""

from __future__ import annotations

from typing import Any

from src.adapters.base import BusinessSystemAdapter, ToolDefinition, ToolResult


class HRAdapter(BusinessSystemAdapter):
    """HR（人力资源）系统的适配器。"""

    def __init__(self, base_url: str = "", timeout: float = 30.0) -> None:
        super().__init__(
            system_type="hr",
            base_url=base_url,
            timeout=timeout,
        )

    def _define_tools(self) -> None:
        self._tools = [
            ToolDefinition(
                name="query_leave_balance",
                description="查询员工假期余额（年假、事假、病假等）",
                category="hr",
                tags=["请假", "查询", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string", "description": "员工工号"},
                        "leave_type": {"type": "string", "description": "假期类型: annual/sick/personal"},
                    },
                    "required": ["employee_id"],
                },
                required_permissions=["hr:leave:read"],
            ),
            ToolDefinition(
                name="apply_leave",
                description="提交请假申请",
                category="hr",
                tags=["请假", "申请", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string", "description": "员工工号"},
                        "leave_type": {"type": "string", "description": "假期类型"},
                        "start_date": {"type": "string", "description": "开始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                        "reason": {"type": "string", "description": "请假原因"},
                    },
                    "required": ["employee_id", "leave_type", "start_date", "end_date"],
                },
                required_permissions=["hr:leave:write"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="query_salary_slip",
                description="查询工资条",
                category="hr",
                tags=["薪资", "查询", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string", "description": "员工工号"},
                        "period": {"type": "string", "description": "工资期间 YYYY-MM"},
                    },
                    "required": ["employee_id", "period"],
                },
                required_permissions=["hr:salary:read"],
                requires_approval=True,
            ),
            ToolDefinition(
                name="query_org_structure",
                description="查询组织架构（部门、汇报关系）",
                category="hr",
                tags=["组织架构", "查询", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "department_id": {"type": "string", "description": "部门ID"},
                        "include_members": {"type": "boolean", "description": "是否包含成员列表"},
                    },
                },
                required_permissions=["hr:org:read"],
            ),
            ToolDefinition(
                name="query_attendance",
                description="查询考勤记录",
                category="hr",
                tags=["考勤", "查询", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string", "description": "员工工号"},
                        "start_date": {"type": "string", "description": "起始日期"},
                        "end_date": {"type": "string", "description": "结束日期"},
                    },
                    "required": ["employee_id", "start_date", "end_date"],
                },
                required_permissions=["hr:attendance:read"],
            ),
            ToolDefinition(
                name="query_performance",
                description="查询绩效评估结果",
                category="hr",
                tags=["绩效", "查询", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string", "description": "员工工号"},
                        "period": {"type": "string", "description": "考核期间"},
                    },
                    "required": ["employee_id", "period"],
                },
                required_permissions=["hr:performance:read"],
            ),
            ToolDefinition(
                name="query_training_records",
                description="查询培训记录",
                category="hr",
                tags=["培训", "查询", "人事"],
                input_schema={
                    "type": "object",
                    "properties": {
                        "employee_id": {"type": "string", "description": "员工工号"},
                        "course_name": {"type": "string", "description": "课程名称"},
                    },
                },
                required_permissions=["hr:training:read"],
            ),
        ]

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        get_tools = {
            "query_leave_balance": "/api/leave/balance",
            "query_salary_slip": "/api/salary/slip",
            "query_org_structure": "/api/org/structure",
            "query_attendance": "/api/attendance",
            "query_performance": "/api/performance",
            "query_training_records": "/api/training/records",
        }
        if tool_name in get_tools:
            data = await self._http_request("GET", get_tools[tool_name], credential, params=arguments)
            return ToolResult(success=True, data=data)
        elif tool_name == "apply_leave":
            data = await self._http_request("POST", "/api/leave/apply", credential, json_body=arguments)
            return ToolResult(success=True, data=data)
        return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
