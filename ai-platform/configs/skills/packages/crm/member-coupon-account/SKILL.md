---
name: member.coupons-account
skill_id: member.coupons-account
description: CRM/ZHG 会员券账户与券使用流水查询。当用户需要查询账户券/电子纸券/智慧购券/停车券余额、筛选可用券、或按条件检索券使用流水时触发此 Skill。
version: "1.0.0"
category: crm
tags:
  - 会员
  - 优惠券
  - 券账户
  - 券流水
  - 账户券
  - 电子纸券
  - 智慧购券
  - 停车券
  - vipId
  - CRM
  - member.coupons-account
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
      description: CRM/ZHG 会员券域接口名
      enum:
        - listMemberAccountCouponsByVipId
        - listMemberElectronicCouponsByVipId
        - listMemberSmartMallCouponsByVipId
        - listMemberParkingCouponsByVipId
        - listMemberCanUseCouponsByVipId
        - listMemberAccountCouponLedger
        - listMemberElectronicCouponLedger
        - listMemberParkingCouponLedger
        - listMemberSmartMallCouponLedger
    params:
      type: object
      additionalProperties: false
      description: 会员券域参数，勿传 datasourceId 或 serviceName
      properties:
        vipId:
          type: string
          description: 会员编号（部分流水/停车场景服务端映射为 hyid 或 user_id）
        beginDate:
          type: string
          description: 券账户查询时间下界（ISO 日期），仅券账户类接口可选
        couponSourceName:
          type: string
          description: 券来源，须与 SQL 字面值一致（账户券/电子纸券/停车券/智慧购券），流水类接口可选
        dealDate:
          type: string
          description: 券流水处理时间下界（ISO 日期），仅账户券/电子纸券流水可选
        couponTypeId:
          type: string
          description: 券类型 id，仅 listMemberAccountCouponLedger 可选
        couponEndDate:
          type: string
          description: 券有效止，仅 listMemberAccountCouponLedger 可选
        couponCode:
          type: string
          description: 券号/实例标识，停车券/智慧购券流水可选
  required:
    - apiName
    - params
---

# 会员券账户与使用流水（member.coupons-account）

本文档供 **WorkBuddy / QwenPaw** 生成 Skill 使用：描述会员**券账户**（多来源）与**券使用流水**的字段，以及如何通过 MCP 工具 **`callApi`** 查询数据。

## MCP 与调用前提

- WorkBuddy / QwenPaw 中已配置 MCP 服务，**名称为 `mcp-api-suite`**（与下文的工具调用对应）。
- 所有接口均通过该服务上的工具 **`callApi`** 调用：传入 **`apiName`**（字符串）与 **`params`**（对象）。
- 进程内查询时不要传 **`serviceName`**，或传空/省略。
- **会员域**接口的 **`params` 中不需要、也不要传 `datasourceId`**（服务端固定 CRM / 智慧购 ZHG 等，由实现决定）。

## 会员身份前提

- 券账户类接口（**2.x**）及多数流水接口均以 **`vipId`（会员编号）** 为主键。
- 若用户仅提供手机号、会员卡号等，**先**通过 `member-profile` Skill 解析出 `vipId`，再调用本 Skill。

## 1 数据与字段说明

### 1.1 券账户（`MemberCouponAccountEntry`；来源：账户券 / 电子纸券 / 智慧购 / 停车券等）

| 字段 | 类型 | 含义 | 可空 | 示例 |
|------|------|------|------|------|
| `couponSourceName` | `string` | 券来源说明 | 否 | `"账户券"` |
| `couponCode` | `string` | 券号/实例标识 | 是 | `""` 或券码 |
| `couponTypeId` | `string` | 券类型 id | 是 | — |
| `couponTypeName` | `string` | 券类型名称 | 是 | — |
| `couponBeginDate` | `string` | 有效开始 | 是 | — |
| `couponEndDate` | `string` | 有效结束 / 结束日期 | 是 | — |
| `balance` | `number` | 面额/余额（单位：元） | 否 | `100` |
| `pendingAmount` | `number` | 在途/冻结等 | 否 | `0` |
| `status` | `string` | 业务状态 | 是 | `"有效"` |
| `belongingStoreId` | `string` | 归属门店 id（部分来源有） | 是 | — |
| `belongingStoreName` | `string` | 归属门店名 | 是 | — |

**合并可用券**接口仅保留 `status` 为 **`有效`** 或历史 **`待使用`**，且 **`balance > 0`** 的条目（见 **2.5**）。

### 1.2 券使用/处理流水（`MemberCouponLedgerEntry`；与 1.1 为不同事实，侧重点是「已发生的使用/处理」）

| 字段 | 类型 | 含义 | 可空 | 示例 |
|------|------|------|------|------|
| `couponSourceName` | `string` | 券来源 | 否 | `"账户券"` |
| `couponCode` | `string` | 券号/实例 | 是 | — |
| `couponTypeId` | `string` | 券类型 id | 是 | — |
| `couponTypeName` | `string` | 券类型名称 | 是 | — |
| `dealTime` | `string` | 处理/发生时间 | 否 | — |
| `dealTypeName` | `string` | 处理类型说明 | 是 | — |
| `dealStoreId` | `string` | 发生门店 id | 是 | — |
| `dealStoreName` | `string` | 发生门店名 | 是 | — |
| `couponBeginDate` | `string` | 券上有效起 | 是 | — |
| `couponEndDate` | `string` | 券上有效止 | 是 | — |
| `dealAmount` | `number` | 本次发生额 | 否 | `50` |

## 2 能力清单 — 券账户（工具 `callApi`）

在 MCP 服务 **`mcp-api-suite`** 上调用 **`callApi`**，请求体为 JSON，至少包含：

| 字段 | 含义 |
|------|------|
| `apiName` | 各小节中的「接口名」 |
| `params` | 各小节列出的参数（**不含** `datasourceId`） |

**日期类**可选参数：均为 **ISO 日期字符串**（如 `"2025-01-01"`）；省略时由服务端在 SQL 中走 **`nvl(?, …)`** 默认下界。若传入，须为合法日期字符串。

### 2.1 账户券（CRM）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberAccountCouponsByVipId` |
| `params` | `vipId`（会员编号，必填） |
| `params` 可选 | `beginDate`：作为查询时间下界，见上文 |
| 返回 | `{ "items": [ ... ] }`，元素字段见 **1.1** |

### 2.2 电子纸券（CRM）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberElectronicCouponsByVipId` |
| `params` | `vipId`；可选 `beginDate`（同上） |
| 返回 | `{ "items": [ ... ] }`，字段见 **1.1** |

### 2.3 智慧购券（ZHG 数据源 / MySQL）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberSmartMallCouponsByVipId` |
| `params` | `vipId`；可选 `beginDate` |
| 返回 | `{ "items": [ ... ] }`，字段见 **1.1** |

### 2.4 停车券（CRM；条件多为 `user_id` 等，与库表一致）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberParkingCouponsByVipId` |
| `params` | `vipId`；可选 `beginDate` |
| 返回 | `{ "items": [ ... ] }`，字段见 **1.1** |

### 2.5 合并可用券（四类账户查询合并后筛「可用」）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberCanUseCouponsByVipId` |
| `params` | `vipId`；可选 `beginDate`（传入则四类查询共用同一时间下界） |
| 返回 | `{ "items": [ ... ] }`，为 **1.1** 中经服务端过滤后的子集（`有效` / `待使用` 且 `balance > 0`） |

示例：

```json
{
  "apiName": "listMemberCanUseCouponsByVipId",
  "params": { "vipId": "10001" }
}
```

## 3 能力清单 — 券使用记录/流水（工具 `callApi`）

| 字段 | 含义 |
|------|------|
| `apiName` | 各小节中的「接口名」 |
| `params` | 各小节列出的参数（**不含** `datasourceId`） |

### 3.1 账户券使用记录（Oracle）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberAccountCouponLedger` |
| `params` 均可选 | **`couponSourceName`**：须与 SQL 字面值一致，**默认 `账户券`**，对应条件 `? = '账户券'`；`dealDate`：处理时间 `a.clsj` 的下界；`couponTypeId`；`couponEndDate`；`vipId`（**hyid**） |
| 返回 | `{ "items": [ ... ] }`，元素字段见 **1.2**（最多 1000 行，以服务端实现为准） |

```json
{
  "apiName": "listMemberAccountCouponLedger",
  "params": {
    "couponSourceName": "账户券",
    "dealDate": "2025-01-01",
    "vipId": "10001"
  }
}
```

### 3.2 电子纸券使用记录（Oracle）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberElectronicCouponLedger` |
| `params` 必填 | **`vipId`**（**hyid**） |
| `params` 可选 | **`couponSourceName`**，**默认 `电子纸券`**（`? = '电子纸券'`）；`dealDate`（`e.clsj` 下界，省略走 SQL 默认） |
| 返回 | `{ "items": [ ... ] }`，见 **1.2** |

### 3.3 停车券使用记录（有使用时间的记录；Oracle）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberParkingCouponLedger` |
| `params` 均可选 | **`couponSourceName`**，**默认 `停车券`**（`? = '停车券'`）；`vipId`：绑定库中 **`user_id`**；`couponCode`：与权益 `equity_no` 等匹配 |
| 返回 | `{ "items": [ ... ] }`，见 **1.2** |

### 3.4 智慧购券使用记录（MySQL / ZHG）

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberSmartMallCouponLedger` |
| `params` 均可选 | **`couponSourceName`**，**默认 `智慧购券`**（`? = '智慧购券'`）；`vipId`：`user_wechat.hyid`；`couponCode`：`cu.id`（券实例 id） |
| 返回 | `{ "items": [ ... ] }`，见 **1.2**（一般为已使用 `status=1` 类数据） |

## 4 术语

- **会员编号**：在多数接口的 `params` 中为 **`vipId`**；在部分流水/停车场景中服务端会映射为 **`hyid`** 或 **`user_id`**，以各接口说明为准。
- **数据源**：不在 `params` 中传递；券账户/流水由服务端选择 CRM 或 ZHG 等。
- **`dealDate`**：仅**账户券使用记录**、**电子纸券使用记录** 中作为**流水时间下界**的可选键；**不要**与积分流水的 `beginDate`/`endDate` 混用，含义不同表不同。
- **`couponSourceName`**：券流水四类接口均有；与服务端 SQL 中 `? = '账户券' | '电子纸券' | '停车券' | '智慧购券'` 一致，传错则结果为空。省略时使用对应默认值。
