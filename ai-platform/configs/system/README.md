# configs/system/ — 全局系统配置

## 目录用途

本目录存储全局系统级配置，包括 LLM 网关配置（多厂家 API Key 池、配额控制、出站代理、故障切换）、出站代理全局配置、企业微信 Bot 全局配置等。这些配置对所有 Agent 生效，各 Agent 的 `system/` 子目录可引用或覆盖。

## 目录结构

```
configs/system/
├── system.yaml                # 全局系统配置入口（汇总引用）
├── llm-gateway.yaml           # LLM 网关全局配置（providers/keys/quota/proxy/failover）
├── outbound-proxy.yaml        # 出站代理全局配置
└── wecom-bot.yaml             # 企业微信 Bot 全局配置（WebSocket 端点/鉴权）
```

## 配置文件说明

### system.yaml
全局系统配置入口文件，汇总引用其他子配置文件，并提供系统级参数（如 Embedding 服务地址、Qdrant 连接等）。

### llm-gateway.yaml
LLM 网关层配置，包括：
- **Providers**：DeepSeek（主力，deepseek-v4-flash）+ Qwen（备选，qwen3.6-plus）
- **API Key 池**：多 Key 轮转（round-robin），支持 Key 用量追踪与自动禁用
- **配额控制**：按用户/部门 Token 配额，超限限流与告警
- **出站代理**：所有 LLM API 请求通过内网出站代理访问外部 API
- **故障切换**：主力模型故障自动切换备选模型

### outbound-proxy.yaml
出站代理全局配置，包括代理节点列表、健康检查间隔、允许访问的域名白名单、审计日志开关。

### wecom-bot.yaml
企业微信智能机器人 Bot 渠道全局配置，包括 WebSocket 长连接端点、鉴权信息、心跳间隔等。

## 安全注意事项

1. **API Key 不硬编码**：使用 `secret://` 引用，实际 Key 值存储在加密的凭证托管服务中
2. **出站代理白名单**：仅允许 `api.deepseek.com` 和 `dashscope.aliyuncs.com` 两个域名
3. **审计日志**：所有出站请求记录审计日志（时间、目标域名、Token 用量）
4. **配置文件权限**：生产环境配置文件应设置严格文件系统权限（600）

## 热更新

系统配置变更通过 ConfigWatcher 监听。LLM 网关配置变更后，新的 API 请求使用新配置；当前活跃请求不受影响。
