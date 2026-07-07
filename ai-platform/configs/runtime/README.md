# configs/runtime/ — 全局运行时配置

## 目录用途

本目录存储 Agent 运行时的全局默认参数。每个 Agent 可以在自己的 `runtime/runtime.yaml` 中覆盖这些默认值。运行时配置决定了 Agent 的执行行为（最大步数、温度、Token 上限等）。

## 目录结构

```
configs/runtime/
└── runtime-defaults.yaml      # 运行时默认参数
```

## runtime-defaults.yaml 结构

```yaml
# 全局运行时默认配置
version: "1.0.0"

# 默认运行时类型
default_type: "openharness"    # openharness | custom | langgraph

# 默认运行参数
defaults:
  maxSteps: 20                 # Agent 最大执行步数
  temperature: 0.7             # LLM 温度参数
  maxTokens: 4096              # 单次响应最大 Token 数
  timeout: 120                 # Agent 执行超时（秒）
  retryCount: 3                # 失败重试次数
  retryDelay: 2                # 重试延迟（秒）

# 上下文压缩配置
contextCompression:
  enabled: true
  maxMessages: 50              # 超过此数量触发压缩
  summaryModel: "deepseek-v4-flash"
  preserveRecent: 10           # 保留最近 N 条消息不压缩

# 流式输出配置
streaming:
  enabled: true
  bufferSize: 1024             # 流式缓冲区大小（字节）
  flushInterval: 50            # 刷新间隔（毫秒）
```

## 运行时类型说明

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| `openharness` | 港大HKUDS开源Python Agent框架，43+工具、MCP客户端、Skills系统、Swarm多Agent | 通用对话、Tool Calling、快速响应 |
| `custom` | 自定义运行时 | 特殊逻辑定制 |
| `langgraph` | 基于 LangGraph 的图式运行时 | 复杂多步推理、状态机 |

## 热更新

运行时配置变更通过 ConfigWatcher 监听，下一会话自动生效。当前活跃会话不受影响。
