/**
 * 解析 Backend 写入 Redis 的 AgentEvent JSON（snake_case）为 Gateway AgentEvent。
 */

import type { AgentEvent, AgentEventType } from '../channels/ChannelCapability.js';

/** Backend AgentEvent JSON（snake_case 或 camelCase） */
interface RawBackendEvent {
  type: AgentEventType;
  content?: string;
  tool_name?: string;
  toolName?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  component?: string;
  props?: Record<string, unknown>;
  skill_id?: string;
  skillId?: string;
  detail?: Record<string, unknown>;
  error_code?: string;
  errorCode?: string;
  message?: string;
  errorMessage?: string;
  token_usage?: { prompt: number; completion: number; total: number };
  tokenUsage?: { prompt: number; completion: number; total: number };
}

/**
 * 将 Backend 事件 JSON 转为 Gateway AgentEvent。
 */
export function parseBackendAgentEvent(eventJson: string): AgentEvent {
  const raw = JSON.parse(eventJson) as RawBackendEvent;
  const event: AgentEvent = { type: raw.type };

  if (raw.content != null) {
    event.content = raw.content;
  }
  if (raw.tool_name != null || raw.toolName != null) {
    event.toolName = raw.toolName ?? raw.tool_name;
  }
  if (raw.args != null) {
    event.args = raw.args;
  }
  if (raw.result != null) {
    event.result = raw.result;
  }
  if (raw.component != null) {
    event.component = raw.component;
  }
  if (raw.props != null) {
    event.props = raw.props;
  }
  if (raw.skill_id != null || raw.skillId != null) {
    event.skillId = raw.skillId ?? raw.skill_id;
  }
  if (raw.detail != null) {
    event.detail = raw.detail;
  }
  if (raw.error_code != null || raw.errorCode != null) {
    event.errorCode = raw.errorCode ?? raw.error_code;
  }
  if (raw.message != null || raw.errorMessage != null) {
    event.errorMessage = raw.errorMessage ?? raw.message;
  }
  const usage = raw.tokenUsage ?? raw.token_usage;
  if (usage != null) {
    event.tokenUsage = usage;
  }

  return event;
}

/**
 * Backend/Gateway 渠道名 → EventTransformer ChannelType。
 */
export function toGatewayChannel(channel: string): 'h5' | 'wecom-h5' | 'wecom-bot' {
  if (channel === 'web' || channel === 'h5') {
    return 'h5';
  }
  if (channel === 'wecom_h5' || channel === 'wecom-h5') {
    return 'wecom-h5';
  }
  if (channel === 'wecom_bot' || channel === 'wecom-bot') {
    return 'wecom-bot';
  }
  return 'h5';
}
