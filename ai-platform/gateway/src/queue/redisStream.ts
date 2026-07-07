/**
 * redisStream.ts — Redis Streams 生产/消费
 *
 * 实现 Gateway 与 Agent Core 之间的异步消息传递：
 * - 生产者：将渠道入站消息写入 Redis Stream
 * - 消费者：消费 Agent Core 返回的 AgentEvent 流
 *
 * Stream 命名规范：
 * - 入站消息流：stream:inbound:{channel}
 * - Agent 事件流：stream:agent:{agentId}
 *
 * @module queue/redisStream
 */

import type { Redis } from 'ioredis';
import { logger } from '../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 入站消息结构 */
export interface InboundMessage {
  /** 消息 ID（UUID） */
  id: string;
  /** 会话 ID */
  sessionId: string;
  /** 用户 ID */
  userId: string;
  /** 渠道类型 */
  channel: string;
  /** Agent ID（可选，路由后填充） */
  agentId?: string;
  /** 消息内容 */
  content: string;
  /** 消息类型 */
  messageType: string;
  /** 追踪 ID */
  traceId: string;
  /** 时间戳（ISO 8601） */
  timestamp: string;
  /** 元数据 */
  metadata?: Record<string, unknown>;
  /** AgentEvent 类型（出站事件流） */
  eventType?: string;
  /** AgentEvent JSON（出站事件流，Backend snake_case） */
  eventJson?: string;
}

/** Stream 消息字段 */
export type StreamMessage = Record<string, string>;

/** 消费回调类型 */
export type ConsumeCallback = (message: InboundMessage) => Promise<void>;

// ============================================================================
// 常量
// ============================================================================

const MAX_STREAM_LENGTH = 10000;
const CONSUMER_BLOCK_MS = 5000;

// ============================================================================
// Stream 生产者
// ============================================================================

/**
 * Redis Stream 生产者
 *
 * 将渠道入站消息写入 Redis Stream，供 Agent Core 异步消费。
 */
export class StreamProducer {
  private readonly redis: Redis;

  constructor(redis: Redis) {
    this.redis = redis;
  }

  /**
   * 将入站消息写入 Stream
   *
   * @param streamKey - Stream 键名（如 stream:agent:{agentId}）
   * @param message - 入站消息
   * @returns Stream 消息 ID
   */
  async produce(streamKey: string, message: InboundMessage): Promise<string> {
    const fields: StreamMessage = {
      id: message.id,
      sessionId: message.sessionId,
      userId: message.userId,
      channel: message.channel,
      content: message.content,
      messageType: message.messageType,
      traceId: message.traceId,
      timestamp: message.timestamp,
      ...(message.agentId != null ? { agentId: message.agentId } : {}),
      ...(message.metadata != null
        ? { metadata: JSON.stringify(message.metadata) }
        : {}),
    };

    const messageId = await this.redis.xadd(
      streamKey,
      'MAXLEN', '~', MAX_STREAM_LENGTH.toString(),
      '*',
      ...Object.entries(fields).flat(),
    );

    if (messageId == null) {
      throw new Error(`Failed to produce message to stream: ${streamKey}`);
    }

    logger.debug(
      { streamKey, messageId, sessionId: message.sessionId },
      'Message produced to stream',
    );

    return messageId;
  }

  /**
   * 构造入站消息 Stream 键名
   * @param channel - 渠道类型
   * @returns Stream 键名
   */
  static getInboundStreamKey(channel: string): string {
    return `stream:inbound:${channel}`;
  }

  /**
   * 构造 Agent 事件 Stream 键名
   * @param agentId - Agent ID
   * @returns Stream 键名
   */
  static getAgentStreamKey(agentId: string): string {
    return `stream:agent:${agentId}`;
  }
}

// ============================================================================
// Stream 消费者
// ============================================================================

/**
 * Redis Stream 消费者
 *
 * 阻塞式消费 Redis Stream 中的消息，支持消费者组。
 */
export class StreamConsumer {
  private readonly redis: Redis;
  private readonly groupName: string;
  private readonly consumerName: string;
  private running = false;
  private currentTimeout: NodeJS.Timeout | undefined;

  constructor(
    redis: Redis,
    groupName = 'gateway-group',
    consumerName = `gateway-${process.pid}`,
  ) {
    this.redis = redis;
    this.groupName = groupName;
    this.consumerName = consumerName;
  }

  /**
   * 启动消费循环
   *
   * @param streamKey - Stream 键名
   * @param callback - 消费回调
   */
  async start(streamKey: string, callback: ConsumeCallback): Promise<void> {
    this.running = true;

    // 确保消费者组存在
    await this.ensureConsumerGroup(streamKey);

    logger.info(
      { streamKey, groupName: this.groupName, consumerName: this.consumerName },
      'Starting stream consumer',
    );

    // 启动消费循环
    this.consumeLoop(streamKey, callback).catch((error) => {
      logger.error(
        { error: error instanceof Error ? error.message : String(error), streamKey },
        'Consumer loop error',
      );
    });
  }

  /**
   * 停止消费
   */
  stop(): void {
    this.running = false;
    if (this.currentTimeout != null) {
      clearTimeout(this.currentTimeout);
      this.currentTimeout = undefined;
    }
    logger.info('Stream consumer stopped');
  }

  /**
   * 确保消费者组存在
   */
  private async ensureConsumerGroup(streamKey: string): Promise<void> {
    try {
      await this.redis.xgroup(
        'CREATE',
        streamKey,
        this.groupName,
        '$',
        'MKSTREAM',
      );
      logger.info(
        { streamKey, groupName: this.groupName },
        'Consumer group created',
      );
    } catch (error) {
      // 消费者组已存在是正常情况
      const message = error instanceof Error ? error.message : String(error);
      if (!message.includes('BUSYGROUP')) {
        throw error;
      }
    }
  }

  /**
   * 消费循环
   */
  private async consumeLoop(
    streamKey: string,
    callback: ConsumeCallback,
  ): Promise<void> {
    while (this.running) {
      try {
        // 阻塞式读取新消息
        const result = await this.redis.xreadgroup(
          'GROUP',
          this.groupName,
          this.consumerName,
          'COUNT', '1',
          'BLOCK', CONSUMER_BLOCK_MS.toString(),
          'STREAMS',
          streamKey,
          '>',
        );

        if (result == null || result.length === 0) {
          continue;
        }

        for (const [, messages] of result) {
          for (const [messageId, fields] of messages) {
            await this.processMessage(
              streamKey,
              messageId,
              fields,
              callback,
            );
          }
        }
      } catch (error) {
        logger.error(
          {
            error: error instanceof Error ? error.message : String(error),
            streamKey,
          },
          'Error consuming message',
        );
        // 短暂等待后重试
        await new Promise<void>((resolve) => {
          this.currentTimeout = setTimeout(resolve, 1000);
        });
      }
    }
  }

  /**
   * 处理单条消息
   */
  private async processMessage(
    streamKey: string,
    messageId: string,
    fields: string[],
    callback: ConsumeCallback,
  ): Promise<void> {
    try {
      // 将字段数组转换为对象
      const fieldObj: Record<string, string> = {};
      for (let i = 0; i < fields.length; i += 2) {
        const key = fields[i] ?? `field_${i}`;
        const value = fields[i + 1] ?? '';
        fieldObj[key] = value;
      }

      // 构造 InboundMessage
      const message: InboundMessage = {
        id: fieldObj['id'] ?? messageId,
        sessionId: fieldObj['sessionId'] ?? '',
        userId: fieldObj['userId'] ?? '',
        channel: fieldObj['channel'] ?? '',
        content: fieldObj['content'] ?? '',
        messageType: fieldObj['messageType'] ?? 'text',
        traceId: fieldObj['traceId'] ?? '',
        timestamp: fieldObj['timestamp'] ?? new Date().toISOString(),
        ...(fieldObj['agentId'] != null ? { agentId: fieldObj['agentId'] } : {}),
        ...(fieldObj['metadata'] != null
          ? { metadata: JSON.parse(fieldObj['metadata']) as Record<string, unknown> }
          : {}),
        ...(fieldObj['event'] != null ? { eventJson: fieldObj['event'] } : {}),
        ...(fieldObj['eventType'] != null ? { eventType: fieldObj['eventType'] } : {}),
      };

      // 执行回调
      await callback(message);

      // 确认消息
      await this.redis.xack(streamKey, this.groupName, messageId);

      logger.debug(
        { streamKey, messageId, sessionId: message.sessionId },
        'Message consumed and acknowledged',
      );
    } catch (error) {
      logger.error(
        {
          error: error instanceof Error ? error.message : String(error),
          streamKey,
          messageId,
        },
        'Error processing message',
      );
      // 不确认消息，让其在 PEL 中稍后重试
    }
  }
}

// ============================================================================
// Stream 管理
// ============================================================================

/**
 * 获取 Stream 信息
 * @param redis - Redis 客户端
 * @param streamKey - Stream 键名
 * @returns Stream 信息
 */
export async function getStreamInfo(
  redis: Redis,
  streamKey: string,
): Promise<{
  length: number;
  groups: number;
  pending: number;
  lastEntryId: string;
}> {
  const info = (await redis.xinfo('STREAM', streamKey)) as unknown[];
  const infoObj: Record<string, unknown> = {};
  for (let i = 0; i < info.length; i += 2) {
    const key = info[i] as string;
    infoObj[key] = info[i + 1];
  }

  return {
    length: (infoObj['length'] as number) ?? 0,
    groups: (infoObj['groups'] as number) ?? 0,
    pending: (infoObj['pending'] as number) ?? 0,
    lastEntryId: (infoObj['last-entry'] as string) ?? '0-0',
  };
}

/**
 * 清理过期 Stream 消息
 * @param redis - Redis 客户端
 * @param streamKey - Stream 键名
 * @param maxLength - 最大保留长度
 */
export async function trimStream(
  redis: Redis,
  streamKey: string,
  maxLength = MAX_STREAM_LENGTH,
): Promise<number> {
  const trimmed = await redis.xtrim(streamKey, 'MAXLEN', '~', maxLength.toString());
  if (trimmed > 0) {
    logger.info(
      { streamKey, trimmed, maxLength },
      'Stream trimmed',
    );
  }
  return trimmed;
}
