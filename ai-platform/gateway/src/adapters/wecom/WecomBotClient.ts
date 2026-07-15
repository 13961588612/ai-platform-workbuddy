/**
 * WecomBotClient.ts — 企业微信智能机器人 WebSocket 长连接客户端
 *
 * 按官方协议（文档 path/101463）实现：
 * - 连接 wss://openws.work.weixin.qq.com
 * - 握手后发送 aibot_subscribe（bot_id + secret）鉴权
 * - 心跳：每 30s 发送 cmd=ping
 * - 自动重连（指数退避）
 * - 接收 aibot_msg_callback / aibot_event_callback
 * - 主动推送 aibot_send_msg
 *
 * @module adapters/wecom/WecomBotClient
 */

import { randomUUID } from 'node:crypto';
import WebSocket from 'ws';
import { logger } from '../../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** Bot WebSocket 客户端配置 */
export interface WecomBotClientConfig {
  /** 智能机器人 BotID */
  botId: string;
  /** 长连接专用 Secret */
  secret: string;
  /** WebSocket URL，默认官方 openws */
  wsUrl: string;
  /** 心跳间隔（秒），默认 30 */
  heartbeatIntervalSec: number;
  /** 心跳超时：连续 N 次未响应触发重连，默认 3 */
  heartbeatTimeoutCount: number;
  /** 最大重连次数，默认 10 */
  maxReconnectAttempts: number;
  /** 初始重连延迟（毫秒），默认 1000 */
  initialReconnectDelayMs: number;
  /** 最大重连延迟（毫秒），默认 30000 */
  maxReconnectDelayMs: number;
  /** 重连退避乘数，默认 2 */
  reconnectBackoffMultiplier: number;
  /** 订阅鉴权超时（毫秒），默认 10000 */
  subscribeTimeoutMs: number;
}

/** WebSocket 消息回调 */
export type MessageCallback = (message: BotWsMessage) => void;

/** 标准化后的 Bot 入站消息（由 aibot_msg_callback 解析） */
export interface BotWsMessage {
  /** 协议 cmd，如 aibot_msg_callback */
  cmd: string;
  /** 回调 req_id（回复时需透传） */
  reqId?: string;
  /** 消息类型（body.msgtype） */
  msgType: string;
  /** 消息 ID（body.msgid） */
  msgId?: string;
  /** 发送者 */
  from?: {
    userId: string;
    name?: string;
  };
  /** 文本内容 */
  content?: string;
  /** 群聊 chatid */
  chatId?: string;
  /** single | group */
  chatType?: string;
  /** 原始完整帧 */
  raw: Record<string, unknown>;
}

/** 连接状态 */
export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'subscribing'
  | 'connected'
  | 'heartbeating'
  | 'reconnecting';

type PendingRequest = {
  resolve: (value: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
};

// ============================================================================
// 默认配置
// ============================================================================

const DEFAULT_WS_URL = 'wss://openws.work.weixin.qq.com';

const DEFAULT_CONFIG: WecomBotClientConfig = {
  botId: '',
  secret: '',
  wsUrl: DEFAULT_WS_URL,
  heartbeatIntervalSec: 30,
  heartbeatTimeoutCount: 3,
  maxReconnectAttempts: 10,
  initialReconnectDelayMs: 1000,
  maxReconnectDelayMs: 30000,
  reconnectBackoffMultiplier: 2,
  subscribeTimeoutMs: 10000,
};

// ============================================================================
// WecomBotClient
// ============================================================================

/**
 * 企业微信智能机器人 WebSocket 客户端
 */
export class WecomBotClient {
  private readonly config: WecomBotClientConfig;
  private ws: WebSocket | null = null;
  private state: ConnectionState = 'disconnected';
  private heartbeatTimer: NodeJS.Timeout | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private missedHeartbeats = 0;
  private messageCallbacks: MessageCallback[] = [];
  private shouldRun = false;
  private readonly pending = new Map<string, PendingRequest>();

  constructor(config: Partial<WecomBotClientConfig> & { botId: string; secret: string }) {
    this.config = {
      ...DEFAULT_CONFIG,
      ...config,
      wsUrl: config.wsUrl?.trim() || DEFAULT_WS_URL,
    };
  }

  /**
   * 连接到企业微信并完成 aibot_subscribe 鉴权
   */
  async connect(): Promise<void> {
    if (this.state === 'connected' || this.state === 'heartbeating') {
      logger.warn('Bot WebSocket already connected');
      return;
    }

    if (!this.config.botId || !this.config.secret) {
      throw new Error('WECOM_BOT_ID and WECOM_BOT_SECRET are required for long connection');
    }

    this.shouldRun = true;
    this.state = 'connecting';

    await new Promise<void>((resolve, reject) => {
      logger.info(
        { wsUrl: this.config.wsUrl, botId: this.config.botId },
        'Connecting to Wecom Bot WebSocket',
      );

      this.ws = new WebSocket(this.config.wsUrl, {
        handshakeTimeout: 10000,
      });

      let settled = false;
      const settleOk = (): void => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      const settleErr = (error: Error): void => {
        if (!settled) {
          settled = true;
          reject(error);
        }
      };

      this.ws.on('open', () => {
        void this.subscribe()
          .then(() => {
            this.state = 'connected';
            this.reconnectAttempts = 0;
            this.missedHeartbeats = 0;
            this.startHeartbeat();
            logger.info({ botId: this.config.botId }, 'Wecom Bot subscribed successfully');
            settleOk();
          })
          .catch((error: unknown) => {
            const err = error instanceof Error ? error : new Error(String(error));
            logger.error({ error: err.message }, 'Wecom Bot subscribe failed');
            settleErr(err);
            this.handleDisconnect();
          });
      });

      this.ws.on('message', (data: WebSocket.RawData) => {
        this.handleMessage(data);
      });

      this.ws.on('close', (code: number, reason: Buffer) => {
        logger.warn(
          { code, reason: reason.toString() },
          'Wecom Bot WebSocket closed',
        );
        if (this.state === 'connecting' || this.state === 'subscribing') {
          settleErr(new Error(`WebSocket closed during connect: ${code}`));
        }
        this.handleDisconnect();
      });

      this.ws.on('error', (error: Error) => {
        logger.error({ error: error.message }, 'Wecom Bot WebSocket error');
        if (this.state === 'connecting' || this.state === 'subscribing') {
          settleErr(error);
        }
        this.handleDisconnect();
      });

      this.ws.on('unexpected-response', (_req: unknown, res: { statusCode?: number }) => {
        const error = new Error(`Unexpected response: ${res.statusCode}`);
        logger.error({ statusCode: res.statusCode }, 'WebSocket unexpected response');
        settleErr(error);
        this.handleDisconnect();
      });
    });
  }

  /**
   * 断开 WebSocket 连接
   */
  disconnect(): void {
    this.shouldRun = false;
    this.stopHeartbeat();
    this.clearReconnectTimer();
    this.rejectAllPending(new Error('WebSocket disconnected'));

    if (this.ws != null) {
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.close(1000, 'Normal closure');
      }
      this.ws.removeAllListeners();
      this.ws = null;
    }

    this.state = 'disconnected';
    logger.info('Wecom Bot WebSocket disconnected');
  }

  /**
   * 发送原始协议帧
   */
  async send(message: Record<string, unknown>): Promise<void> {
    if (this.ws == null || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not connected');
    }

    const data = JSON.stringify(message);
    return new Promise<void>((resolve, reject) => {
      this.ws!.send(data, (error: Error | undefined) => {
        if (error != null) {
          logger.error(
            { error: error.message },
            'Failed to send Bot WebSocket message',
          );
          reject(error);
        } else {
          resolve();
        }
      });
    });
  }

  /**
   * 流式回复（aibot_respond_msg）— 用于「思考中...」与最终回复
   *
   * 必须透传消息回调中的 req_id；同一条流式消息共用 streamId。
   */
  async respondStream(params: {
    reqId: string;
    streamId: string;
    content: string;
    finish: boolean;
  }): Promise<void> {
    const frame = {
      cmd: 'aibot_respond_msg',
      headers: { req_id: params.reqId },
      body: {
        msgtype: 'stream',
        stream: {
          id: params.streamId,
          finish: params.finish,
          content: params.content,
        },
      },
    };
    await this.send(frame);
    logger.info(
      {
        reqId: params.reqId,
        streamId: params.streamId,
        finish: params.finish,
        contentLen: params.content.length,
      },
      'aibot_respond_msg stream sent',
    );
  }

  /**
   * 主动推送 template_card（aibot_send_msg）
   */
  async sendCard(
    cardType: string,
    cardData: Record<string, unknown>,
    target: { userId?: string; chatId?: string },
  ): Promise<void> {
    const chatid = target.chatId ?? target.userId;
    if (chatid == null || chatid.length === 0) {
      throw new Error('sendCard requires chatId or userId');
    }

    const chatType = target.chatId != null ? 2 : 1;
    const reqId = randomUUID();
    const frame = {
      cmd: 'aibot_send_msg',
      headers: { req_id: reqId },
      body: {
        chatid,
        chat_type: chatType,
        msgtype: 'template_card',
        template_card: {
          card_type: cardType,
          ...cardData,
        },
      },
    };

    await this.send(frame);
    logger.info(
      { cardType, chatid, chatType, reqId },
      'template_card sent via aibot_send_msg',
    );
  }

  /**
   * 更新模板卡片（aibot_respond_update_msg）
   */
  async updateCard(
    responseCode: string,
    content: Record<string, unknown>,
  ): Promise<void> {
    const reqId = randomUUID();
    await this.send({
      cmd: 'aibot_respond_update_msg',
      headers: { req_id: reqId },
      body: {
        response_code: responseCode,
        ...content,
      },
    });

    logger.info({ responseCode, reqId }, 'Card updated via aibot_respond_update_msg');
  }

  onMessage(callback: MessageCallback): void {
    this.messageCallbacks.push(callback);
  }

  isConnected(): boolean {
    return this.state === 'connected' || this.state === 'heartbeating';
  }

  getState(): ConnectionState {
    return this.state;
  }

  // ========================================================================
  // 私有方法
  // ========================================================================

  private async subscribe(): Promise<void> {
    this.state = 'subscribing';
    const reqId = randomUUID();
    const frame = {
      cmd: 'aibot_subscribe',
      headers: { req_id: reqId },
      body: {
        bot_id: this.config.botId,
        secret: this.config.secret,
      },
    };

    const responsePromise = this.waitForResponse(reqId, this.config.subscribeTimeoutMs);
    await this.send(frame);
    const response = await responsePromise;
    const errcode = Number(response['errcode'] ?? -1);
    if (errcode !== 0) {
      throw new Error(
        `aibot_subscribe failed: errcode=${errcode}, errmsg=${String(response['errmsg'] ?? '')}`,
      );
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.state = 'heartbeating';

    const intervalMs = this.config.heartbeatIntervalSec * 1000;
    this.heartbeatTimer = setInterval(() => {
      void this.sendHeartbeat();
    }, intervalMs);

    logger.debug(
      { intervalSec: this.config.heartbeatIntervalSec },
      'Heartbeat started',
    );
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer != null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private async sendHeartbeat(): Promise<void> {
    if (this.ws == null || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }

    this.missedHeartbeats++;
    if (this.missedHeartbeats >= this.config.heartbeatTimeoutCount) {
      logger.warn(
        { missedHeartbeats: this.missedHeartbeats },
        'Heartbeat timeout, triggering reconnect',
      );
      this.handleDisconnect();
      return;
    }

    const reqId = randomUUID();
    try {
      const responsePromise = this.waitForResponse(reqId, this.config.subscribeTimeoutMs);
      await this.send({
        cmd: 'ping',
        headers: { req_id: reqId },
      });
      const response = await responsePromise;
      if (Number(response['errcode'] ?? -1) === 0) {
        this.missedHeartbeats = 0;
      }
      logger.debug({ missedHeartbeats: this.missedHeartbeats, reqId }, 'Heartbeat ping ok');
    } catch (error) {
      logger.warn(
        { error: error instanceof Error ? error.message : String(error) },
        'Heartbeat ping failed',
      );
    }
  }

  private handleMessage(data: WebSocket.RawData): void {
    try {
      const raw = JSON.parse(data.toString()) as Record<string, unknown>;
      const headers = (raw['headers'] as Record<string, unknown> | undefined) ?? {};
      const reqId = typeof headers['req_id'] === 'string' ? headers['req_id'] : undefined;

      // 订阅 / ping / send 的响应帧（带 errcode）
      if (reqId != null && this.pending.has(reqId) && raw['errcode'] != null) {
        this.resolvePending(reqId, raw);
        return;
      }

      const cmd = typeof raw['cmd'] === 'string' ? raw['cmd'] : '';

      // 心跳响应偶发无 errcode 匹配时也清零
      if (cmd === 'pong' || (reqId != null && this.pending.has(reqId) && cmd === '')) {
        if (reqId != null && this.pending.has(reqId)) {
          this.resolvePending(reqId, raw);
        }
        this.missedHeartbeats = 0;
        return;
      }

      if (cmd === 'aibot_msg_callback' || cmd === 'aibot_event_callback') {
        const message = this.parseCallback(raw, cmd, reqId);
        this.dispatchMessage(message);
        return;
      }

      // 兼容旧字段或未知帧：尽量解析后下发
      if (raw['msgType'] != null || raw['body'] != null) {
        const message = this.parseCallback(raw, cmd || 'unknown', reqId);
        this.dispatchMessage(message);
        return;
      }

      logger.debug({ cmd, keys: Object.keys(raw) }, 'Ignored Bot WebSocket frame');
    } catch (error) {
      logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to parse Bot WebSocket message',
      );
    }
  }

  private parseCallback(
    raw: Record<string, unknown>,
    cmd: string,
    reqId?: string,
  ): BotWsMessage {
    const body = (raw['body'] as Record<string, unknown> | undefined) ?? {};
    const fromRaw = body['from'] as Record<string, unknown> | undefined;
    const textRaw = body['text'] as Record<string, unknown> | undefined;
    const userId =
      (typeof fromRaw?.['userid'] === 'string' ? fromRaw['userid'] : undefined) ??
      (typeof fromRaw?.['userId'] === 'string' ? fromRaw['userId'] : undefined);

    const content =
      (typeof textRaw?.['content'] === 'string' ? textRaw['content'] : undefined) ??
      (typeof body['content'] === 'string' ? body['content'] : undefined) ??
      (typeof raw['content'] === 'string' ? raw['content'] : undefined);

    const msgType =
      (typeof body['msgtype'] === 'string' ? body['msgtype'] : undefined) ??
      (typeof raw['msgType'] === 'string' ? raw['msgType'] : undefined) ??
      'unknown';

    return {
      cmd,
      ...(reqId != null ? { reqId } : {}),
      msgType,
      ...(typeof body['msgid'] === 'string' ? { msgId: body['msgid'] } : {}),
      ...(userId != null ? { from: { userId } } : {}),
      ...(content != null ? { content } : {}),
      ...(typeof body['chatid'] === 'string' ? { chatId: body['chatid'] } : {}),
      ...(typeof body['chattype'] === 'string' ? { chatType: body['chattype'] } : {}),
      raw,
    };
  }

  private dispatchMessage(message: BotWsMessage): void {
    logger.debug(
      {
        cmd: message.cmd,
        msgType: message.msgType,
        from: message.from?.userId,
        chatId: message.chatId,
      },
      'Bot message received',
    );

    for (const callback of this.messageCallbacks) {
      try {
        callback(message);
      } catch (error) {
        logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Error in message callback',
        );
      }
    }
  }

  private waitForResponse(reqId: string, timeoutMs: number): Promise<Record<string, unknown>> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(reqId);
        reject(new Error(`Timed out waiting for req_id=${reqId}`));
      }, timeoutMs);

      this.pending.set(reqId, { resolve, reject, timer });
    });
  }

  private resolvePending(reqId: string, value: Record<string, unknown>): void {
    const pending = this.pending.get(reqId);
    if (pending == null) {
      return;
    }
    clearTimeout(pending.timer);
    this.pending.delete(reqId);
    pending.resolve(value);
  }

  private rejectAllPending(error: Error): void {
    for (const [reqId, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(reqId);
    }
  }

  private handleDisconnect(): void {
    this.stopHeartbeat();
    this.rejectAllPending(new Error('WebSocket disconnected'));

    if (this.ws != null) {
      this.ws.removeAllListeners();
      this.ws = null;
    }

    if (!this.shouldRun) {
      this.state = 'disconnected';
      return;
    }

    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();

    if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
      logger.error(
        { attempts: this.reconnectAttempts, max: this.config.maxReconnectAttempts },
        'Max reconnection attempts reached, giving up',
      );
      this.state = 'disconnected';
      return;
    }

    this.state = 'reconnecting';

    const delay = Math.min(
      this.config.initialReconnectDelayMs *
        Math.pow(this.config.reconnectBackoffMultiplier, this.reconnectAttempts),
      this.config.maxReconnectDelayMs,
    );

    this.reconnectAttempts++;

    logger.info(
      { attempt: this.reconnectAttempts, delayMs: delay },
      'Scheduling reconnect',
    );

    this.reconnectTimer = setTimeout(() => {
      this.connect().catch((error) => {
        logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Reconnection failed',
        );
        this.scheduleReconnect();
      });
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer != null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
