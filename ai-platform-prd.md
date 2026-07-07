# 企业内部 AI 平台 — 产品需求文档（PRD）

> **文档版本**: v1.4（新增 Agent 记忆机制：静态记忆 memory/ 目录 + 动态记忆 PostgreSQL + Qdrant 向量检索）  
> **创建日期**: 2026-07-04  
> **编写人**: 许清楚（Xu）— 产品经理  
> **文档状态**: 待评审
>
> **v1.4 变更记录**：
> - **Agent 记忆机制（新增）**：每个 Agent 配置目录新增 `memory/` 子目录，支持两层记忆模型——**静态记忆**（memory/ 目录下 YAML/MD 文件，包含 agent-memory.yaml 长期记忆 + facts/ 事实知识库 + personality.md 人格记忆）和**动态记忆**（PostgreSQL `agent_memory` 表存储交互中产生的记忆条目 + Qdrant `agent_memory_index` collection 向量索引支持语义检索）。运行时 MemoryManager 分层注入：系统提示词 → 静态记忆 → 动态记忆 Top-K → 对话历史。Agent 可自主写入动态记忆（用户偏好/重要决策/任务摘要），支持按会话/用户/Agent 维度检索与遗忘策略
>
> **v1.3 变更记录**：
> - **企业微信智能机器人渠道（新增）**：渠道从双渠道扩展为**三渠道**（企业微信 H5 + **企业微信智能机器人** + 独立 H5）。企业微信后台智能机器人通过 WebSocket 长连接接入，仅支持 6 种 template_card（text_notice、news_notice、button_interaction、vote_interaction、multiple_interaction、template_notice），不支持流式输出/自定义 React 组件/Generative UI，需能力降级映射（AgentEvent → Bot 渠道格式）
> - **Agent 后台自动路由（新增）**：前端**不提供**用户选择运行时/Agent 的功能，由系统后台 **AgentRouter** 自动路由到合适的 Agent。路由策略：会话亲和性 → 关键词匹配 → 语义检索 → 默认 Agent 兜底。用户无需感知"当前在跟哪个 Agent 对话"
> - **配置目录结构设计（新增）**：明确"配置即实例"设计理念，每个 Agent 一套配置目录（configs/agents/{agent_name}/ 下含 agent.yaml + skills/ + runtime/ + identity/ + system/），支持热更新机制，同时支持文件系统和数据库两种配置存储模式
> - **LLM 厂家服务+网关（确认）**：LLM（deepseek-v4-flash + qwen3.6-plus）通过**购买厂家 API 服务**使用，**不自建 GPU 推理集群**。平台需 **LLM 网关层**管理多厂家 API Key，支持 Token 计费追踪、按部门/用户配额等成本控制
> - **内网部署+出站代理（确认）**：平台部署在公司内网，LLM API 需通过**内网出站代理**访问厂家服务端点。其他组件（Qdrant/Redis/PostgreSQL/Embedding 模型 bge-small-zh-v1.5）全部内网部署
>
> **v1.2 变更记录**：
> - Skills 分类：新增 **CRM 系统**（~80 Skills）和 **储值卡系统**（~70 Skills）两个一级分类，总数约 670+ Skills
> - LLM 选型：确定为 **deepseek-v4-flash**（主力）+ **qwen3.6-plus**（备选），双模型策略
> - 业务系统适配层：明确各业务系统 API 不统一，需开发 **统一业务系统适配层（Business System Adapter）**，将各系统 API 封装为标准 MCP Server 接口
> - ~~微信机器人：**从项目范围删除**，渠道从三渠道缩减为双渠道（企业微信 H5 + 独立 H5）~~ — ⚠️ v1.3 重新新增**企业微信智能机器人**渠道（与原微信机器人不同，为企业微信后台智能机器人），渠道恢复为三渠道
> - SSO/OAuth：确认 **企业微信 OAuth2 直连 + 本地 JWT**（不引入独立 IdP），独立 H5 用户名密码登录，业务系统凭证托管（P1-11）
>
> **v1.1 变更记录**：
> - Q1 企业微信：确认为 **H5 嵌入企业微信工作台**（非原生 API 应用），动态 UI 直接通过 CopilotKit 在 H5 内渲染
> - Q2 微信端：确认为 **机器人长连接对话**（非服务号/订阅号），通过 WebSocket/长轮询维持双向通信
> - Q4 LLM：确认使用 **国产供应商**（通义千问/文心/智谱/DeepSeek 等），需模型适配层
> - Q5 Skills 来源：确认来自 **财务、超市管理、百货管理、人事系统、物业系统** 等多业务系统
> - Q8 部署环境：确认 **内网部署**，全部组件内网可访问，不依赖外部 SaaS
> - Q9 并发规模：确认 **100-200 用户并发**，容量规划相应调整

---

## 1. 产品概述

### 1.1 产品定位

企业内部 AI 平台是一个**统一的 AI 能力接入与调度中枢**，将大模型 Agent 能力以**三渠道**（企业微信 H5、企业微信智能机器人、独立 H5）方式触达内部员工，支持多套 Agent 配置并行运行、基于身份的 Skills 权限管控，以及 670+ 大规模 Skills 场景下的高效调度。平台 **全内网部署**，LLM（deepseek-v4-flash + qwen3.6-plus）通过**购买厂家 API 服务**使用（不自建 GPU 推理集群），经平台 **LLM 网关层**统一管理多厂家 API Key 与成本控制，LLM API 请求通过**内网出站代理**访问厂家服务端点。其他组件（Qdrant/Redis/PostgreSQL/Embedding 模型 bge-small-zh-v1.5）全部内网部署。Skills 来源于财务、超市管理、百货管理、人事系统、物业系统、CRM 系统、储值卡系统等多个业务系统。各业务系统现有 API 不统一，需开发**统一业务系统适配层（Business System Adapter）**，将各系统 API 封装为标准 MCP Server 接口。前端**不提供**用户选择运行时/Agent 的功能，由系统后台 **AgentRouter** 自动路由到合适的 Agent。

### 1.2 产品目标

| 编号 | 目标 | 衡量标准 |
|------|------|----------|
| G1 | **三渠道触达**：员工可通过企业微信 H5、企业微信智能机器人、独立 H5 三种渠道与 AI Agent 交互 | 三渠道均可正常收发消息，H5 渠道支持动态 UI，Bot 渠道支持 6 种 template_card 交互，消息延迟 < 2s |
| G2 | **灵活的多 Agent 配置**：每套配置对应一个独立 Agent 实例，支持 Skills/MCP 灵活编排 | 配置创建到实例就绪 < 5min，支持热更新 |
| G3 | **大规模 Skills 调度**：单实例支持 670+ Skills 高效调度，按身份动态授权 | 670 Skills 场景下 Skill 召回准确率 > 90%，首 Token 延迟 < 3s |
| G4 | **智能 Agent 路由**：AgentRouter 后台自动路由用户请求到合适的 Agent，用户无需手动选择 | 路由准确率 > 85%，路由延迟 < 500ms，支持会话亲和性/关键词/语义检索/兜底策略 |

### 1.3 核心价值主张

- **渠道原生体验**：企业微信 H5 通过 CopilotKit 动态 UI 提供富交互；企业微信智能机器人提供轻量级模板卡片交互（6 种 template_card）；独立 H5 提供完整 Generative UI 体验
- **配置即实例**：运营人员通过配置目录（非编码）即可创建新 Agent，定义其 Skills、MCP、模型参数、记忆，每个 Agent 一套独立配置目录，支持文件系统与数据库双模式存储
- **记忆驱动个性化**：Agent 具备两层记忆——静态记忆（角色背景/领域知识/行为准则）由运营配置，动态记忆（用户偏好/决策摘要）由 Agent 自动积累，让 Agent 越用越懂用户
- **智能路由无感**：AgentRouter 后台自动路由用户请求到合适的 Agent，用户无需感知"当前在跟哪个 Agent 对话"
- **运行时可替换**：后端运行时抽象层以 OpenHarness（港大HKUDS开源 Python Agent 框架）为初始实现，支持切换至自研 Agent 或其他框架
- **身份驱动的能力管控**：不同角色看到的 Skills 不同，实现细粒度的能力隔离
- **LLM 厂家服务+成本可控**：通过购买厂家 API 服务使用 LLM，LLM 网关层统一管理 API Key 与 Token 计费，按部门/用户配额控制成本

---

## 2. 目标用户与场景

### 2.1 用户角色画像

| 角色 | 描述 | 核心诉求 | 使用渠道 |
|------|------|----------|----------|
| **普通员工** | 各业务部门一线人员 | 快速获取信息、完成日常任务（如查数据、提审批、查知识库） | 企业微信 H5、企业微信 Bot、独立 H5 |
| **管理者** | 部门负责人 / 项目经理 | 查看团队 AI 使用情况、配置部门级 Agent、审批敏感操作 | 企业微信 H5、企业微信 Bot、H5 管理后台 |
| **平台运营** | AI 平台运维/配置人员 | 创建/管理 Agent 配置、管理 Skills 注册与发现、监控运行状态 | H5 管理后台 |
| **开发者** | 内部研发人员 | 开发新 Skill、接入 MCP Server、调试 Agent 行为 | H5 管理后台 + API |
| **系统管理员** | IT 安全/合规人员 | 管理用户身份与权限、审计日志、运行时切换、LLM 成本管控 | H5 管理后台 |

### 2.2 核心使用场景

| 场景 | 角色 | 描述 |
|------|------|------|
| S1 日常问答 | 普通员工 | 在企业微信工作台打开 AI 助手 H5 应用，提问获取流式回答 |
| S2 动态卡片交互 | 普通员工 | AI 在 H5 内动态渲染审批卡片/数据看板等 React 组件，员工直接交互操作 |
| S3 动态表单 | 普通员工 | Agent 根据对话上下文动态生成表单 UI（如报销填报），员工在 H5 中填写提交 |
| S4 智能路由（自动） | 普通员工 | 用户无需选择 Agent，系统 AgentRouter 根据会话亲和性/关键词/语义检索自动路由到合适的 Agent（如 HR助手、财务助手、超市管理助手） |
| S5 Bot 对话 | 普通员工 | 在企业微信群/单聊中直接 @ 智能机器人对话，机器人通过 6 种 template_card 回复（如文本通知、图文通知、按钮交互） |
| S6 Bot 主动推送 | 管理者/系统 | 智能机器人主动向用户/群推送模板卡片消息（如任务提醒、数据摘要、审批通知） |
| S7 Agent 配置 | 平台运营 | 在管理后台通过配置目录创建新 Agent 配置，选择模型、Skills、MCP、系统提示词 |
| S8 Skill 开发注册 | 开发者 | 开发新 Skill 并注册到平台，设置可见范围 |
| S9 权限管理 | 系统管理员 | 为不同部门/角色配置可使用的 Skills 白名单 |
| S10 运行时切换 | 系统管理员 | 将某 Agent 的运行时从 OpenHarness 切换至自研框架，零停机 |
| S11 大规模调度 | 所有用户 | Agent 拥有 670+ Skills（来自财务/超市/百货/人事/物业/CRM/储值卡等系统），根据用户问题动态检索并仅加载相关 Skills |
| S12 LLM 成本管控 | 系统管理员 | 通过 LLM 网关层查看 Token 消耗、按部门/用户设置配额与告警 |

---

## 3. 用户故事

### 3.1 前端交互

| 编号 | 用户故事 |
|------|----------|
| US-01 | 作为**普通员工**，我希望能在**企业微信**中直接与 AI 助手对话，这样我无需切换应用就能获取帮助 |
| US-02 | 作为**普通员工**，我希望 AI 助手能推送**卡片消息**（如审批提醒、数据看板），这样我能快速完成交互操作 |
| US-03 | 作为**普通员工**，我希望在 **H5 页面**中看到**动态生成的界面**（如表格、图表、表单），而不是纯文本回复 |
| US-04 | 作为**普通员工**，我希望系统**自动路由**我的问题到合适的 Agent（如 HR 问题自动路由到 HR 助手），这样我**无需手动选择**当前使用哪个 Agent |
| US-05 | 作为**普通员工**，我希望 AI 回复能**流式输出**，这样我不需要等待完整回复就能开始阅读 |
| US-B01 | 作为**普通员工**，我希望能在企业微信中直接 **@智能机器人**对话，这样我不需要打开 H5 应用就能快速获取信息 |
| US-B02 | 作为**普通员工**，我希望智能机器人能回复**模板卡片**（如按钮选择、投票、图文通知），这样我能在卡片上直接完成交互操作 |
| US-B03 | 作为**普通员工**，我希望智能机器人能**主动推送**模板卡片消息给我（如审批待办、任务到期提醒），这样我能及时处理重要事项 |
| US-B04 | 作为**管理者**，我希望智能机器人能向**企业微信群**推送数据摘要卡片，这样团队成员能快速了解关键指标 |

### 3.2 后端管理与多 Agent

| 编号 | 用户故事 |
|------|----------|
| US-06 | 作为**平台运营**，我希望能通过**配置目录**创建新 Agent 实例（含模型、Skills、MCP、提示词），这样无需开发介入 |
| US-07 | 作为**平台运营**，我希望能**热更新** Agent 配置（如增减 Skills），这样不影响正在进行的对话 |
| US-08 | 作为**平台运营**，我希望能查看每个 Agent 实例的**运行状态**（活跃会话数、Token 消耗、错误率），这样我能及时发现问题 |
| US-R01 | 作为**系统管理员**，我希望 AgentRouter 能根据**会话亲和性**将同一用户的连续对话路由到同一 Agent，这样保持上下文连贯 |
| US-R02 | 作为**系统管理员**，我希望 AgentRouter 能通过**关键词匹配和语义检索**自动识别用户意图并路由到对应 Agent，这样用户无需手动选择 |
| US-R03 | 作为**系统管理员**，我希望 AgentRouter 在无法确定目标 Agent 时能**回退到默认 Agent**，这样保证用户请求始终得到响应 |
| US-R04 | 作为**平台运营**，我希望能查看 AgentRouter 的**路由日志和统计**（路由命中率、各 Agent 流量分布），这样我能优化路由策略 |
| US-C01 | 作为**平台运营**，我希望每个 Agent 配置都有**独立的配置目录**（agent.yaml + skills/ + runtime/ + identity/ + system/ + memory/），这样配置结构清晰可维护 |
| US-C02 | 作为**平台运营**，我希望能通过**文件系统或数据库**两种方式管理 Agent 配置，这样适应不同部署环境 |
| US-C03 | 作为**系统管理员**，我希望能通过 **LLM 网关**统一管理多个厂家的 API Key，这样无需在各 Agent 配置中分散管理 |
| US-C04 | 作为**系统管理员**，我希望能按**部门和用户设置 Token 配额**，这样控制 LLM 使用成本 |

### 3.3 权限控制

| 编号 | 用户故事 |
|------|----------|
| US-09 | 作为**系统管理员**，我希望能根据**用户身份**（部门/角色）自动确定其可调用的 Skills，这样实现能力隔离 |
| US-10 | 作为**普通员工**，我希望 AI 助手**仅展示我有权限使用的功能**，这样不会看到无权操作的入口 |
| US-11 | 作为**系统管理员**，我希望能对**敏感 Skills** 设置二次审批，这样高权限操作有人工把关 |

### 3.4 大规模 Skills 与运行时

| 编号 | 用户故事 |
|------|----------|
| US-12 | 作为**开发者**，我希望 Agent 在面对 670+ Skills 时能**自动检索**最相关的 Skills 加载到上下文，这样不会超出 Token 限制 |
| US-13 | 作为**系统管理员**，我希望能将 Agent 运行时从 OpenHarness **无缝切换**到自研框架，这样不被单一框架绑定 |
| US-14 | 作为**平台运营**，我希望能为不同 Agent 配置**不同的运行时**，这样可根据场景选择最优实现 |
| US-15 | 作为**开发者**，我希望能接入外部 **MCP Server** 作为 Skills 来源，这样能快速复用社区生态 |

### 3.5 主动推送

| 编号 | 用户故事 |
| US-16 | 作为**普通员工**，我希望 AI Agent 能**主动推送**消息给我（如任务到期提醒、异常告警），这样我不需要主动查询 |
| US-17 | 作为**管理者**，我希望 AI 能**定时推送**部门数据摘要卡片到企业微信群，这样团队能及时了解关键指标 |
| US-18 | 作为**普通员工**，我希望企业微信智能机器人能**主动推送 template_card** 给我（如审批待办按钮卡片、投票卡片），这样我能直接在卡片上完成操作 |

---

## 4. 需求池（P0 / P1 / P2）

### 4.1 P0 — Must Have（必须有）

| 编号 | 需求 | 描述 | 验收标准 |
|------|------|------|----------|
| P0-01 | **企业微信 H5 接入** | 企业微信工作台嵌入 H5 应用，通过 JS-SDK 获取用户身份，CopilotKit 动态 UI 直接在 H5 内渲染 | H5 加载 < 2s，JS-SDK 鉴权自动完成，动态 UI 正常渲染 |
| P0-02 | **企业微信智能机器人接入** | 在企业微信管理后台添加机器人应用，平台与机器人建立 WebSocket 长连接，用户在企业微信中直接与机器人对话 | WebSocket 长连接稳定，消息收发延迟 < 2s，支持 6 种 template_card |
| P0-03 | **H5 远程调用** | 提供 H5 Web 应用，通过 API/WebSocket 与后端 Agent 交互 | 支持 SSE/WebSocket 流式输出 |
| P0-04 | **动态 UI 交互** | 前端支持动态渲染 Agent 返回的 UI 组件（表格、图表、表单等） | 基于 CopilotKit Generative UI 实现 |
| P0-05 | **多 Agent 配置管理** | 支持创建/编辑/删除多套 Agent 配置，每套对应一个独立实例，配置以目录结构组织 | 配置项含：模型、系统提示词、Skills列表、MCP列表、运行时类型；支持配置目录结构 |
| P0-06 | **Agent 实例生命周期** | 实例的创建、启动、暂停、恢复、销毁全生命周期管理 | 支持优雅停机，进行中会话完成后再关闭 |
| P0-07 | **用户身份识别** | 从企业微信 JS-SDK/H5 请求中识别用户身份（UserID、部门、角色） | 身份识别准确率 100%，企业微信 OAuth 自动登录 |
| P0-08 | **Skills 权限控制** | 根据用户身份动态过滤可用 Skills，仅授权 Skills 进入 Agent 上下文 | 未授权 Skill 不可见、不可调用 |
| P0-09 | **Skills 注册与发现** | 支持 Skill 的注册、分类、检索、版本管理 | 支持 MCP Server 和自定义 Skill 两种注册方式 |
| P0-10 | **基础聊天交互** | 文本对话、流式输出、多轮上下文管理 | 支持 Markdown 渲染、代码高亮 |
| P0-11 | **Agent 智能路由** | AgentRouter 后台自动路由用户请求到合适的 Agent，路由策略：会话亲和性 → 关键词匹配 → 语义检索 → 默认 Agent 兜底。前端不提供 Agent/运行时选择功能 | 路由准确率 > 85%，路由延迟 < 500ms，用户无感知路由过程 |
| P0-12 | **Bot 渠道能力降级映射** | AgentEvent → Bot 渠道格式降级映射：text.delta → 文本消息，ui.render → template_card（按类型映射），approval.request → button_interaction 卡片 | 6 种 AgentEvent 类型均能正确降级为 Bot 支持的格式，降级无信息丢失 |

### 4.2 P1 — Should Have（应该有）

| 编号 | 需求 | 描述 | 验收标准 |
|------|------|------|----------|
| P1-01 | **主动推送机制** | Agent 可主动向用户/群发送消息或动态界面 | 支持企业微信应用消息通知、企业微信 Bot template_card 推送、H5 WebSocket 推送 |
| P1-02 | **H5 动态卡片交互** | H5 内动态渲染审批卡片、数据看板等交互组件，支持实时更新 | 基于 CopilotKit Generative UI，支持按钮/表单/图表等组件类型 |
| P1-03 | **运行时抽象层** | 定义统一的 Agent 运行时接口，OpenHarness 为默认实现 | 接口含：run()、stream()、tools()、状态管理；支持注册新运行时 |
| P1-04 | **运行时切换** | 支持将 Agent 运行时从 OpenHarness 切换至其他框架/自研 | 切换过程零停机，进行中会话平滑迁移 |
| P1-05 | **670+ Skills 动态调度** | 基于语义检索的 Skill 召回机制，仅加载相关 Skills 到上下文 | 670 Skills 召回 Top-K（K≤20），召回准确率 > 90% |
| P1-06 | **Skill 语义索引** | 为所有注册 Skill 建立语义向量索引，支持自然语言检索 | 索引构建 < 30s，检索延迟 < 200ms |
| P1-07 | **MCP Server 管理** | 支持接入外部 MCP Server（stdio/HTTP/SSE），自动发现其 Tools | 支持多 MCP Server 同时挂载 |
| P1-08 | **人机交互（HITL）** | 敏感操作前需人工确认，Agent 暂停等待审批结果 | 审批超时默认拒绝，H5 内弹窗审批 + 企业微信消息通知；Bot 渠道降级为 button_interaction 卡片审批 |
| P1-09 | **会话管理** | 多会话并发、会话历史持久化、会话恢复 | 支持会话列表、历史回看 |
| P1-10 | **管理后台** | H5 管理 Agent 配置、Skills 管理、用户权限、运行监控 | 响应式设计，支持 PC + Pad |
| P1-11 | **业务系统凭证托管** | 平台安全存储各业务系统（财务/超市/百货/人事/物业/CRM/储值卡，共 7 个）的登录凭证（AES-256 加密存储），Agent 调用 Skill 时适配层自动完成业务系统认证；管理后台提供凭证配置入口 | 凭证加密存储，明文不可见；适配层自动登录/Token 刷新；凭证可按系统/角色配置 |
| P1-12 | **LLM 网关与成本控制** | LLM 网关层统一管理多厂家 API Key（deepseek/qwen），支持 API Key 轮转/故障切换；Token 计费追踪（按会话/用户/部门维度）；按部门/用户设置 Token 配额与告警；LLM 请求通过内网出站代理访问厂家 API 端点 | API Key 统一管理，Token 用量可追踪到会话级，配额超限自动告警/限流 |
| P1-13 | **配置目录与热更新** | 每个 Agent 一套配置目录（configs/agents/{agent_name}/ 下含 agent.yaml + skills/ + runtime/ + identity/ + system/ + memory/）；支持文件系统和数据库两种配置存储模式；配置变更热更新，无需重启 Agent 实例 | 配置目录结构规范化，热更新生效 < 10s，文件/数据库双模式可切换 |
| P1-14 | **Agent 记忆机制** | 两层记忆模型：**静态记忆**（memory/ 目录下 agent-memory.yaml + personality.md + facts/）由运营人员维护，定义 Agent 的角色背景、人格、领域知识；**动态记忆**（PostgreSQL agent_memory 表 + Qdrant agent_memory_index 向量索引）由 Agent 在交互中自动写入，记录用户偏好、重要决策、任务摘要。运行时 MemoryManager 分层注入上下文：系统提示词 → 静态记忆 → 动态记忆 Top-K（语义检索） → 对话历史。支持按会话/用户/Agent 维度检索，支持遗忘策略（TTL/容量上限/重要性衰减） | 静态记忆通过配置文件定义，热更新生效；动态记忆写入延迟 < 500ms，语义检索延迟 < 200ms，Top-K 检索准确率 > 85% |

### 4.3 P2 — Nice to Have（可以有）

| 编号 | 需求 | 描述 |
|------|------|------|
| P2-01 | **多模型路由（基于厂家 API）** | 根据任务类型/成本/延迟动态选择 LLM 厂家与模型（deepseek-v4-flash / qwen3.6-plus 等），通过 LLM 网关层实现路由策略 |
| P2-02 | **Agent 编排** | 多 Agent 协作（Supervisor 模式），复杂任务拆分给子 Agent |
| P2-03 | **使用分析仪表盘** | Token 消耗、Skill 调用频次、用户活跃度等数据分析 |
| P2-04 | **Skill 市场** | 内部 Skill 共享市场，部门间复用 Skills |
| P2-05 | **A/B 测试** | 对比不同 Agent 配置/模型/Skills 组合的效果 |
| P2-06 | **语音交互** | 企业微信语音消息转文字 → Agent 处理 → 语音回复 |
| P2-07 | **多语言支持** | Agent 支持中英双语交互 |
| P2-08 | **沙箱执行** | 代码类 Skill 在隔离沙箱中执行，保障安全 |
| P2-09 | **成本控制仪表盘** | 按部门/用户/Agent 维度的 Token 成本可视化、预算趋势预测、异常消费告警 |
| P2-10 | **审计日志** | 全量操作审计，支持合规审查与追溯 |
| P2-11 | **Bot 渠道模板卡片高级交互** | 利用 multiple_interaction / vote_interaction 等高级模板卡片实现复杂表单、多步骤投票等场景 |

---

## 5. 前端交互设计要点

### 5.1 企业微信 H5 嵌入方案

企业微信通过**工作台 H5 应用**方式接入，CopilotKit 动态 UI 直接在 H5 内渲染，无需依赖企业微信原生卡片 API。

**接入方式**：
- 企业微信管理后台配置 H5 应用（自建应用 → 网页应用）
- H5 页面通过**企业微信 JS-SDK** 实现身份鉴权（`wx.qy.getContext` / OAuth2 授权登录）
- 用户在企业微信工作台点击应用图标即打开 H5 页面
- CopilotKit 在 H5 内完整运行，Generative UI 组件直接渲染为 React 组件

**企业微信 JS-SDK 能力利用**：

| JS-SDK 接口 | 用途 | 平台应用场景 |
|-------------|------|-------------|
| `wx.qy.getContext` | 获取入口上下文（工作台/聊天/通讯录） | 根据入口场景定制 Agent 行为 |
| `wx.qy.login` / OAuth2 | 获取用户身份 UserID | 免登录自动认证 |
| `wx.qy.sendChatMessage` | 向当前聊天发送消息 | 在聊天中分享 AI 结果 |
| `wx.qy.openDefaultBrowser` | 打开默认浏览器 | 需要全屏体验时跳转 |
| `wx.qy.shareToExternalContact` | 分享给外部联系人 | 知识/结果分享 |
| `wx.qy.setNavigationBarTitle` | 设置导航栏标题 | 动态页面标题 |

**设计要点**：
1. H5 应用作为主要交互入口，CopilotKit 完整运行
2. 企业微信 JS-SDK 负责身份获取和上下文传递，不依赖原生卡片消息
3. 主动推送通知通过**企业微信应用消息 API**（文本/图文卡片消息）引导用户打开 H5
4. HITL 审批在 H5 内通过 CopilotKit 弹窗完成，同时推送应用消息提醒

### 5.2 CopilotKit 动态 UI 方案分析

CopilotKit 是面向 Agent 原生应用的全栈前端 SDK，核心能力：

| 能力 | 说明 | 平台价值 |
|------|------|----------|
| **Generative UI** | Agent 可动态渲染真实 React 组件（表格、图表、表单等） | Agent 返回结构化 UI 而非纯文本 |
| **AG-UI 协议** | 统一连接标准，任意 AG-UI 兼容后端可接入 | 运行时可替换的天然支撑 |
| **预构建组件** | CopilotChat / CopilotSidebar / CopilotPopup | 快速搭建 H5 聊天界面 |
| **Headless UI** | 完全自定义 UI，仅使用 Agent 运行时 | 企业微信等非浏览器场景适配 |
| **Human-in-the-Loop** | 内置人工介入工作流 | 敏感操作审批的 UI 支撑 |
| **MCP 集成** | 前端直接接入 MCP Server | 前端工具调用能力 |
| **多框架支持** | React / Angular / Vue / React Native | 技术选型灵活 |
| **共享状态** | 前端与 Agent 之间双向状态同步 | 表单填写等交互场景 |

**选型结论**：**推荐 CopilotKit 作为 H5 端动态 UI 主框架**，理由：
1. Generative UI 完美匹配"动态界面交互"需求
2. AG-UI 协议为运行时可替换提供协议层支撑
3. 18+ Agent 框架集成（含 LangGraph、Mastra、PydanticAI 等），与 OpenHarness 可对接
4. Headless UI 模式可适配企业微信卡片场景的组件渲染逻辑

### 5.3 动态 UI 方案对比

| 维度 | CopilotKit | Vercel AI SDK | LangChain.js (前端) |
|------|-----------|---------------|---------------------|
| **定位** | Agent 原生前端全栈 SDK | 前端 AI UI 工具箱 | LLM 应用编排框架（前端能力弱） |
| **Generative UI** | ⭐⭐⭐⭐⭐ Agent 渲染真实 React 组件 | ⭐⭐⭐ 需手动实现 | ⭐ 无 |
| **流式输出** | ⭐⭐⭐⭐⭐ 内置 | ⭐⭐⭐⭐⭐ useChat 开箱即用 | ⭐⭐⭐ 需自己接 SSE |
| **Agent 后端集成** | ⭐⭐⭐⭐⭐ AG-UI 协议，18+ 框架 | ⭐⭐⭐ SDK 5+ 多步 Tool Calling | ⭐⭐⭐⭐⭐ LangGraph 强编排 |
| **MCP 支持** | ⭐⭐⭐⭐⭐ 前端直接接入 | ⭐⭐ 需自行实现 | ⭐⭐⭐ 后端支持 |
| **Human-in-the-Loop** | ⭐⭐⭐⭐⭐ 内置 | ⭐⭐ 需自行实现 | ⭐⭐⭐⭐ LangGraph 支持 |
| **多框架覆盖** | React/Angular/Vue/RN | React/Svelte/Vue/Solid | 无官方前端 Hook |
| **学习曲线** | 中等 | 低 | 高 |
| **GitHub Stars** | 32.7K+ | 22K+ | 14K+ |
| **适用场景** | Agent 驱动的动态 UI 应用 | 聊天界面 + 基础 Tool Calling | 复杂 Agent 编排（后端为主） |

**最终方案建议**：
- **企业微信 H5 端**：CopilotKit 完整运行在 H5 内 + 企业微信 JS-SDK（身份鉴权/上下文/消息通知）
- **企业微信 Bot 端**：WebSocket 长连接 + 6 种 template_card（轻量交互，不支持流式/Generative UI，需能力降级映射）
- **独立 H5 端**：CopilotKit（主框架）+ Vercel AI SDK（底层流式传输补充）
- **Agent 路由**：AgentRouter 后台自动路由（会话亲和性 → 关键词 → 语义检索 → 兜底），前端不提供 Agent 选择功能
- **后端 Agent 编排**：OpenHarness（港大HKUDS开源Python Agent框架，默认运行时）+ LangGraph（复杂编排场景可选）
- **LLM 服务**：通过**购买厂家 API 服务**使用 deepseek-v4-flash（主力）+ qwen3.6-plus（备选），经 **LLM 网关层**统一管理 API Key 与成本控制，通过**内网出站代理**访问厂家 API 端点

### 5.4 前端架构分层

```
┌──────────────────────────────────────────────────────────────────┐
│                          渠道适配层                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ 企业微信工作台      │  │ 企业微信智能机器人  │  │ 独立 H5 Web     │  │
│  │ H5 + JS-SDK      │  │ WebSocket 长连接   │  │ CopilotKit     │  │
│  │ CopilotKit 完整   │  │ 6种 template_card │  │ Components     │  │
│  └────────┬─────────┘  └────────┬─────────┘  └───────┬────────┘  │
├───────────┼──────────────────────┼─────────────────────┼──────────┤
│           └──────────────────────┼─────────────────────┘          │
│                     统一消息网关                                     │
│          (消息格式转换 / 协议适配 / Bot能力降级 / 会话管理)            │
├──────────────────────────────────────────────────────────────────┤
│                    AgentRouter（智能路由层）                          │
│       (会话亲和性 → 关键词匹配 → 语义检索 → 默认Agent兜底)             │
├──────────────────────────────────────────────────────────────────┤
│                     AG-UI 协议层                                     │
│         (CopilotKit Runtime / 事件流 / 状态同步)                     │
├──────────────────────────────────────────────────────────────────┤
│                    LLM 网关层                                        │
│    (多厂家 API Key 管理 / Token 计费追踪 / 配额控制 / 出站代理)        │
│    deepseek-v4-flash + qwen3.6-plus → 内网出站代理 → 厂家 API       │
├──────────────────────────────────────────────────────────────────┤
│                   Agent 后端服务                                     │
│   ┌──────────────────────────────────────────────────────────┐     │
│   │  运行时抽象层 (OpenHarness / 自研 / LangGraph)              │     │
│   │  Skills 调度引擎 / MCP 管理 / 身份鉴权                      │     │
│   │  LLM 双模型: deepseek-v4-flash + qwen3.6-plus              │     │
│   └──────────────────────────────────────────────────────────┘     │
│   ┌──────────────────────────────────────────────────────────┐     │
│   │  业务系统适配层 (Business System Adapter)                     │     │
│   │  财务/超市/百货/人事/物业/CRM/储值卡 → 标准 MCP接口            │     │
│   └──────────────────────────────────────────────────────────┘     │
│               【全内网部署，LLM 经出站代理访问厂家 API】                 │
└──────────────────────────────────────────────────────────────────┘
```

### 5.5 企业微信智能机器人渠道交互设计

企业微信智能机器人是与企业微信 H5 **完全不同**的轻量级渠道。用户在企业微信群聊或单聊中直接 @ 机器人即可对话，无需打开 H5 应用。

**接入方式**：
- 在企业微信管理后台添加**智能机器人应用**（非网页应用）
- 平台与机器人建立 **WebSocket 长连接**，维持双向通信
- 用户在企业微信中直接与机器人对话（群聊 @ 机器人 / 单聊）
- 机器人仅支持**企业微信 template_card** 消息格式，不支持流式输出、自定义 React 组件、Generative UI

**支持的 6 种 template_card 类型及使用场景**：

| template_card 类型 | 用途 | 平台应用场景 |
|-------------------|------|-------------|
| **text_notice** | 文本通知卡片 | Agent 回复的文本摘要、任务完成通知、知识问答结果 |
| **news_notice** | 图文通知卡片 | 带图片/链接的通知，如数据报表链接、知识库文章推荐 |
| **button_interaction** | 按钮交互卡片 | 审批确认/拒绝、操作选择（如"查看详情"/"忽略"）、HITL 审批 |
| **vote_interaction** | 投票交互卡片 | 多选项投票/调查，如"请选择处理方式：A/B/C" |
| **multiple_interaction** | 多项交互卡片 | 复杂表单类交互，如多字段选择提交、多步骤引导 |
| **template_notice** | 模板通知卡片 | 结构化通知（如审批流通知、系统告警通知） |

**能力降级映射（AgentEvent → Bot 渠道格式）**：

由于 Bot 渠道不支持流式输出和 Generative UI，Agent 产生的 AgentEvent 需降级映射：

| AgentEvent 类型 | H5 渠道（富交互） | Bot 渠道（降级） |
|----------------|------------------|-----------------|
| `text.delta`（流式文本） | CopilotKit 实时流式渲染 | **累积为完整文本** → `text_notice` 卡片（不支持流式） |
| `ui.render`（动态 UI 组件） | CopilotKit Generative UI 渲染 React 组件 | **按组件类型映射**：表格/列表 → `text_notice`；图表/图片 → `news_notice`；按钮/操作 → `button_interaction`；表单 → `multiple_interaction` |
| `tool.call` / `tool.result` | 前端实时显示工具调用状态 | **隐藏或简化**为 `text_notice`（"正在查询..." → "查询完成"） |
| `approval.request`（审批请求） | CopilotKit 弹窗审批 | **降级为** `button_interaction`（"同意"/"拒绝"按钮） |
| `error` | 前端错误提示组件 | `text_notice` 错误信息卡片 |
| `done` | 流式结束标记 | 无需额外处理 |

**Bot 渠道设计要点**：
1. **无流式输出**：Agent 完整生成后一次性发送卡片消息，首响延迟可能较高（需在 UI 上提示"思考中..."）
2. **交互受限**：复杂表单/动态图表等 Generative UI 场景无法在 Bot 中呈现，引导用户打开 H5 获取完整体验
3. **主动推送**：Bot 渠道适合主动推送场景（审批待办、数据摘要、任务提醒），通过 template_card 推送到用户/群
4. **上下文保持**：Bot 渠道与 H5 渠道共享同一用户会话上下文，用户可跨渠道继续对话

### 5.6 渠道能力矩阵

| 能力维度 | 企业微信 H5 | 企业微信智能机器人 | 独立 H5 |
|---------|------------|------------------|---------|
| **接入方式** | 企业微信工作台嵌入 H5 + JS-SDK | 企业微信机器人 WebSocket 长连接 | 独立 Web 应用 |
| **流式输出** | ✅ 支持（SSE/WebSocket） | ❌ 不支持（完整生成后发送） | ✅ 支持（SSE/WebSocket） |
| **Generative UI** | ✅ 支持（CopilotKit React 组件） | ❌ 不支持 | ✅ 支持（CopilotKit React 组件） |
| **动态卡片交互** | ✅ 完整支持（表格/图表/表单等） | ⚠️ 仅 6 种 template_card | ✅ 完整支持 |
| **Markdown 渲染** | ✅ 支持 | ⚠️ 有限支持（text_notice 内） | ✅ 支持 |
| **代码高亮** | ✅ 支持 | ❌ 不支持 | ✅ 支持 |
| **HITL 审批** | ✅ CopilotKit 弹窗 | ⚠️ button_interaction 卡片 | ✅ CopilotKit 弹窗 |
| **主动推送** | ✅ 应用消息通知 | ✅ template_card 推送 | ✅ WebSocket 推送 |
| **用户身份识别** | ✅ JS-SDK 自动登录 | ✅ 企业微信用户身份 | ⚠️ 用户名密码登录 |
| **上下文共享** | ✅ 与其他渠道共享会话 | ✅ 与其他渠道共享会话 | ✅ 与其他渠道共享会话 |
| **适用场景** | 日常富交互、动态 UI | 轻量问答、主动推送、快速操作 | 完整体验、管理后台 |

### 5.7 Agent 智能路由设计

前端**不提供**用户选择运行时/Agent 的功能。所有用户请求由后台 **AgentRouter** 自动路由到合适的 Agent。

**路由策略（优先级从高到低）**：

```
用户请求到达
     │
     ▼
┌──────────────────────────────────────────┐
│  策略1: 会话亲和性 (Session Affinity)       │
│  同一用户同一会话 → 路由到上次服务的 Agent    │
│  命中率: 高（连续对话场景）                  │
└──────────────────┬───────────────────────┘
                   │ 未命中
                   ▼
┌──────────────────────────────────────────┐
│  策略2: 关键词匹配 (Keyword Matching)       │
│  预定义关键词 → 对应 Agent                  │
│  如 "请假/年假/考勤" → HR助手              │
│  如 "报销/凭证/预算" → 财务助手             │
│  命中率: 中（明确意图场景）                  │
└──────────────────┬───────────────────────┘
                   │ 未命中
                   ▼
┌──────────────────────────────────────────┐
│  策略3: 语义检索 (Semantic Retrieval)       │
│  用户请求 → 向量检索 → 匹配 Agent 描述      │
│  基于各 Agent 的 Skills 覆盖范围语义匹配     │
│  命中率: 中高（模糊意图场景）                │
└──────────────────┬───────────────────────┘
                   │ 未命中/置信度低
                   ▼
┌──────────────────────────────────────────┐
│  策略4: 默认 Agent 兜底 (Default Fallback)  │
│  路由到通用助手 Agent（平台通用 Skills）     │
│  保证用户请求始终得到响应                    │
└──────────────────────────────────────────┘
```

**路由设计要点**：
1. **用户无感知**：用户不需要知道当前在跟哪个 Agent 对话，所有 Agent 共享统一对话界面
2. **会话亲和性**：同一会话尽量保持路由到同一 Agent，避免上下文断裂
3. **路由可观测**：管理后台可查看路由日志、命中率、各 Agent 流量分布
4. **路由可配置**：关键词规则、语义匹配阈值、默认 Agent 均可配置
5. **跨渠道一致**：无论用户从哪个渠道发起请求，AgentRouter 路由逻辑一致

---

## 6. 后端架构需求要点

### 6.1 多配置管理模型

**配置数据模型**：

```yaml
AgentConfig:
  id: "agent-hr-assistant"
  name: "HR 助手"
  description: "人力资源问答与流程处理"
  
  # 运行时配置
  runtime:
    type: "openharness"          # openharness | custom | langgraph
    version: "1.0.0"
    params:
      maxSteps: 20
      temperature: 0.7
  
  # 模型配置（双模型策略，通过 LLM 网关访问厂家 API）
  model:
    primary: "deepseek-v4-flash"      # 主力模型（通用对话/Tool Calling/快速响应）
    fallback: "qwen3.6-plus"          # 备选模型（复杂推理/长上下文场景）
    strategy: "default-primary"       # 默认使用主力模型，复杂推理任务切换备选
    gateway: "llm-gateway"            # 通过 LLM 网关层统一管理 API Key 与出站代理
    # API Key 不在此配置，由 LLM 网关层统一管理
  
  # 系统提示词
  systemPrompt: "你是公司HR助手..."
  
  # Skills 配置（引用 Skills 注册中心）
  skills:
    - skillId: "skill-leave-query"
      enabled: true
    - skillId: "skill-salary-slip"
      enabled: true
      requiresApproval: true     # 敏感操作需审批
    - skillId: "skill-org-chart"
      enabled: true
  
  # MCP Server 配置
  mcpServers:
    - name: "hr-system-mcp"
      transport: "http"
      endpoint: "http://hr-system:8080/mcp"
      tools: ["query_employee", "submit_leave"]
  
  # 权限配置
  accessControl:
    allowedDepartments: ["HR", "Finance"]
    allowedRoles: ["employee", "hr_manager"]
    skillOverrides:
      "skill-salary-slip":        # 覆盖特定 Skill 的权限
        allowedRoles: ["hr_manager"]
  
  # 推送配置
  push:
    enabled: true
    channels: ["wecom_h5", "wecom_bot"]   # 企业微信 H5 应用消息 + 企业微信 Bot template_card
    schedules:
      - cron: "0 9 * * 1"        # 每周一9点推送周报
        target: "department:HR"
        template: "weekly_report"
        botCardType: "news_notice"        # Bot 渠道使用图文通知卡片
```

**配置管理要求**：
- 支持配置版本管理（每次修改生成新版本，可回滚）
- 支持热更新（Skills 增减、提示词修改无需重启实例）
- 配置校验（Skill 引用有效性、MCP 连通性、权限合规性）
- 配置导入/导出（YAML/JSON 格式）

### 6.2 配置目录结构设计

**设计理念 — 配置即实例**：每个 Agent 对应一套独立的配置目录，包含该 Agent 运行所需的全部配置文件。运营人员通过编辑配置目录（非编码）即可创建和管理 Agent，配置变更后热更新生效。

**配置目录结构**：

```
configs/
└── agents/
    └── {agent_name}/                    # 每个 Agent 一套配置目录
        ├── agent.yaml                   # Agent 主配置文件（核心定义）
        ├── skills/                      # Skills 配置目录
        │   ├── enabled-skills.yaml      # 启用的 Skills 列表与参数覆盖
        │   ├── skill-overrides/         # 特定 Skill 的参数覆盖
        │   │   ├── skill-leave-query.yaml
        │   │   └── skill-salary-slip.yaml
        │   └── custom-skills/           # Agent 专属自定义 Skill 定义
        │       └── custom-report.yaml
        ├── runtime/                     # 运行时配置目录
        │   ├── runtime.yaml             # 运行时类型与参数（openharness/custom/langgraph）
        │   ├── prompts/                 # 系统提示词
        │   │   ├── system-prompt.md     # 主系统提示词
        │   │   └── few-shot/            # Few-shot 示例
        │   │       └── examples.yaml
        │   └── middleware/              # 中间件配置（上下文压缩、重试等）
        │       └── middleware.yaml
        ├── identity/                    # 身份与权限配置目录
        │   ├── access-control.yaml      # 部门/角色权限配置
        │   ├── skill-permissions.yaml   # Skills 级别权限覆盖
        │   └── sensitive-ops.yaml       # 敏感操作审批配置
        ├── system/                      # 系统级配置目录
        │   ├── model.yaml               # LLM 模型配置（主力/备选/策略）
        │   ├── mcp-servers.yaml          # MCP Server 连接配置
        │   ├── push.yaml                # 推送配置（渠道/定时/模板）
        │   └── llm-gateway.yaml         # LLM 网关路由配置（引用全局网关）
        ├── memory/                      # 记忆配置目录（v1.4 新增）
        │   ├── agent-memory.yaml        # 静态长期记忆（角色背景/固定知识/行为准则）
        │   ├── personality.md           # 人格记忆（语气/风格/交互偏好）
        │   └── facts/                   # 事实知识库（领域知识/FAQ）
        │       └── hr-policies.yaml     # 示例：HR 政策事实
        └── metadata.yaml                # Agent 元数据（名称/描述/版本/标签，供 AgentRouter 语义检索）
```

**agent.yaml 主配置文件示例**：

```yaml
# Agent 主配置
agent:
  name: "hr-assistant"
  display_name: "HR 助手"
  description: "人力资源问答与流程处理，支持考勤/薪酬/招聘/培训等场景"
  version: "1.0.0"
  tags: ["HR", "人事", "考勤", "薪酬", "招聘"]
  
  # 引用各子配置
  includes:
    runtime: "runtime/runtime.yaml"
    skills: "skills/enabled-skills.yaml"
    identity: "identity/access-control.yaml"
    system: "system/model.yaml"
    mcp: "system/mcp-servers.yaml"
    push: "system/push.yaml"
    memory: "memory/agent-memory.yaml"       # 静态记忆引用（v1.4 新增）
  
  # AgentRouter 路由配置
  routing:
    keywords: ["请假", "年假", "考勤", "薪酬", "招聘", "培训", "HR"]  # 关键词匹配规则
    enabled: true                                                       # 是否参与自动路由
    priority: 10                                                        # 路由优先级（数值越高越优先）
```

**双模式存储**：
- **文件系统模式**：配置以 YAML 文件形式存储在 configs/agents/ 目录下，适合开发调试和版本管理（Git）
- **数据库模式**：配置存储在 PostgreSQL 中，适合生产环境多实例部署和管理后台在线编辑
- 两种模式可双向同步：文件 → 数据库（导入）、数据库 → 文件（导出）
- 管理后台支持在线编辑配置，变更后自动同步到文件系统（如启用）并触发热更新

**热更新机制**：
1. 配置变更（文件修改或数据库更新）触发配置变更事件
2. 配置校验器验证变更合法性（Skill 引用、MCP 连通性、权限合规）
3. 校验通过后，配置加载器将新配置推送到对应 Agent 实例
4. Agent 实例热加载新配置（Skills 增减、提示词修改等），进行中会话使用旧配置完成，新会话使用新配置
5. 热更新生效时间 < 10s

### 6.3 Agent 实例生命周期

```
                    ┌─────────┐
                    │ Created │ (配置已创建，实例未启动)
                    └────┬────┘
                         │ start()
                         ▼
                    ┌─────────┐
          ┌────────│ Running │◄─────────────────┐
          │        └────┬────┘                  │
          │             │ pause()               │ resume()
          │             ▼                       │
          │        ┌─────────┐                  │
          │        │ Paused  │──────────────────┘
          │        └────┬────┘
          │             │ stop()
          │             ▼
          │        ┌─────────┐
          │        │Draining │ (等待进行中会话完成)
          │        └────┬────┘
          │             │ all sessions done
          │             ▼
          │        ┌─────────┐
          └───────►│ Stopped │ (实例已停止，配置保留)
                   └────┬────┘
                        │ delete()
                        ▼
                   ┌─────────┐
                   │ Deleted │ (配置和实例均删除)
                   └─────────┘
```

**生命周期关键要求**：
- **优雅停机**：Draining 状态下拒绝新会话，等待进行中会话完成或超时（可配置）
- **健康检查**：Running 状态定期心跳检测，异常自动重启
- **会话隔离**：每个 Agent 实例维护独立的会话上下文，不跨实例泄漏
- **资源限制**：每实例最大并发会话数可配置，超限排队

### 6.4 Skills 注册与发现机制

**Skill 注册来源**：

| 来源 | 描述 | 注册方式 |
|------|------|----------|
| 业务系统 Skills | 财务/超市/百货/人事/物业/CRM/储值卡等业务系统通过**业务系统适配层（Business System Adapter）**封装为标准 MCP Server 接口 | 适配层将各系统不统一的 API 封装为统一 MCP 接口，自动注册为 Skills |
| 自定义 Skill | 内部开发的 Python/TS 函数 | 通过 API/配置注册，含名称、描述、参数 Schema、处理函数 |
| MCP Server Tools | 外部 MCP Server 提供的工具 | 配置 MCP Server 连接信息，自动发现 Tools |
| 内置 Skill | 平台预置能力（如搜索、计算） | 系统自带，开箱即用 |

> **业务系统适配层说明**：各业务系统（财务、超市管理、百货管理、人事系统、物业系统、CRM 系统、储值卡系统，共 7 个）现有 API 不统一，需开发统一的 **Business System Adapter**，将各系统 API 封装为标准 MCP Server 接口，实现 Skills 的统一注册、发现和调用。

**Skill 元数据结构**：

```yaml
Skill:
  id: "skill-leave-query"
  name: "请假查询"
  description: "查询员工的请假记录和剩余年假天数"
  category: "HR"                   # 分类标签
  tags: ["请假", "年假", "考勤"]    # 语义标签
  
  # 参数定义
  parameters:
    type: "object"
    properties:
      employeeId:
        type: "string"
        description: "员工ID"
      dateRange:
        type: "object"
        properties:
          start: { type: "string", format: "date" }
          end: { type: "string", format: "date" }
    required: ["employeeId"]
  
  # 权限要求
  requiredPermissions: ["hr:leave:read"]
  
  # 语义索引
  embedding: [0.12, -0.34, ...]     # 由 description 生成
  
  # 执行信息
  handler: "mcp://hr-system-mcp/query_leave"  # 或 "function://..."
  timeout: 30000                    # 超时 ms
  retryCount: 2
  
  version: "1.2.0"
  status: "active"
```

**发现机制**：
- **注册时**：自动为 Skill 的 description + name + tags 生成语义向量，存入向量索引
- **运行时**：用户请求到达后，先经语义检索召回 Top-K 相关 Skills（K ≤ 20），再结合身份权限过滤，最终注入 Agent 上下文
- **MCP 自动发现**：连接 MCP Server 后，调用 `tools/list` 获取所有 Tools，自动注册为 Skills

### 6.5 670+ Skills 场景下的调度策略

**核心挑战**：670+ Skills 的完整定义（含参数 Schema）远超 LLM 上下文窗口限制，无法一次性注入。

**Skills 一级分类总览（8 个分类，约 670+ Skills）**：

| 分类 | 预估 Skills 数量 | 说明 |
|------|----------------|------|
| 财务系统 | ~100 | 凭证、报表、报销、预算、成本核算等 |
| 超市管理系统 | ~90 | 商品、库存、促销、收银、会员价等 |
| 百货管理系统 | ~80 | 柜组、品牌、专柜、联营、扣点等 |
| 人事系统 | ~100 | 考勤、薪酬、招聘、培训、绩效等 |
| 物业系统 | ~70 | 租户、合同、报修、巡检、缴费等 |
| CRM 系统 | ~80 | 会员、积分、等级、标签、画像、营销活动、客户旅程 |
| 储值卡系统 | ~70 | 发卡、充值、消费、退款、余额查询、卡券、规则引擎、对账 |
| 平台通用 | ~80 | 搜索、计算、日历、通知、知识库等跨系统通用能力 |
| **合计** | **~670+** | |

> 各业务系统 Skills 通过**业务系统适配层（Business System Adapter）**统一接入，平台通用 Skills 为内置开发。

**调度策略 — 两阶段检索**：

```
用户请求: "帮我查一下这个月还剩多少年假"
         │
         ▼
┌──────────────────────────────────────────────┐
│  阶段1: 语义检索 (Skill Retriever)              │
│                                                │
│  输入: 用户请求文本                              │
│  操作: 向量相似度检索 → Top-50 候选 Skills       │
│  延迟: < 200ms                                 │
└───────────────────┬──────────────────────────┘
                    │ Top-50 候选
                    ▼
┌──────────────────────────────────────────────┐
│  阶段2: 权限过滤 + 精排 (Skill Ranker)          │
│                                                │
│  操作:                                         │
│  1. 过滤: 移除用户无权限的 Skills               │
│  2. 精排: LLM-based rerank 或规则排序           │
│     - 使用频率加权                               │
│     - 最近使用加权                               │
│     - 分类匹配加权                               │
│  输出: Top-K Skills (K ≤ 20)                   │
└───────────────────┬──────────────────────────┘
                    │ Top-20 Skills (仅名称+描述)
                    ▼
┌──────────────────────────────────────────────┐
│  阶段3: 上下文注入 (Context Injector)            │
│                                                │
│  操作: 将 Top-K Skills 的精简定义注入系统提示词   │
│  注入内容: name + description (不含完整 Schema)  │
│  延迟触发: Agent 选中某 Skill 时再加载完整 Schema │
└──────────────────────────────────────────────┘
```

**调度策略关键设计**：

| 策略 | 说明 |
|------|------|
| **延迟加载 Schema** | 初始仅注入 Skill 名称+描述，Agent 决定调用时再加载完整参数 Schema |
| **分类预过滤** | 根据用户身份/部门先按分类缩小检索范围（如 HR 部门仅检索 HR 类 Skills） |
| **缓存热 Skills** | 高频 Skill 的定义缓存在内存，减少检索开销 |
| **Skill 分组** | 670+ Skills 按业务系统分组（财务/超市管理/百货管理/人事/物业/CRM/储值卡等），支持按组检索 |
| **动态 K 值** | 根据请求复杂度动态调整 K 值（简单问题 K=5，复杂问题 K=20） |
| **Fallback** | 语义检索无结果时，回退到关键词匹配或展示 Skill 分类目录 |

### 6.6 运行时抽象层设计

**设计目标**：OpenHarness 为初始实现，支持切换至自研 Agent 或其他框架，切换零代码改动。

**运行时抽象接口**：

```typescript
interface AgentRuntime {
  // 基本信息标识
  readonly runtimeType: string;      // "openharness" | "custom" | "langgraph"
  readonly version: string;

  // 执行接口
  run(
    messages: Message[],
    config: AgentConfig
  ): AsyncIterable<AgentEvent>;      // 流式事件输出

  // 工具管理
  registerTools(skills: Skill[]): void;
  registerMCP(server: MCPServerConfig): void;

  // 状态管理
  getState(sessionId: string): AgentState;
  setState(sessionId: string, state: AgentState): void;

  // 生命周期
  initialize(config: AgentConfig): Promise<void>;
  healthCheck(): Promise<HealthStatus>;
  shutdown(): Promise<void>;
}

// 统一事件类型
type AgentEvent =
  | { type: "text.delta"; content: string }
  | { type: "tool.call"; toolName: string; args: any }
  | { type: "tool.result"; toolName: string; result: any }
  | { type: "ui.render"; component: string; props: any }    // Generative UI
  | { type: "approval.request"; skillId: string; detail: any }
  | { type: "error"; code: string; message: string }
  | { type: "done"; tokenUsage: TokenUsage };
```

**运行时注册机制**：

```yaml
RuntimeRegistry:
  runtimes:
    - type: "openharness"
      factory: "OpenHarnessRuntimeFactory"
      default: true
      capabilities:
        - streaming: true
        - generativeUI: true
        - mcp: true
        - multiAgent: true
        - hitl: true
    
    - type: "custom"
      factory: "CustomRuntimeFactory"
      capabilities:
        - streaming: true
        - generativeUI: false
        - mcp: true
        - multiAgent: false
        - hitl: true
```

**切换流程**：
1. 管理员在配置中修改 `runtime.type`
2. 系统创建新运行时实例并初始化
3. 新会话路由至新运行时
4. 旧运行时进入 Draining 状态
5. 旧会话完成后销毁旧运行时

**OpenHarness 框架说明**：
- OpenHarness 是香港大学数据科学研究所（HKUDS）开源的轻量级 Agent 基础设施框架（MIT 协议，3.5k+ Star）
- 核心理念：Agent = LLM（智能）+ Harness（双手+双眼+记忆+安全边界），模型决定做什么，Harness 决定怎么做
- 内置 43+ 工具（文件读写、Shell 执行、代码搜索、Web 抓取、MCP 协议等）、Skills 系统（40+ 内置技能，.md 格式按需加载）
- MCP 协议客户端（stdio/HTTP/SSE 三种传输）、权限系统（默认/自动/计划三种模式，路径级规则+命令黑名单）
- 多 Agent 协作（Swarm 协调机制，动态生成子 Agent）、持久记忆子系统、生命周期钩子（hooks）、插件系统
- Python 96.5% + React 3.5%（终端 UI），uv 包管理，Python 3.10+，支持 Anthropic/OpenAI API 格式
- 模型支持：通义千问、DeepSeek、Kimi、Ollama、Groq、SiliconFlow 等

**平台集成方式**：
- 后端通过 Python 包引入 OpenHarness engine 引擎
- 用平台 LLM Gateway 替换 OpenHarness 默认 LLM 调用（统一 API Key 管理、Token 计费、出站代理）
- 用平台 Skills 系统替换 OpenHarness 内置 Skills（670+ 业务 Skills 语义检索+权限过滤）
- 保留 OpenHarness 的 MCP 客户端（连接业务系统适配层）
- 保留 OpenHarness 的权限系统（与平台身份鉴权联动）
- 天然支持流式输出（Agent Loop 引擎）
- 支持子代理委托（多 Agent Swarm 协调场景）
- 可组合中间件（上下文压缩、重试、持久化）
- 无状态设计 — 状态由平台管理层负责

### 6.7 AgentRouter 智能路由设计

**设计目标**：用户无需手动选择 Agent，AgentRouter 根据用户请求自动路由到最合适的 Agent 实例。

**路由架构**：

```typescript
interface AgentRouter {
  // 路由入口
  route(request: UserRequest, sessionContext: SessionContext): AgentConfig;
  
  // 路由策略链
  strategies: RoutingStrategy[];
}

type RoutingStrategy =
  | { type: "session_affinity" }           // 会话亲和性
  | { type: "keyword_matching" }            // 关键词匹配
  | { type: "semantic_retrieval" }          // 语义检索
  | { type: "default_fallback" };           // 默认兜底
```

**路由流程**：
1. 用户请求到达统一消息网关，附带会话上下文
2. AgentRouter 按策略链顺序尝试路由：
   - **会话亲和性**：检查该会话是否已有绑定的 Agent，有则直接路由（保证上下文连贯）
   - **关键词匹配**：各 Agent 配置的 `routing.keywords` 与用户请求文本匹配
   - **语义检索**：用户请求文本 → 向量检索 → 匹配各 Agent 的 `metadata.description` + Skills 覆盖范围
   - **默认兜底**：路由到默认通用助手 Agent
3. 路由结果记录到路由日志，供管理后台可观测

**路由配置**（在 agent.yaml 中声明）：

```yaml
routing:
  keywords: ["请假", "年假", "考勤", "薪酬", "招聘"]  # 关键词匹配
  enabled: true                                       # 是否参与自动路由
  priority: 10                                        # 优先级（高优先）
```

**路由可观测性**：
- 路由日志：每次路由决策的策略、命中 Agent、置信度
- 路由统计：各 Agent 流量分布、各策略命中率、路由延迟
- 路由调优：管理后台支持调整关键词规则、语义匹配阈值、默认 Agent

### 6.8 LLM 网关层设计

**设计目标**：统一管理多厂家 LLM API Key，实现成本控制与故障切换，LLM 请求通过内网出站代理访问厂家 API 端点。

**LLM 网关架构**：

```
┌─────────────────────────────────────────────────────────┐
│                     LLM 网关层                            │
│                                                          │
│  ┌─────────────────┐  ┌─────────────────┐               │
│  │ API Key 管理器    │  │ Token 计费追踪    │               │
│  │ 多厂家 Key 轮转   │  │ 按会话/用户/部门   │               │
│  │ 故障自动切换      │  │ 用量记录与统计     │               │
│  └─────────────────┘  └─────────────────┘               │
│                                                          │
│  ┌─────────────────┐  ┌─────────────────┐               │
│  │ 配额管理器        │  │ 出站代理管理器     │               │
│  │ 部门/用户配额     │  │ 内网 → 厂家 API   │               │
│  │ 超限告警/限流     │  │ 代理池/负载均衡    │               │
│  └─────────────────┘  └─────────────────┘               │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │ 模型路由器                                         │    │
│  │ deepseek-v4-flash（主力）↔ qwen3.6-plus（备选）   │    │
│  │ 按任务类型/成本/延迟动态选择                        │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
   ┌──────────┐                  ┌──────────┐
   │ 内网出站   │                  │  内网出站  │
   │ 代理      │                  │  代理     │
   └────┬─────┘                  └────┬─────┘
        │                              │
        ▼                              ▼
  DeepSeek API                    Qwen API
  (厂家服务端点)                  (厂家服务端点)
```

**LLM 网关核心能力**：

| 能力 | 说明 |
|------|------|
| **多厂家 API Key 管理** | 统一管理 deepseek/qwen 等厂家 API Key，支持 Key 轮转、过期预警、故障切换 |
| **模型路由** | 按任务类型/成本/延迟动态选择模型（P2-01），默认 deepseek-v4-flash，复杂推理切 qwen3.6-plus |
| **Token 计费追踪** | 按会话/用户/部门维度记录 Token 消耗，支持成本分摊 |
| **配额管理** | 按部门/用户设置 Token 配额，超限告警/限流 |
| **出站代理** | LLM API 请求通过内网出站代理访问厂家服务端点，代理池支持负载均衡与高可用 |
| **故障切换** | 主力模型 API 不可用时自动切换到备选模型 |
| **请求缓存** | 相同请求的响应缓存（可选），降低 API 调用成本 |

**LLM 网关配置示例**（全局配置，各 Agent 引用）：

```yaml
LLMGateway:
  providers:
    deepseek:
      apiKeys:
        - { ref: "secret://deepseek-key-1" }
        - { ref: "secret://deepseek-key-2" }
      endpoint: "https://api.deepseek.com/v1"
      models: ["deepseek-v4-flash"]
      proxy: "http://outbound-proxy:8080"    # 内网出站代理
      keyRotation: "round-robin"
    
    qwen:
      apiKeys:
        - { ref: "secret://qwen-key-1" }
      endpoint: "https://dashscope.aliyuncs.com/api/v1"
      models: ["qwen3.6-plus"]
      proxy: "http://outbound-proxy:8080"    # 内网出站代理
      keyRotation: "round-robin"
  
  costControl:
    defaultQuota:
      perUser: 100000          # 每用户每日 Token 配额
      perDepartment: 1000000   # 每部门每日 Token 配额
    alertThreshold: 0.8        # 配额使用 80% 告警
  
  failover:
    primary: "deepseek"
    fallback: "qwen"
    autoSwitch: true           # 主力不可用自动切换
```

---

### 6.9 Agent 记忆机制设计

**设计背景**：其他系统每套运行时配置都有 memory.md，用于定义 Agent 的持久化记忆。本平台采用更结构化的两层记忆模型，既保留配置式静态记忆的确定性，又支持交互中动态积累的语义记忆。

**两层记忆模型**：

| 层次 | 存储位置 | 维护方 | 内容 | 生命周期 |
|------|---------|--------|------|---------|
| **静态记忆** | `configs/agents/{agent_name}/memory/` 目录（YAML/MD 文件） | 运营人员 | 角色背景、人格风格、领域知识、行为准则、FAQ 事实 | 配置文件，随热更新生效 |
| **动态记忆** | PostgreSQL `agent_memory` 表 + Qdrant `agent_memory_index` collection | Agent 自动写入 | 用户偏好、重要决策、任务摘要、交互中的上下文发现 | 按遗忘策略自动清理（TTL/容量/重要性） |

**静态记忆目录结构**：

```
memory/
├── agent-memory.yaml          # 长期记忆主文件（角色背景/核心知识/行为准则）
├── personality.md             # 人格记忆（语气/风格/交互偏好，自然语言描述）
└── facts/                     # 事实知识库（结构化领域知识）
    ├── hr-policies.yaml       # 示例：HR 政策事实（休假制度/报销标准等）
    ├── finance-rules.yaml     # 示例：财务规则
    └── retail-faq.yaml        # 示例：零售常见问答
```

**静态记忆示例（agent-memory.yaml）**：

```yaml
# ===== HR 助手静态记忆 =====
role:
  identity: "公司人力资源助手"
  scope: "负责考勤、薪酬、招聘、培训等 HR 相关咨询与流程处理"
  limitations:
    - "不提供法律咨询"
    - "不直接修改薪酬数据，需走审批流程"

knowledge:
  company: "某某集团，员工约 3000 人，总部设在上海"
  departments: ["财务部", "超市事业部", "百货事业部", "人事部", "物业部", "CRM 中心", "储值卡中心"]
  systems: ["用友财务", "超市 POS", "百货 CRM", "北森 HR", "物业工单"]

behavior:
  - "涉及薪酬数据时，先验证用户身份和权限"
  - "推荐流程时附带审批链接"
  - "不确定的信息要明确告知用户，不编造"
```

**动态记忆数据库表设计（agent_memory）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| agent_name | VARCHAR(64) | Agent 标识 |
| session_id | VARCHAR(128) | 会话标识（可空，全局记忆为 NULL） |
| user_id | VARCHAR(128) | 用户标识（可空） |
| memory_type | VARCHAR(32) | 记忆类型：preference / decision / summary / context |
| content | TEXT | 记忆内容（自然语言） |
| importance | FLOAT | 重要性分数（0.0-1.0），影响检索排序和遗忘策略 |
| created_at | TIMESTAMP | 创建时间 |
| expires_at | TIMESTAMP | 过期时间（NULL = 永不过期） |
| access_count | INT | 被检索命中次数 |
| last_accessed_at | TIMESTAMP | 最后被检索时间 |

**动态记忆向量索引**：Qdrant `agent_memory_index` collection，复用 bge-small-zh-v1.5 模型生成向量，支持按 agent_name + user_id 过滤检索。

**运行时记忆注入流程**：

```
用户消息到达
    │
    ▼
┌─────────────────────────────────┐
│ 1. 系统提示词（runtime/prompts/） │ ← Agent 基础人设
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ 2. 静态记忆（memory/ 目录）       │ ← 角色背景/领域知识/行为准则
│    agent-memory.yaml + facts/   │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ 3. 动态记忆 Top-K（Qdrant 检索）  │ ← 与当前消息语义相关的历史记忆
│    按 agent + user 过滤          │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│ 4. 对话历史（Redis 会话上下文）    │ ← 当前会话的最近 N 轮对话
└──────────────┬──────────────────┘
               ▼
        组装完整上下文 → LLM
```

**动态记忆写入时机**：
- Agent 在对话中识别到用户偏好（如"我喜欢简洁的回复"）→ 写入 preference 类型
- Agent 完成重要决策（如"选择了方案 A"）→ 写入 decision 类型
- 会话结束时自动生成摘要 → 写入 summary 类型
- Agent 发现重要上下文（如"用户是财务部的"）→ 写入 context 类型

**遗忘策略**：
- **TTL 过期**：动态记忆默认 30 天过期，可通过 importance 调整（importance > 0.8 的永不过期）
- **容量上限**：每个 agent + user 维度最多保留 200 条动态记忆，超出时按 importance × recency 综合评分淘汰
- **重要性衰减**：access_count 低的记忆 importance 逐月衰减（×0.95/月）

---

## 7. 非功能需求

### 7.1 性能

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 消息收发延迟 | < 2s | 企业微信 H5 / Bot → 后端 → Agent → 响应 |
| 首 Token 延迟 | < 3s | 670 Skills 场景下含检索时间（deepseek-v4-flash / qwen3.6-plus，经出站代理） |
| Skill 语义检索延迟 | < 200ms | 向量检索 Top-50（本地 Embedding + Qdrant） |
| Agent 配置热更新生效 | < 10s | 修改配置到新会话使用新配置 |
| AgentRouter 路由延迟 | < 500ms | 会话亲和性/关键词/语义检索/兜底策略链 |
| 并发会话数（单实例） | ≥ 100 | 100-200 用户并发，单实例可覆盖 |
| 系统吞吐量 | ≥ 200 QPS | 内网部署，100-200 用户规模 |
| LLM 网关出站代理延迟 | < 100ms | 内网出站代理到厂家 API 的额外延迟 |
| 动态记忆写入延迟 | < 500ms | Agent 写入 agent_memory 表 + Qdrant 向量索引 |
| 动态记忆检索延迟 | < 200ms | Qdrant agent_memory_index 语义检索 Top-K（含 Embedding） |

### 7.2 安全

| 要求 | 说明 |
|------|------|
| 身份认证 | 企业微信 OAuth2 直连（唯一身份源）+ 本地 JWT；独立 H5 用户名密码登录（用户数据来自企业微信同步）；不引入独立 IdP |
| 权限最小化 | Skills 按需授权，默认拒绝原则 |
| 数据加密 | 内网传输可选 TLS，存储层 AES-256；内网网络隔离 |
| 敏感数据脱敏 | Agent 输出中自动脱敏（手机号、身份证、薪资等） |
| 沙箱隔离 | 代码执行类 Skill 在容器沙箱中运行 |
| API 限流 | 按用户/部门/IP 维度限流 |
| 密钥管理 | **LLM 网关层**统一管理多厂家 API Key（deepseek/qwen），AES-256 加密存储，支持 Key 轮转与故障切换；MCP 凭证统一管理；**业务系统凭证托管**（见 P1-11）：7 个业务系统登录凭证 AES-256 加密存储，适配层自动认证 |
| 内网出站代理 | LLM API 请求通过内网出站代理访问厂家服务端点，代理层支持访问白名单（仅允许已知厂家 API 域名）、请求审计日志 |
| Bot 渠道安全 | 企业微信智能机器人 WebSocket 长连接需鉴权验证，消息来源校验防止伪造 |

### 7.3 可扩展性

| 要求 | 说明 |
|------|------|
| 水平扩展 | Agent 实例无状态，支持多副本部署 |
| Skills 弹性 | 新 Skill 注册无需重启，热加载 |
| 运行时插件化 | 新运行时通过实现接口 + 注册即可接入 |
| MCP 动态接入 | 运行时动态添加/移除 MCP Server |
| 渠道可扩展 | 新增渠道（如钉钉、飞书）只需实现消息网关适配器 |

### 7.4 高可用

| 要求 | 说明 |
|------|------|
| 可用性 | 99.9% SLA |
| 故障转移 | Agent 实例多副本，自动故障转移 |
| 消息不丢失 | 企业微信消息持久化队列，失败重试 |
| 会话恢复 | 会话状态持久化，实例重启后可恢复 |
| 监控告警 | 全链路监控（消息网关 → Agent → Skills），异常自动告警 |
| 灰度发布 | 新配置/新运行时支持灰度发布，按比例引流 |

---

## 8. 待确认问题

| 编号 | 问题 | 影响范围 | 状态/建议 |
|------|------|----------|------|
| Q1 | ~~企业微信应用类型~~ | ~~前端渠道接入~~ | ✅ **已确认**：H5 嵌入企业微信工作台，JS-SDK 鉴权 |
| Q2 | ~~微信端具体形态~~ | ~~渠道能力边界~~ | ✅ **v1.3 更新**：v1.2 删除的微信机器人已由**企业微信智能机器人**替代（不同形态），渠道恢复为三渠道。企业微信后台智能机器人，WebSocket 长连接，仅支持 6 种 template_card |
| Q3 | ~~身份体系~~ | ~~权限控制、身份识别~~ | ✅ **已确认**：企业微信 OAuth2 直连 + 本地 JWT。不引入独立 IdP 组件（不用 Casdoor/Keycloak），企业微信作为唯一身份源，组织架构定时同步到本地。独立 H5 入口使用用户名密码登录（用户数据来自企业微信同步）。7 个业务系统各自独立账号，适配层内置凭证托管 |
| Q4 | ~~模型供应商~~ | ~~模型配置、成本、合规~~ | ✅ **v1.3 更新**：主力模型 deepseek-v4-flash + 备选模型 qwen3.6-plus，通过**购买厂家 API 服务**使用（不自建 GPU 推理集群），经 LLM 网关层管理 + 内网出站代理访问 |
| Q5 | ~~Skills 来源~~ | ~~Skills 注册、开发工作量~~ | ✅ **已确认**：来自财务、超市管理、百货管理、人事系统、物业系统、CRM 系统、储值卡系统等业务系统，共 8 个一级分类，约 670+ Skills |
| Q6 | **自研运行时时间线**：自研 Agent 运行时预计何时启动？OpenHarness 预期使用周期？ | 运行时抽象层设计深度 | 建议先以 OpenHarness 跑通，再启动自研 |
| Q7 | **推送频率与场景**：主动推送的具体场景有哪些？是否需要订阅/退订机制？Bot 渠道推送的 template_card 模板有哪些？ | 推送机制设计 | 建议支持用户级推送偏好设置；Bot 推送模板需与企业微信模板对齐 |
| Q8 | ~~部署环境~~ | ~~架构选型、安全方案~~ | ✅ **v1.3 更新**：内网部署，全部组件内网可访问；LLM API 通过**内网出站代理**访问厂家服务端点；Embedding 模型 bge-small-zh-v1.5 内网部署 |
| Q9 | ~~并发规模~~ | ~~容量规划~~ | ✅ **已确认**：100-200 用户并发 |
| Q10 | **数据合规**：对话记录是否需要留存？留存期限？隐私合规审查？ | 存储设计、合规 | 需法务确认 |
| Q11 | **CopilotKit 许可**：MIT 核心功能是否足够？企业版预算？ | 前端技术选型 | MIT 核心功能足够，企业版按需 |
| Q12 | ~~国产 LLM 具体选型~~ | ~~LLM 适配层实现~~ | ✅ **v1.3 更新**：deepseek-v4-flash（主力）+ qwen3.6-plus（备选），通过厂家 API 服务使用，LLM 网关层统一管理 API Key 与成本控制 |
| Q13 | ~~微信机器人框架选型~~ | ~~渠道实现~~ | ✅ **v1.3 更新**：企业微信智能机器人（非原微信机器人），通过企业微信管理后台添加机器人应用，WebSocket 长连接接入，仅支持 6 种 template_card |
| Q14 | ~~业务系统 MCP 对接~~ | ~~Skills 开发工作量~~ | ✅ **已确认**：财务/超市/百货/人事/物业/CRM/储值卡（共 7 个）系统 API 不统一，需开发**统一业务系统适配层（Business System Adapter）**，将各系统 API 封装为标准 MCP Server 接口 |
| Q15 | ~~Agent 选择方式~~ | ~~前端交互、路由设计~~ | ✅ **v1.3 已确认**：前端不提供用户选择 Agent/运行时的功能，由系统后台 AgentRouter 自动路由（会话亲和性 → 关键词匹配 → 语义检索 → 默认 Agent 兜底） |
| Q16 | ~~配置目录格式~~ | ~~配置管理、运维~~ | ✅ **v1.3 已确认**：每个 Agent 一套配置目录（configs/agents/{agent_name}/ 下含 agent.yaml + skills/ + runtime/ + identity/ + system/ + memory/），支持文件系统和数据库双模式存储，热更新机制。✅ **v1.4 新增** memory/ 子目录（静态记忆 agent-memory.yaml + personality.md + facts/） |
| Q17 | ~~LLM 部署方式~~ | ~~架构选型、成本~~ | ✅ **v1.3 已确认**：通过购买厂家 API 服务使用 LLM，不自建 GPU 推理集群。需 LLM 网关层管理多厂家 API Key 与成本控制，通过内网出站代理访问厂家 API |
| Q18 | **出站代理高可用**：内网出站代理是否需要高可用方案？代理故障时 LLM 服务如何降级？ | LLM 网关设计 | 建议代理池 + 健康检查，代理故障时降级为缓存响应或提示用户稍后重试 |

---

## 附录 A：技术选型总结

| 层面 | 选型 | 理由 |
|------|------|------|
| H5 动态 UI | CopilotKit | Generative UI、AG-UI 协议、多框架支持 |
| 流式传输 | Vercel AI SDK (底层) | useChat Hook、Data Stream Protocol |
| 企业微信 H5 接入 | H5 嵌入工作台 + JS-SDK | CopilotKit 完整运行，JS-SDK 负责身份鉴权 |
| 企业微信 Bot 接入 | 智能机器人 + WebSocket 长连接 | 企业微信后台机器人应用，6 种 template_card 轻量交互 |
| Agent 智能路由 | AgentRouter（会话亲和性/关键词/语义检索/兜底） | 用户无需手动选择 Agent，后台自动路由 |
| LLM 服务方式 | 购买厂家 API 服务（不自建 GPU 集群） | deepseek-v4-flash + qwen3.6-plus，经 LLM 网关 + 出站代理 |
| LLM 网关 | 自研网关层（API Key 管理/Token 计费/配额/出站代理） | 统一管理多厂家 API Key，成本控制 |
| 配置管理 | 配置目录（文件系统 + 数据库双模式） | 配置即实例，热更新，configs/agents/{agent_name}/ 结构 |
| LLM 供应商 | deepseek-v4-flash（主力）+ qwen3.6-plus（备选） | 双模型策略：主力快速响应/Tool Calling，备选复杂推理/长上下文 |
| 业务系统适配层 | Business System Adapter → 标准 MCP Server | 统一封装 7 个业务系统 API（财务/超市/百货/人事/物业/CRM/储值卡） |
| Agent 运行时（初始） | OpenHarness | 港大HKUDS开源Python Agent框架，43+工具、MCP客户端、Skills系统、权限系统、Swarm多Agent |
| Agent 运行时（备选） | LangGraph / 自研 | 复杂编排 / 特定需求 |
| 后端语言 | Python + TypeScript | Python (Agent 逻辑) + TS (前端/网关) |
| 向量检索 | Qdrant（内网部署） | 670+ Skills 语义索引，本地部署 |
| Embedding 模型 | bge-small-zh-v1.5（内网部署） | 中文优化，避免外部 API 延迟 |
| 消息队列 | Redis Streams（内网部署） | 消息持久化、异步推送 |
| 数据库 | PostgreSQL（内网部署） | 配置存储（数据库模式）、会话持久化、审计日志 |
| 出站代理 | 内网出站代理（代理池） | LLM API 请求经代理访问厂家服务端点 |
| 部署方式 | Docker Compose（内网） | 100-200 并发规模，无需 K8s |

---

> **文档结束 — v1.3 已完成增量更新（企业微信 Bot 渠道 + AgentRouter 智能路由 + 配置目录结构 + LLM 网关 + 内网出站代理）。请评审后确认待确认问题（第8节），以便进入架构设计阶段。**
