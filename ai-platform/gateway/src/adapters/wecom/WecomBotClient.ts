/**
 * WecomBotClient.ts — 企业微信 Bot WebSocket 客户端
 *
 * 实现企业微信智能机器人 WebSocket 长连接：
 * - 长连接维持
 * - 心跳保活（30s 间隔）
 * - 自动重连（指数退避：1s → 2s → 4s → 8s → 16s → 30s 上限）
 * - 消息编解码（JSON 格式）
 * - 来源校验
 *
 * @module adapters/wecom/WecomBotClient
 */

import WebSocket from 'ws';
import { logger } from '../../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** Bot WebSocket 客户端配置 */
export interface WecomBotClientConfig {
  /** WebSocket 连接 URL */
  wsUrl: string;
  /** 鉴权 Token */
  authToken: string;
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
}

/** WebSocket 消息回调 */
export type MessageCallback = (message: BotWsMessage) => void;

/** Bot WebSocket 消息 */
export interface BotWsMessage {
  /** 消息类型 */
  msgType: string;
  /** 消息 ID */
  msgId?: string;
  /** 发送者 */
  from?: {
    userId: string;
    name?: string;
  };
  /** 消息内容 */
  content?: string;
  /** 消息时间戳 */
  timestamp?: string;
  /** 原始数据 */
  raw: Record<string, unknown>;
}

/** 连接状态 */
export type ConnectionState =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'heartbeating'
  | 'reconnecting';

// ============================================================================
// 默认配置
// ============================================================================

const DEFAULT_CONFIG: WecomBotClientConfig = {
  wsUrl: '',
  authToken: '',
  heartbeatIntervalSec: 30,
  heartbeatTimeoutCount: 3,
  maxReconnectAttempts: 10,
  initialReconnectDelayMs: 1000,
  maxReconnectDelayMs: 30000,
  reconnectBackoffMultiplier: 2,
};

// ============================================================================
// WecomBotClient
// ============================================================================

/**
 * 企业微信 Bot WebSocket 客户端
 *
 * 维持与企业微信智能机器人平台的 WebSocket 长连接，
 * 负责消息收发、心跳保活和自动重连。
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

  constructor(config: Partial<WecomBotClientConfig> & { wsUrl: string; authToken: string }) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * 连接到企业微信 Bot WebSocket 服务
   *
   * @returns 连接成功 resolve，连接失败 reject
   */
  async connect(): Promise<void> {
    if (this.state === 'connected' || this.state === 'heartbeating') {
      logger.warn('Bot WebSocket already connected');
      return;
    }

    this.shouldRun = true;
    this.state = 'connecting';

    return new Promise<void>((resolve, reject) => {
      logger.info(
        { wsUrl: this.config.wsUrl },
        'Connecting to Wecom Bot WebSocket',
      );

      // 构造 WebSocket URL（带鉴权参数）
      const url = `${this.config.wsUrl}?token=${encodeURIComponent(this.config.authToken)}`;

      this.ws = new WebSocket(url, {
        handshakeTimeout: 10000,
      });

      this.ws.on('open', () => {
        logger.info('Wecom Bot WebSocket connected');
        this.state = 'connected';
        this.reconnectAttempts = 0;
        this.missedHeartbeats = 0;
        this.startHeartbeat();
        resolve();
      });

      this.ws.on('message', (data: WebSocket.RawData) => {
        this.handleMessage(data);
      });

      this.ws.on('pong', () => {
        this.missedHeartbeats = 0;
      });

      this.ws.on('close', (code: number, reason: Buffer) => {
        logger.warn(
          { code, reason: reason.toString() },
          'Wecom Bot WebSocket closed',
        );
        this.handleDisconnect();
      });

      this.ws.on('error', (error: Error) => {
        logger.error(
          { error: error.message },
          'Wecom Bot WebSocket error',
        );
        if (this.state === 'connecting') {
          reject(error);
        }
        this.handleDisconnect();
      });

      this.ws.on('unexpected-response', (_req, res) => {
        const error = new Error(`Unexpected response: ${res.statusCode}`);
        logger.error({ statusCode: res.statusCode }, 'WebSocket unexpected response');
        if (this.state === 'connecting') {
          reject(error);
        }
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
   * 发送消息到企业微信 Bot 平台
   *
   * @param message - 待发送的消息对象
   */
  async send(message: Record<string, unknown>): Promise<void> {
    if (this.ws == null || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not connected');
    }

    const data = JSON.stringify(message);
    return new Promise<void>((resolve, reject) => {
      this.ws!.send(data, (error) => {
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
   * 发送 template_card 消息
   *
   * @param cardType - 卡片类型
   * @param cardData - 卡片数据
   * @param target - 目标用户/群
   */
  async sendCard(
    cardType: string,
    cardData: Record<string, unknown>,
    target: { userId?: string; chatId?: string },
  ): Promise<void> {
    const message = {
      msgType: 'template_card',
      cardType,
      cardData,
      target,
      timestamp: new Date().toISOString(),
    };
    await this.send(message);

    logger.info(
      { cardType, target },
      'template_card sent via Bot WebSocket',
    );
  }

  /**
   * 更新已发送的卡片（通过 responseCode）
   *
   * @param responseCode - 卡片响应码
   * @param content - 更新内容
   */
  async updateCard(
    responseCode: string,
    content: Record<string, unknown>,
  ): Promise<void> {
    const message = {
      msgType: 'update_template_card',
      responseCode,
      content,
      timestamp: new Date().toISOString(),
    };
    await this.send(message);

    logger.info(
      { responseCode },
      'Card updated via Bot WebSocket',
    );
  }

  /**
   * 注册消息回调
   *
   * @param callback - 消息回调函数
   */
  onMessage(callback: MessageCallback): void {
    this.messageCallbacks.push(callback);
  }

  /**
   * 检查连接状态
   * @returns 是否已连接
   */
  isConnected(): boolean {
    return this.state === 'connected' || this.state === 'heartbeating';
  }

  /**
   * 获取当前连接状态
   * @returns 连接状态
   */
  getState(): ConnectionState {
    return this.state;
  }

  // ========================================================================
  // 私有方法
  // ========================================================================

  /**
   * 启动心跳定时器
   */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.state = 'heartbeating';

    const intervalMs = this.config.heartbeatIntervalSec * 1000;
    this.heartbeatTimer = setInterval(() => {
      this.sendHeartbeat();
    }, intervalMs);

    logger.debug(
      { intervalSec: this.config.heartbeatIntervalSec },
      'Heartbeat started',
    );
  }

  /**
   * 停止心跳定时器
   */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer != null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /**
   * 发送心跳
   */
  private sendHeartbeat(): void {
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

    // 发送 ping
    this.ws.ping();

    // 也可以发送业务心跳消息
    const heartbeatMsg = {
      msgType: 'heartbeat',
      timestamp: new Date().toISOString(),
    };
    this.ws.send(JSON.stringify(heartbeatMsg), (error) => {
      if (error != null) {
        logger.warn(
          { error: error.message },
          'Heartbeat send failed',
        );
      }
    });

    logger.debug(
      { missedHeartbeats: this.missedHeartbeats },
      'Heartbeat sent',
    );
  }

  /**
   * 处理接收到的消息
   */
  private handleMessage(data: WebSocket.RawData): void {
    try {
      const raw = JSON.parse(data.toString()) as Record<string, unknown>;

      // 心跳响应
      if (raw['msgType'] === 'heartbeat_ack' || raw['msgType'] === 'pong') {
        this.missedHeartbeats = 0;
        return;
      }

      // 构造标准消息
      const message: BotWsMessage = {
        msgType: (raw['msgType'] as string) ?? 'unknown',
        ...(raw['msgId'] != null ? { msgId: raw['msgId'] as string } : {}),
        ...(raw['from'] != null ? { from: raw['from'] as { userId: string; name?: string } } : {}),
        ...(raw['content'] != null ? { content: raw['content'] as string } : {}),
        ...(raw['timestamp'] != null ? { timestamp: raw['timestamp'] as string } : {}),
        raw,
      };

      // 验证消息来源
      if (!this.verifyMessageSource(raw)) {
        logger.warn(
          { msgType: message.msgType },
          'Message source verification failed, ignoring',
        );
        return;
      }

      logger.debug(
        { msgType: message.msgType, from: message.from?.userId },
        'Bot message received',
      );

      // 触发回调
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
    } catch (error) {
      logger.error(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to parse Bot WebSocket message',
      );
    }
  }

  /**
   * 验证消息来源
   */
  private verifyMessageSource(raw: Record<string, unknown>): boolean {
    // 检查是否有必要的来源字段
    if (raw['msgType'] == null) {
      return false;
    }

    // 心跳消息不需要来源验证
    if (raw['msgType'] === 'heartbeat' || raw['msgType'] === 'heartbeat_ack') {
      return true;
    }

    // 检查是否有 from 字段（用户消息需要）
    if (raw['content'] != null && raw['from'] == null) {
      return false;
    }

    return true;
  }

  /**
   * 处理断连
   */
  private handleDisconnect(): void {
    this.stopHeartbeat();

    if (this.ws != null) {
      this.ws.removeAllListeners();
      this.ws = null;
    }

    if (!this.shouldRun) {
      this.state = 'disconnected';
      return;
    }

    // 尝试重连
    this.scheduleReconnect();
  }

  /**
   * 安排重连
   */
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

    // 计算指数退避延迟
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

  /**
   * 清除重连定时器
   */
  private clearReconnectTimer(): void {
    if (this.reconnectTimer != null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
