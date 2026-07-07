# CRM callApi 调用约定（会员积分域）

## MCP 连接

- **MCP 服务名**：`mcp-api-suite`
- **工具名**：`callApi`

## 约束

- 勿传 `serviceName`
- 会员域 **勿传 `datasourceId`**
- `apiName` 仅允许：`getMemberPointsBalanceByVipId`、`listMemberPointsLedgerByVipId`

## 会员身份

- 本域接口均要求 `vipId`；仅有手机号/卡号时，先通过 `member-profile` 解析 `vipId`
