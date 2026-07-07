# CRM callApi 调用约定（会员券域）

## MCP 连接

- **MCP 服务名**：`mcp-api-suite`
- **工具名**：`callApi`

## 约束

- 勿传 `serviceName`
- 会员域 **勿传 `datasourceId`**
- `apiName` 须来自本 Skill 文档，禁止猜测

## 券账户 apiName

- `listMemberAccountCouponsByVipId` — 账户券
- `listMemberElectronicCouponsByVipId` — 电子纸券
- `listMemberSmartMallCouponsByVipId` — 智慧购券
- `listMemberParkingCouponsByVipId` — 停车券
- `listMemberCanUseCouponsByVipId` — 合并可用券

## 券流水 apiName

- `listMemberAccountCouponLedger`
- `listMemberElectronicCouponLedger`
- `listMemberParkingCouponLedger`
- `listMemberSmartMallCouponLedger`

## 会员身份

- 多数接口要求 `vipId`；仅有手机号/卡号时，先通过 `member-profile` 解析 `vipId`
