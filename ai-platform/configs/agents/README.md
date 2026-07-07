# configs/agents/ — Agent 配置目录

## 目录用途

本目录是所有 Agent 的配置根目录。**每个 Agent 对应一个子目录**，目录名即为 Agent ID（如 `crm-assistant`）。运营人员通过编辑配置目录中的 YAML/MD 文件即可创建和管理 Agent，配置变更后通过 ConfigWatcher 热更新机制自动生效，无需重启服务。

## 目录结构

```
configs/agents/
├── crm-assistant/             # CRM 智能助手 Agent
│   ├── agent.yaml             # 主配置（模型/提示词引用/路由/MCP引用/记忆引用）
│   ├── metadata.yaml          # 元数据（名称/描述/版本/标签，供 AgentRouter 语义检索）
│   ├── skills/                # Skills 配置
│   │   ├── enabled-skills.yaml
│   │   ├── skill-overrides/   # 特定 Skill 参数覆盖
│   │   └── custom-skills/     # Agent 专属自定义 Skill
│   ├── runtime/               # 运行时配置
│   │   ├── runtime.yaml       # 运行时类型与参数（openharness/custom/langgraph）
│   │   ├── prompts/           # 系统提示词
│   │   └── middleware/        # 中间件配置
│   ├── identity/              # 身份与权限
│   │   ├── access-control.yaml
│   │   ├── skill-permissions.yaml
│   │   └── sensitive-ops.yaml
│   ├── system/                # 系统级配置
│   │   ├── model.yaml         # LLM 模型配置（主力/备选/策略）
│   │   ├── mcp-servers.yaml   # MCP Server 连接配置
│   │   ├── push.yaml          # 推送配置
│   │   └── llm-gateway.yaml   # LLM 网关路由配置
│   └── memory/                # 记忆配置（v1.4 新增）
│       ├── agent-memory.yaml  # 静态长期记忆
│       ├── personality.md     # 人格记忆
│       └── facts/             # 事实知识库
│           └── crm-policies.yaml
├── finance-assistant/         # 财务助手 Agent
├── retail-assistant/          # 超市管理助手 Agent
└── default-agent/             # 默认兜底 Agent
```

## agent.yaml 核心字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent.name` | string | Agent ID（= 目录名） |
| `agent.display_name` | string | 显示名称 |
| `agent.description` | string | 简短描述 |
| `agent.version` | string | 配置版本 |
| `agent.tags` | string[] | 标签（供路由匹配） |
| `agent.includes` | object | 子配置文件引用路径 |
| `agent.routing.keywords` | string[] | 关键词匹配路由 |
| `agent.routing.enabled` | bool | 是否参与自动路由 |
| `agent.routing.priority` | int | 路由优先级 |
| `agent.memory` | object | 记忆配置（v1.4） |

## 配置模式

- **FILE_SYSTEM 模式**（开发/调试）：直接编辑 YAML 文件，watchdog 监听变更自动热更新
- **DATABASE 模式**（生产）：配置存储在 PostgreSQL，通过管理后台编辑，支持版本回滚

## 热更新机制

ConfigWatcher 监听文件变更后：
1. 解析变更的 YAML 文件
2. 校验配置有效性（Skill 引用、MCP 连通性、权限合规）
3. 通知对应的 Agent 实例
4. 下一会话生效（不影响当前活跃会话）
