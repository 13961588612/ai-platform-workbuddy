# CRM callApi 调用约定（会员档案域）

## MCP 连接

- **MCP 服务名**：`mcp-api-suite`
- **工具名**：`callApi`

## 约束

- 勿传 `serviceName`
- 会员域 **勿传 `datasourceId`**

## 身份字段默认约定

- 11 位数字且未说明类型 → `getMemberProfileByMobile`
- 明确会员编号 / 卡号 / 车牌 → 见 SKILL.md 映射表
