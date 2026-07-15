/**
 * MessageRouter.ts — 消息路由（渠道 → Agent Core）
 *
 * 接收渠道适配器解析后的 InboundMessage，路由到对应的 Agent Core 处理队列。
 * 通过 Redis Streams 实现异步消息传递。
 *
 * @module router/MessageRouter
 */

import type { Redis } from 'ioredis';
import { randomUUID } from 'node:crypto';
import {
  StreamProducer,
  type InboundMessage,
} from '../queue/redisStream.js';
import { ChannelResolver } from './ChannelResolver.js';
import { logger } from '../middleware/logger.js';
import type { ChannelType } from '../channels/ChannelCapability.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 路由结果 */
export interface RouteResult {
  /** 消息 ID */
  messageId: string;
  /** 会话 ID */
  sessionId: string;
  /** 目标 Stream 键名 */
  streamKey: string;
  /** Agent ID（路由后填充，若为 null 表示待路由） */
  agentId: string | null;
  /** 渠道类型 */
  channel: string;
  /** 路由时间戳 */
  timestamp: string;
}

/** 会话上下文（用于 AgentRouter 路由决策） */
export interface SessionContext {
  /** 会话 ID */
  sessionId: string;
  /** 用户 ID */
  userId: string;
  /** 渠道类型 */
  channel: string;
  /** 是否已有绑定的 Agent */
  hasBoundAgent: boolean;
  /** 已绑定的 Agent ID（如有） */
  boundAgentId?: string;
}

// ============================================================================
// MessageRouter
// ============================================================================

/**
 * 消息路由器
 *
 * 负责将渠道适配器解析后的入站消息路由到 Agent Core 处理队列。
 *
 * 路由流程：
 * 1. 接收 InboundMessage
 * 2. 解析渠道来源
 * 3. 查询会话绑定（session → agent 映射）
 * 4. 生成 Redis Stream 键名
 * 5. 将消息写入 Stream
 * 6. 返回路由结果
 *
 * 注意：AgentRouter 的 4 级策略链路由在 Agent Core 端实现，
 * Gateway 仅负责消息投递到正确的 Stream。
 */
export class MessageRouter {
  private readonly producer: StreamProducer;
  private readonly redis: Redis;

  constructor(redis: Redis) {
    this.redis = redis;
    this.producer = new StreamProducer(redis);
  }

  /**
   * 路由入站消息到 Agent Core 处理队列
   *
   * @param message - 入站消息
   * @returns 路由结果
   */
  async route(message: InboundMessage): Promise<RouteResult> {
    // 如果消息中已有 agentId，直接路由到对应 Agent 的 Stream
    let agentId = message.agentId ?? null;
    let streamKey: string;

    if (agentId != null) {
      // 已知目标 Agent，直接路由
      streamKey = StreamProducer.getAgentStreamKey(agentId);
    } else {
      // 未知目标 Agent，路由到渠道入站队列，由 AgentRouter 决策
      streamKey = StreamProducer.getInboundStreamKey(message.channel);
    }

    // 尝试从会话绑定中获取 Agent ID
    if (agentId == null) {
      const boundAgentId = await this.resolveAgent(message.channel, message.userId, message.sessionId);
      if (boundAgentId != null) {
        agentId = boundAgentId;
        streamKey = StreamProducer.getAgentStreamKey(agentId);
        // 更新消息中的 agentId
        message.agentId = agentId;
      }
    }

    // 写入 Redis Stream
    await this.producer.produce(streamKey, message);

    const result: RouteResult = {
      messageId: message.id,
      sessionId: message.sessionId,
      streamKey,
      agentId,
      channel: message.channel,
      timestamp: new Date().toISOString(),
    };

    logger.info(
      {
        messageId: message.id,
        sessionId: message.sessionId,
        channel: message.channel,
        agentId,
        streamKey,
      },
      'Message routed to Agent Core',
    );

    return result;
  }

  /**
   * 解析 Agent（会话亲和性路由）
   *
   * 查询 Redis 中 session → agent 的绑定关系。
   * 如果有绑定，返回绑定的 Agent ID；否则返回 null（由 AgentRouter 决策）。
   *
   * @param channel - 渠道类型
   * @param userId - 用户 ID
   * @param sessionId - 会话 ID
   * @returns 绑定的 Agent ID 或 null
   */
  async resolveAgent(
    channel: string,
    userId: string,
    sessionId: string,
  ): Promise<string | null> {
    // 查询会话绑定
    const bindingKey = `session:${sessionId}:agent_binding`;
    const boundAgentId = await this.redis.get(bindingKey);

    if (boundAgentId != null) {
      // 验证绑定的 Agent 是否仍然有效
      const agentEnabledKey = `agent:${boundAgentId}:enabled`;
      const isEnabled = await this.redis.get(agentEnabledKey);

      if (isEnabled === '1' || isEnabled == null) {
        logger.debug(
          { sessionId, boundAgentId },
          'Session bound to agent (session affinity)',
        );
        return boundAgentId;
      }

      // Agent 已禁用，清除绑定
      await this.redis.del(bindingKey);
      logger.info(
        { sessionId, boundAgentId },
        'Session binding cleared (agent disabled)',
      );
    }

    return null;
  }

  /**
   * 绑定会话到 Agent
   *
   * AgentRouter 决策后，将会话绑定到选中的 Agent。
   *
   * @param sessionId - 会话 ID
   * @param agentId - Agent ID
   * @param ttlSeconds - 绑定 TTL（秒），默认 86400（24h）
   */
  async bindSessionToAgent(
    sessionId: string,
    agentId: string,
    ttlSeconds = 86400,
  ): Promise<void> {
    const bindingKey = `session:${sessionId}:agent_binding`;
    await this.redis.set(bindingKey, agentId, 'EX', ttlSeconds);

    logger.info(
      { sessionId, agentId, ttlSeconds },
      'Session bound to agent',
    );
  }

  /**
   * 获取会话上下文
   *
   * @param sessionId - 会话 ID
   * @param userId - 用户 ID
   * @param channel - 渠道类型
   * @returns 会话上下文
   */
  async getSessionContext(
    sessionId: string,
    userId: string,
    channel: string,
  ): Promise<SessionContext> {
    const bindingKey = `session:${sessionId}:agent_binding`;
    const boundAgentId = await this.redis.get(bindingKey);

    return {
      sessionId,
      userId,
      channel,
      hasBoundAgent: boundAgentId != null,
      ...(boundAgentId != null ? { boundAgentId } : {}),
    };
  }

  /**
   * 构造入站消息
   *
   * 从渠道适配器接收的原始消息构造标准 InboundMessage。
   *
   * @param params - 消息参数
   * @returns 标准入站消息
   */
  static createInboundMessage(params: {
    userId: string;
    channel: string;
    content: string;
    messageType?: string;
    sessionId?: string;
    agentId?: string;
    traceId?: string;
    userMobile?: string;
    channelUserId?: string;
    metadata?: Record<string, unknown>;
  }): InboundMessage {
    // 生成 session_id（如果未提供）
    let sessionId = params.sessionId;
    if (sessionId == null || sessionId.length === 0) {
      const source = ChannelResolver.getDefaultSource(
        params.channel as ChannelType,
      );
      sessionId = ChannelResolver.generateSessionId(source);
    }

    return {
      id: randomUUID(),
      sessionId,
      userId: params.userId,
      ...(params.userMobile != null && params.userMobile.length > 0
        ? { userMobile: params.userMobile }
        : {}),
      channelUserId: params.channelUserId ?? params.userId,
      channel: params.channel,
      ...(params.agentId != null ? { agentId: params.agentId } : {}),
      content: params.content,
      messageType: params.messageType ?? 'text',
      traceId: params.traceId ?? randomUUID(),
      timestamp: new Date().toISOString(),
      ...(params.metadata != null ? { metadata: params.metadata } : {}),
    };
  }
}
