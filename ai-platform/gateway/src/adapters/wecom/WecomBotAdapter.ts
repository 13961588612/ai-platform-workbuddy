/**
 * WecomBotAdapter.ts — 企业微信智能机器人适配器
 *
 * 实现 Bot 渠道协议适配：
 * - WebSocket 长连接消息收发
 * - 收到用户消息后立即 aibot_respond_msg「思考中...」
 * - Agent 完成后用同一 stream 推送最终回复
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

/** 企业微信 Bot 适配器配置 */
export interface WecomBotAdapterConfig extends WecomBotClientConfig {
  sourceName: string;
  sourceIconUrl?: string;
}

/** 进行中的流式回复上下文 */
interface PendingStream {
  reqId: string;
  streamId: string;
  buffer: string;
  /** Gateway 收到企微回调的时间戳（ms） */
  t0: number;
  /** 首次 text.delta 时间 */
  firstDeltaAt?: number;
  /** 上次推送到企微的时间（用于节流） */
  lastFlushAt: number;
  /** 推送到企微的次数（不含思考中） */
  flushCount: number;
}

const STREAM_FLUSH_INTERVAL_MS = 400;

/**
 * 企业微信智能机器人适配器
 */
export class WecomBotAdapter {
  private readonly wsClient: WecomBotClient;
  private readonly cardBuilder: WecomBotCardBuilder;
  private readonly capability: WecomBotCapability;
  private readonly sourceName: string;
  private readonly pendingBySession = new Map<string, PendingStream>();

  constructor(config: WecomBotAdapterConfig) {
    this.wsClient = new WecomBotClient(config);
    this.cardBuilder = new WecomBotCardBuilder(
      config.sourceName,
      config.sourceIconUrl,
    );
    this.capability = new WecomBotCapability();
    this.sourceName = config.sourceName;
  }

  getCapability(): ChannelCapability {
    return this.capability;
  }

  /**
   * 启动 Bot：连接后注册回调。
   * 文本消息会先回「思考中...」，再交给 MessageRouter。
   */
  async start(onMessage: (message: InboundMessage) => void | Promise<void>): Promise<void> {
    await this.wsClient.connect();

    this.wsClient.onMessage((botMessage: BotWsMessage) => {
      logger.info({ botMessage }, 'Wecom Bot raw botMessage');
      void this.handleInbound(botMessage, onMessage);
    });

    logger.info({ sourceName: this.sourceName }, 'WecomBotAdapter started');
  }

  stop(): void {
    this.wsClient.disconnect();
    this.pendingBySession.clear();
    logger.info('WecomBotAdapter stopped');
  }

  /**
   * 处理入站帧：打日志、过滤事件、立即回「思考中...」、再路由
   */
  private async handleInbound(
    botMessage: BotWsMessage,
    onMessage: (message: InboundMessage) => void | Promise<void>,
  ): Promise<void> {
    const t0 = Date.now();
    logger.info(
      {
        cmd: botMessage.cmd,
        msgType: botMessage.msgType,
        from: botMessage.from?.userId,
        chatId: botMessage.chatId,
        chatType: botMessage.chatType,
        reqId: botMessage.reqId,
        contentPreview: (botMessage.content ?? '').slice(0, 80),
        perfPhase: 'gw_recv',
      },
      'Wecom Bot inbound message',
    );

    // 进入会话等事件：不走 Agent（无正文）
    if (botMessage.cmd === 'aibot_event_callback') {
      logger.info({ msgType: botMessage.msgType }, 'Skip wecom event callback (no agent)');
      return;
    }

    if (botMessage.cmd !== 'aibot_msg_callback') {
      logger.info({ cmd: botMessage.cmd }, 'Skip non-msg wecom frame');
      return;
    }

    const content = (botMessage.content ?? '').trim();
    if (content.length === 0) {
      logger.info('Skip empty wecom text message');
      return;
    }

    if (botMessage.reqId == null || botMessage.reqId.length === 0) {
      logger.warn('Wecom msg_callback missing req_id, cannot stream reply');
      return;
    }

    const inbound = this.receive(botMessage, t0);
    const streamId = randomUUID();
    this.pendingBySession.set(inbound.sessionId, {
      reqId: botMessage.reqId,
      streamId,
      buffer: '',
      t0,
      lastFlushAt: 0,
      flushCount: 0,
    });

    const tThinking0 = Date.now();
    try {
      await this.wsClient.respondStream({
        reqId: botMessage.reqId,
        streamId,
        content: '思考中...',
        finish: false,
      });
      logger.info(
        {
          sessionId: inbound.sessionId,
          streamId,
          msThinking: Date.now() - tThinking0,
          msSinceRecv: Date.now() - t0,
          perfPhase: 'gw_thinking',
        },
        'Wecom Bot replied 思考中...',
      );
    } catch (error) {
      logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to send 思考中... stream',
      );
    }

    const tRoute0 = Date.now();
    try {
      await onMessage(inbound);
      logger.info(
        {
          sessionId: inbound.sessionId,
          traceId: inbound.traceId,
          msRoute: Date.now() - tRoute0,
          msSinceRecv: Date.now() - t0,
          perfPhase: 'gw_route',
        },
        'Wecom Bot routed to Redis',
      );
    } catch (error) {
      logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to route wecom inbound message',
      );
      await this.finishWithError(inbound.sessionId, '消息处理失败，请稍后重试');
    }
  }

  receive(botMessage: BotWsMessage, t0: number = Date.now()): InboundMessage {
    const channelUserId = botMessage.from?.userId ?? 'unknown';
    const content = botMessage.content ?? '';
    const sessionKey =
      botMessage.chatType === 'group' && botMessage.chatId != null
        ? botMessage.chatId
        : channelUserId;
    const sessionId = `wecom-bot-${sessionKey}`;

    // 企微回调偶发带手机号字段；没有则为空
    const rawBody =
      (botMessage.raw['body'] as Record<string, unknown> | undefined) ?? {};
    const rawFrom =
      (rawBody['from'] as Record<string, unknown> | undefined) ??
      (botMessage.raw['from'] as Record<string, unknown> | undefined) ??
      {};
    const userMobile =
      (typeof rawFrom['mobile'] === 'string' ? rawFrom['mobile'] : undefined) ??
      (typeof rawBody['mobile'] === 'string' ? rawBody['mobile'] : undefined) ??
      '';

    return {
      id: botMessage.msgId ?? randomUUID(),
      sessionId,
      // 暂无平台用户映射时，userId 先沿用渠道 userid
      userId: channelUserId,    // 平台侧统一用户标识
      channelUserId,
      ...(userMobile.length > 0 ? { userMobile } : {}),
      
      channel: 'wecom-bot',
      content,
      messageType: 'text',
      traceId: randomUUID(),
      timestamp: new Date().toISOString(),
      metadata: {
        botCmd: botMessage.cmd,
        botMsgType: botMessage.msgType,
        botReqId: botMessage.reqId,
        chatId: botMessage.chatId,
        chatType: botMessage.chatType,
        from: botMessage.from,
        raw: botMessage.raw,
        perfT0: t0,
      },
    };
  }

  /** Agent text.delta：累积；节流推送到企微（默认 400ms） */
  async onAgentTextDelta(sessionId: string, delta: string): Promise<void> {
    const pending = this.pendingBySession.get(sessionId);
    if (pending == null) {
      return;
    }
    pending.buffer += delta;
    if (pending.firstDeltaAt == null) {
      pending.firstDeltaAt = Date.now();
      logger.info(
        {
          sessionId,
          msSinceRecv: pending.firstDeltaAt - pending.t0,
          perfPhase: 'gw_first_delta',
        },
        'Wecom Bot first text.delta',
      );
    }

    const now = Date.now();
    if (
      pending.buffer.trim().length > 0 &&
      now - pending.lastFlushAt >= STREAM_FLUSH_INTERVAL_MS
    ) {
      const tFlush0 = Date.now();
      await this.wsClient.respondStream({
        reqId: pending.reqId,
        streamId: pending.streamId,
        content: pending.buffer,
        finish: false,
      });
      pending.lastFlushAt = now;
      pending.flushCount += 1;
      logger.debug(
        {
          sessionId,
          flushCount: pending.flushCount,
          msFlush: Date.now() - tFlush0,
          contentLen: pending.buffer.length,
          perfPhase: 'gw_stream_flush',
        },
        'Wecom Bot stream flushed',
      );
    }
  }

  /** Agent 出错：结束流式消息 */
  async onAgentError(sessionId: string, message: string): Promise<void> {
    await this.finishWithError(sessionId, message || '处理出错');
  }

  /** Agent done：结束流式消息 */
  async onAgentDone(sessionId: string): Promise<void> {
    const pending = this.pendingBySession.get(sessionId);
    if (pending == null) {
      return;
    }
    const content =
      pending.buffer.trim().length > 0 ? pending.buffer : '（无回复内容）';
    const tFinish0 = Date.now();
    try {
      await this.wsClient.respondStream({
        reqId: pending.reqId,
        streamId: pending.streamId,
        content,
        finish: true,
      });
      const now = Date.now();
      logger.info(
        {
          sessionId,
          contentLen: content.length,
          flushCount: pending.flushCount,
          msFinishSend: now - tFinish0,
          msFirstDelta: pending.firstDeltaAt != null ? pending.firstDeltaAt - pending.t0 : null,
          msTotal: now - pending.t0,
          perfPhase: 'gw_done',
        },
        'Wecom Bot stream finished (perf summary)',
      );
    } finally {
      this.pendingBySession.delete(sessionId);
    }
  }

  private async finishWithError(sessionId: string, message: string): Promise<void> {
    const pending = this.pendingBySession.get(sessionId);
    if (pending == null) {
      return;
    }
    try {
      await this.wsClient.respondStream({
        reqId: pending.reqId,
        streamId: pending.streamId,
        content: `⚠️ ${message}`,
        finish: true,
      });
      logger.info(
        {
          sessionId,
          msTotal: Date.now() - pending.t0,
          perfPhase: 'gw_error_done',
        },
        'Wecom Bot stream finished with error',
      );
    } finally {
      this.pendingBySession.delete(sessionId);
    }
  }

  async sendCard(
    card: TemplateCard,
    target: { userId?: string; chatId?: string },
  ): Promise<void> {
    await this.wsClient.sendCard(card.card_type, card.data, target);
    logger.info({ cardType: card.card_type, target }, 'template_card sent to Bot');
  }

  async send(
    event: AgentEvent,
    target: { userId?: string; chatId?: string },
    transformFn?: (event: AgentEvent) => TemplateCard | null,
  ): Promise<void> {
    if (transformFn != null) {
      const card = transformFn(event);
      if (card != null) {
        await this.sendCard(card, target);
        return;
      }
    }

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

    logger.debug({ eventType: event.type }, 'Event skipped (no card generated)');
  }

  async updateCard(
    responseCode: string,
    content: Record<string, unknown>,
  ): Promise<void> {
    await this.wsClient.updateCard(responseCode, content);
  }

  getWsClient(): WecomBotClient {
    return this.wsClient;
  }

  getCardBuilder(): WecomBotCardBuilder {
    return this.cardBuilder;
  }

  isConnected(): boolean {
    return this.wsClient.isConnected();
  }
}
