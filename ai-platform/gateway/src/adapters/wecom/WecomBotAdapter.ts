/**
 * WecomBotAdapter.ts — 企业微信智能机器人适配器
 *
 * 实现 Bot 渠道协议适配：
 * - WebSocket 长连接消息收发
 * - template_card 发送与更新
 * - AgentEvent → template_card 映射（委托 EventTransformer/BotEventMapper）
 * - 会话上下文管理
 *
 * @module adapters/wecom/WecomBotAdapter
 */

import { randomUUID } from 'node:crypto';
import type { AgentEvent, ChannelCapability } from '../../channels/ChannelCapability.js';
import { WecomBotCapability } from '../../channels/ChannelCapability.js';
import { WecomBotClient, type WecomBotClientConfig, type BotWsMessage } from './WecomBotClient.js';
import { WecomBotCardBuilder, type TemplateCard } from './WecomBotCardBuilder.js';
import type { InboundMessage } from '../../queue/redisStream.js';
import { logger } from '../../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 企业微信 Bot 适配器配置 */
export interface WecomBotAdapterConfig extends WecomBotClientConfig {
  /** 卡片来源名称 */
  sourceName: string;
  /** 卡片来源图标 URL */
  sourceIconUrl?: string;
}

// ============================================================================
// WecomBotAdapter
// ============================================================================

/**
 * 企业微信智能机器人适配器
 *
 * 实现 ChannelAdapter 接口，负责企业微信 Bot 渠道的消息收发。
 *
 * 能力：流式输出 ❌（需缓冲） | 自定义 UI ❌（仅卡片） | Markdown LIMITED | 消息长度 2048
 *
 * 消息流程：
 * 1. 接收 WebSocket 消息 → 解析为 InboundMessage
 * 2. 路由到 MessageRouter → Agent Core 处理
 * 3. 接收 AgentEvent 流 → EventTransformer 降级 → template_card
 * 4. 通过 WecomBotClient 发送 template_card
 */
export class WecomBotAdapter {
  private readonly wsClient: WecomBotClient;
  private readonly cardBuilder: WecomBotCardBuilder;
  private readonly capability: WecomBotCapability;
  private readonly sourceName: string;

  constructor(config: WecomBotAdapterConfig) {
    this.wsClient = new WecomBotClient(config);
    this.cardBuilder = new WecomBotCardBuilder(
      config.sourceName,
      config.sourceIconUrl,
    );
    this.capability = new WecomBotCapability();
    this.sourceName = config.sourceName;
  }

  /**
   * 获取渠道能力声明
   * @returns 渠道能力
   */
  getCapability(): ChannelCapability {
    return this.capability;
  }

  /**
   * 启动 Bot 适配器
   *
   * 连接企业微信 Bot WebSocket 服务，注册消息回调。
   *
   * @param onMessage - 消息回调（将入站消息传递给 MessageRouter）
   */
  async start(onMessage: (message: InboundMessage) => void): Promise<void> {
    await this.wsClient.connect();

    // 注册消息回调
    this.wsClient.onMessage((botMessage: BotWsMessage) => {
      const inbound = this.receive(botMessage);
      onMessage(inbound);
    });

    logger.info(
      { sourceName: this.sourceName },
      'WecomBotAdapter started',
    );
  }

  /**
   * 停止 Bot 适配器
   */
  stop(): void {
    this.wsClient.disconnect();
    logger.info('WecomBotAdapter stopped');
  }

  /**
   * 接收原始 Bot 消息，解析为标准入站消息
   *
   * @param botMessage - Bot WebSocket 消息
   * @returns 标准入站消息
   */
  receive(botMessage: BotWsMessage): InboundMessage {
    const userId = botMessage.from?.userId ?? 'unknown';
    const content = botMessage.content ?? '';

    // 生成 session_id（wecom-bot-{uuid}）
    const sessionId = `wecom-bot-${randomUUID()}`;

    return {
      id: botMessage.msgId ?? randomUUID(),
      sessionId,
      userId,
      channel: 'wecom-bot',
      content,
      messageType: 'text',
      traceId: randomUUID(),
      timestamp: botMessage.timestamp ?? new Date().toISOString(),
      metadata: {
        botMsgType: botMessage.msgType,
        from: botMessage.from,
        raw: botMessage.raw,
      },
    };
  }

  /**
   * 发送 AgentEvent 到 Bot 渠道
   *
   * Bot 渠道不支持流式输出和自定义 UI，
   * AgentEvent 需要通过 EventTransformer 降级为 template_card 后发送。
   *
   * 注意：此方法接收已转换的 template_card，实际转换由 EventTransformer 完成。
   *
   * @param card - template_card 消息
   * @param target - 目标用户
   */
  async sendCard(
    card: TemplateCard,
    target: { userId?: string; chatId?: string },
  ): Promise<void> {
    await this.wsClient.sendCard(card.card_type, card.data, target);

    logger.info(
      {
        cardType: card.card_type,
        target,
      },
      'template_card sent to Bot',
    );
  }

  /**
   * 发送 AgentEvent（统一接口，内部转换为卡片）
   *
   * @param event - Agent 事件
   * @param target - 目标用户
   * @param transformFn - 事件转换函数（由 EventTransformer 提供）
   */
  async send(
    event: AgentEvent,
    target: { userId?: string; chatId?: string },
    transformFn?: (event: AgentEvent) => TemplateCard | null,
  ): Promise<void> {
    // 如果提供了转换函数，先转换
    if (transformFn != null) {
      const card = transformFn(event);
      if (card != null) {
        await this.sendCard(card, target);
        return;
      }
    }

    // 无转换函数时，直接构建 text_notice（降级处理）
    if (event.type === 'text.delta' && event.content != null) {
      const card = this.cardBuilder.buildTextNotice('AI助手回复', event.content, {});
      await this.sendCard(card, target);
      return;
    }

    if (event.type === 'error') {
      const card = this.cardBuilder.buildTextNotice(
        '⚠️ 处理出错',
        `错误: ${event.errorMessage ?? '未知错误'}`,
        {},
      );
      await this.sendCard(card, target);
      return;
    }

    // 其他事件类型不做处理（由 EventTransformer 统一转换）
    logger.debug(
      { eventType: event.type },
      'Event skipped (no card generated)',
    );
  }

  /**
   * 更新已发送的卡片
   *
   * @param responseCode - 卡片响应码
   * @param content - 更新内容
   */
  async updateCard(
    responseCode: string,
    content: Record<string, unknown>,
  ): Promise<void> {
    await this.wsClient.updateCard(responseCode, content);
  }

  /**
   * 获取 WebSocket 客户端实例
   * @returns WebSocket 客户端
   */
  getWsClient(): WecomBotClient {
    return this.wsClient;
  }

  /**
   * 获取卡片构建器实例
   * @returns 卡片构建器
   */
  getCardBuilder(): WecomBotCardBuilder {
    return this.cardBuilder;
  }

  /**
   * 检查连接状态
   * @returns 是否已连接
   */
  isConnected(): boolean {
    return this.wsClient.isConnected();
  }
}
