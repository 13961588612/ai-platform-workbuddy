---
name: member.points-account
skill_id: member.points-account
description: CRM 会员积分账户查询与积分流水检索。当用户需要查询会员积分余额、按会员编号查看积分变动明细、或按时间范围筛选积分流水时触发此 Skill。
version: "1.0.0"
category: crm
tags:
  - 会员
  - 积分
  - 积分余额
  - 积分流水
  - vipId
  - CRM
  - member.points-account
source: package
status: active
timeout: 30
requires_approval: false
required_permissions:
  - crm:member:read
handler: mcp:mcp-api-suite:callApi
mcp_server: mcp-api-suite
inputSchema:
  type: object
  additionalProperties: false
  properties:
    apiName:
      type: string
      description: CRM 会员积分域接口名
      enum:
        - getMemberPointsBalanceByVipId
        - listMemberPointsLedgerByVipId
    params:
      type: object
      additionalProperties: false
      description: 会员积分域参数，勿传 datasourceId 或 serviceName
      properties:
        vipId:
          type: string
          description: 会员编号
        beginDate:
          type: string
          description: 流水起始日期（ISO 日期，如 2026-01-01），仅 listMemberPointsLedgerByVipId 可选
        endDate:
          type: string
          description: 流水截止日期（ISO 日期，如 2026-12-31），仅 listMemberPointsLedgerByVipId 可选
  required:
    - apiName
    - params
---

# 会员积分账户（member.points-account）

本文档供 **WorkBuddy / QwenPaw** 生成 Skill 使用：描述会员积分余额与积分变动明细的字段，以及如何通过 MCP 工具 **`callApi`** 查询数据。

## MCP 与调用前提

- WorkBuddy / QwenPaw 中已配置 MCP 服务，**名称为 `mcp-api-suite`**（与下文的工具调用对应）。
- 所有接口均通过该服务上的工具 **`callApi`** 调用：传入 **`apiName`**（字符串）与 **`params`**（对象）。
- 进程内查询时不要传 **`serviceName`**，或传空/省略。
- **会员域**接口的 **`params` 中不需要、也不要传 `datasourceId`**。

## 会员身份前提

- 本 Skill 的接口均以 **`vipId`（会员编号）** 为查询条件。
- 若用户仅提供手机号、会员卡号等，**先**通过 `member-profile` Skill 解析出 `vipId`，再调用本 Skill 查询积分。

## 1 数据与字段说明

### 1.1 积分余额（`bfcrm8.hyk_mdjf` 汇总）

| 字段 | 类型 | 含义 | 可空 | 示例 |
|------|------|------|------|------|
| `vipId` | `string` | 会员编号 | 否 | `"10001"` |
| `memberCardNo` | `string` | 会员卡号 | 是 | `"88000001"` |
| `totalPoints` | `number` | 总积分 / 剩余积分（按会员聚合） | 否 | `1280` |

### 1.2 积分变动明细（`bfcrm8.hyk_jfbdjlmx` ∪ `bfcrm8.hyk_jfbdjlmx_cs`；按 `clsj` 筛选后按变动时间降序）

| 字段 | 类型 | 含义 | 可空 | 示例 |
|------|------|------|------|------|
| `vipId` | `string` | 会员编号 | 否 | `"10001"` |
| `pointsDelta` | `number` | 本次积分变动量 | 否 | `100` 或 `-50` |
| `changeTime` | `string` | 变动时间 | 否 | `"2026-01-15 10:30:00"` |
| `reason` | `string` | 变动原因（处理类型说明） | 是 | `"消费积分"` |
| `storeName` | `string` | 操作门店 | 是 | `"南京路店"` |

## 2 能力清单（工具 `callApi`）

在 MCP 服务 **`mcp-api-suite`** 上调用 **`callApi`**，请求体为 JSON，至少包含：

| 字段 | 含义 |
|------|------|
| `apiName` | 各小节中的「接口名」 |
| `params` | 各小节列出的参数（**不含** `datasourceId`） |

### 2.1 根据会员编号查询积分余额

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `getMemberPointsBalanceByVipId` |
| `params` | `vipId`（会员编号） |
| 返回 | 单条对象，字段见 **1.1**；无记录时 `{ "found": false }` |

示例：

```json
{
  "apiName": "getMemberPointsBalanceByVipId",
  "params": {
    "vipId": "10001"
  }
}
```

### 2.2 根据会员编号查询积分流水

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberPointsLedgerByVipId` |
| `params` | `vipId`（会员编号，必填） |
| `params` 可选 | `beginDate`、`endDate`：均为 **ISO 日期字符串**（如 `"2026-01-01"`）；可省略。省略时由服务端对绑定参数使用 SQL 中的默认时间窗（与 `nvl(?, …)` 一致，约近 365 天至当日区间）。若传入，须为合法日期字符串。底层 SQL 对两段 `union all` 使用相同时间条件（`clsj`），调用方仍只传一组 `beginDate`/`endDate`。 |
| 返回 | `{ "items": [ ... ] }`，元素字段见 **1.2** |

示例（仅会员编号，使用默认时间窗）：

```json
{
  "apiName": "listMemberPointsLedgerByVipId",
  "params": {
    "vipId": "10001"
  }
}
```

示例（带起止日期）：

```json
{
  "apiName": "listMemberPointsLedgerByVipId",
  "params": {
    "vipId": "10001",
    "beginDate": "2026-01-01",
    "endDate": "2026-12-31"
  }
}
```

## 3 术语

- **会员编号**：`params` 与返回 JSON 中的 `vipId`。
- **会员数据源**：由服务端固定为 **`crm`**，调用方**勿**在 `params` 中传 `datasourceId`。
- **积分流水时间范围**：`beginDate` / `endDate` 为可选；传参规则见 **2.2**。
