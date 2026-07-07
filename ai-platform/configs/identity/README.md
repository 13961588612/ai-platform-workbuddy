# configs/identity/ — 全局身份配置

## 目录用途

本目录存储全局身份与权限配置，包括角色定义、部门映射等。这些配置与各 Agent 目录下的 `identity/` 子目录配合使用，实现细粒度的访问控制。

## 目录结构

```
configs/identity/
├── role-definitions.yaml      # 角色定义（角色名/权限模板/继承关系）
└── dept-mappings.yaml         # 部门映射（企业微信部门 ID → 本地部门标识）
```

## role-definitions.yaml 结构

```yaml
# 全局角色定义
version: "1.0.0"

roles:
  - id: "admin"
    name: "系统管理员"
    description: "拥有全部权限"
    permissions: ["*"]
    inherits: []

  - id: "hr_manager"
    name: "HR 经理"
    description: "人事部门管理员"
    permissions:
      - "hr:*"
      - "skill:leave:*"
      - "skill:salary:read"
    inherits: ["hr_staff"]

  - id: "hr_staff"
    name: "HR 专员"
    description: "人事部门专员"
    permissions:
      - "hr:leave:read"
      - "hr:attendance:read"
    inherits: ["employee"]

  - id: "finance_manager"
    name: "财务经理"
    description: "财务部门管理员"
    permissions:
      - "finance:*"
      - "skill:budget:*"
    inherits: ["finance_staff"]

  - id: "employee"
    name: "普通员工"
    description: "基础权限"
    permissions:
      - "skill:leave:read"
      - "skill:attendance:read:self"
    inherits: []
```

## dept-mappings.yaml 结构

```yaml
# 企业微信部门映射
version: "1.0.0"

# 企业微信部门 ID → 本地部门标识映射
mappings:
  - wecom_dept_id: 10
    local_dept_code: "HR"
    local_dept_name: "人力资源部"
    parent_dept_code: "ROOT"

  - wecom_dept_id: 20
    local_dept_code: "FINANCE"
    local_dept_name: "财务部"
    parent_dept_code: "ROOT"

  - wecom_dept_id: 30
    local_dept_code: "RETAIL"
    local_dept_name: "超市管理部"
    parent_dept_code: "ROOT"

  - wecom_dept_id: 40
    local_dept_code: "CRM"
    local_dept_name: "客户关系管理部"
    parent_dept_code: "ROOT"
```

## 权限模型

采用 **RBAC + Skill 覆盖** 混合权限模型：

1. **角色权限（RBAC）**：通过 `role-definitions.yaml` 定义角色与权限模板
2. **Skill 权限覆盖**：每个 Agent 的 `identity/skill-permissions.yaml` 可覆盖全局角色权限
3. **部门限制**：部分 Skill 限制仅特定部门可用
4. **敏感操作审批**：`identity/sensitive-ops.yaml` 配置需要 HITL 审批的操作

## 企业微信组织架构同步

企业微信组织架构通过定时任务同步到本地 PostgreSQL，部门映射关系在此配置文件中维护。同步频率：每日凌晨 2:00 全量同步。
