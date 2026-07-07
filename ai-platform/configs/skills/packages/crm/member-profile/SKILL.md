---
name: member.profile
skill_id: member.profile
description: CRM 会员档案与生日变更记录查询。当用户需要查询会员信息、通过手机号/会员卡号/VIP编号/车牌号检索会员档案、或查询会员生日变更历史记录时触发此 Skill。
version: "1.0.0"
category: crm
tags:
  - 会员
  - 会员档案
  - vipId
  - 手机号
  - 车牌号
  - 生日变更
  - CRM
  - member.profile
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
      description: CRM 会员档案域接口名
      enum:
        - getMemberProfileByVipId
        - getMemberProfileByMemberCardNo
        - getMemberProfileByMobile
        - getMemberProfileByPlateNo
        - listMemberBirthdayChangeLogByVipId
    params:
      type: object
      additionalProperties: false
      description: 会员域参数，勿传 datasourceId 或 serviceName
      properties:
        vipId:
          type: string
          description: 会员编号
        memberCardNo:
          type: string
          description: 会员卡号
        mobile:
          type: string
          description: 手机号（11 位）
          pattern: "^\\d{11}$"
        plateNo:
          type: string
          description: 车牌号
  required:
    - apiName
    - params
---

# 会员档案（member.profile）

本文档供 **WorkBuddy / QwenPaw** 生成 Skill 使用：描述会员档案与生日变更相关字段，以及如何通过 MCP 工具 **`callApi`** 查询数据。

## MCP 与调用前提

- WorkBuddy / QwenPaw 中已配置 MCP 服务，**名称为 `mcp-api-suite`**（与下文的工具调用对应）。
- 所有接口均通过该服务上的工具 **`callApi`** 调用：传入 **`apiName`**（字符串）与 **`params`**（对象）。
- 进程内查询时不要传 **`serviceName`**，或传空/省略。
- **会员域**接口的 **`params` 中不需要、也不要传 `datasourceId`**。

## 身份字段默认约定

- 当顾客询问**会员相关信息**，只提供一串 **11 位数字**且**未说明**是会员编号（`vipId`）、会员卡号（`memberCardNo`）还是手机号（`mobile`）时，**默认按手机号码**处理：使用接口 **`getMemberProfileByMobile`**，`params` 中传 **`mobile`** 为该 11 位字符串。
- 若用户随后明确实为其它字段，再改用 **2.1 / 2.2** 对应接口。

## 1 数据与字段说明

### 1.1 会员档案

| 字段 | 类型 | 含义 | 可空 | 示例 |
|------|------|------|------|------|
| `vipId` | `string` | 会员编号 | 否 | `"10001"` |
| `memberCardNo` | `string` | 会员卡号 | 是 | `"88000001"` |
| `userName` | `string` | 会员姓名 | 是 | `"张三"` |
| `sex` | `string` | 性别 | 是 | `"男"` |
| `birthday` | `date` | 生日 | 是 | `"1990-01-01"` |
| `cardTypeName` | `string` | 会员等级（即卡类型，如金卡/银卡） | 是 | `"金卡"` |
| `mobile` | `string` | 手机号 | 是 | `"13800000000"` |
| `storeName` | `string` | 归属门店 | 是 | `"南京路店"` |
| `registeTime` | `string` | 注册时间 | 是 | `"2024-05-12 09:00:00"` |
| `plateNoList` | `string[]` | 会员绑定的车牌号列表（`hdwx.plateno`，`NVL(is_del,0)=0`）；无绑定时为 `[]` | 否 | `["沪A12345", "沪B99999"]` |

### 1.2 生日变更 / 档案变更记录

| 字段 | 类型 | 含义 | 可空 | 示例 |
|------|------|------|------|------|
| `vipId` | `string` | 会员编号 | 否 | `"10001"` |
| `birthday` | `string` | 变更后生日 | 是 | `"1990-01-02"` |
| `change_day` | `string` | 变更日期 | 否 | `"2026-03-28"` |

## 2 能力清单（工具 `callApi`）

在 MCP 服务 **`mcp-api-suite`** 上调用 **`callApi`**，请求体为 JSON，至少包含：

| 字段 | 含义 |
|------|------|
| `apiName` | 各小节中的「接口名」 |
| `params` | 各小节列出的参数（**不含** `datasourceId`） |

示例（按会员编号查档案）：

```json
{
  "apiName": "getMemberProfileByVipId",
  "params": {
    "vipId": "10001"
  }
}
```

### 2.1 根据会员编号查询会员档案

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `getMemberProfileByVipId` |
| `params` | `vipId`（会员编号） |
| 返回 | 单条档案对象，字段见 **1.1**；未找到时 `{ "found": false }` |

### 2.2 根据会员卡号查询会员档案

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `getMemberProfileByMemberCardNo` |
| `params` | `memberCardNo`（会员卡号） |
| 返回 | 同上，字段见 **1.1** |

### 2.3 根据手机号码查询会员档案

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `getMemberProfileByMobile` |
| `params` | `mobile`（手机号） |
| 返回 | 同上，字段见 **1.1** |

### 2.4 根据车牌号查询会员档案

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `getMemberProfileByPlateNo` |
| `params` | `plateNo`（车牌号，与 `hdwx.plateno.plate_no` 匹配） |
| 返回 | 同上，字段见 **1.1**（含 `plateNoList`）；未找到时 `{ "found": false }` |
| 备注 | 条件为 `EXISTS (hdwx.plateno p WHERE a.hyid = p.user_id AND p.plate_no = ?)`；若多条会员命中，由库返回顺序决定首条 |

### 2.5 根据会员编号查询会员生日变更记录

| 项目 | 说明 |
|------|------|
| 接口名 `apiName` | `listMemberBirthdayChangeLogByVipId` |
| `params` | `vipId`（会员编号） |
| 返回 | `{ "items": [ ... ] }`，元素字段见 **1.2** |

## 3 术语

- **会员编号**：`params` 与返回 JSON 中的 `vipId`。
- **会员等级**：与**卡类型**同义，对应返回字段 `cardTypeName`；用户问「等级」「卡类型」均指此字段。
- **会员数据源**：由服务端固定为 **`crm`**，调用方**勿**在 `params` 中传 `datasourceId`。
