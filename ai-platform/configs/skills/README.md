# configs/skills/ — 全局 Skills 注册中心

## 双层标准

| 层级 | 标准 | 用途 |
|------|------|------|
| **上层** | **Agent Skills Spec**（Anthropic 牵头开放标准） | 技能包：场景 + 执行流程 + 约束 + 模板 + 脚本 + 参考资料 |
| **下层** | **MCP Tool**（JSON Schema 2020-12 inputSchema） | 实际 API 调用参数与工具绑定 |

## Agent Skills Spec 目录结构

```
configs/skills/
├── packages/
│   ├── _shared/                       # 跨业务域共享参考资料（非 Skill）
│   ├── crm/                           # 业务分类层
│   │   ├── member-profile/            # 会员档案域（含多种查询方式）
│   │   │   ├── SKILL.md
│   │   │   └── references/
│   ├── hr/                            # 其他业务域同理
│   └── finance/
├── registry.yaml
└── README.md
```

## SKILL.md 格式

```markdown
---
# Agent Skills Spec 必填（启动时加载，用于任务匹配）
name: member-profile-by-vip-id
description: 通过会员编号查询 CRM 会员档案...

# 平台扩展（工具注册，仍在 Front Matter，不读正文）
skill_id: member.profile
handler: mcp:mcp-api-suite:callApi
inputSchema:
  $schema: https://json-schema.org/draft/2020-12/schema
  type: object
  ...
---

# 执行流程（懒加载：确认使用该 Skill 后才注入上下文）

1. 确认 vipId
2. 调用 callApi ...
```

## 渐进式懒加载（Progressive Disclosure）

| 阶段 | 时机 | 加载内容 |
|------|------|----------|
| **一** | Agent / 平台启动 | 仅 SKILL.md **Front Matter**（name、description、inputSchema、handler） |
| **二** | LLM 确认调用该 Skill | 完整 Markdown 正文 + references/scripts/assets 索引 |

实现：`src/skills/spec_parser.py`、`SkillRegistry.load_full()`、`SkillToolAdapter._ensure_skill_body_loaded()`。

## Agent 启用 Skill

在 `configs/agents/{agent}/skills/enabled-skills.yaml` 中按 `skill_id` 启用：

```yaml
skills:
  enabled:
    - skill_id: member.profile
      enabled: true
```

## 向量索引

元数据（name + description + tags）在注册时生成 embedding，存入 Qdrant `skills_index`。
