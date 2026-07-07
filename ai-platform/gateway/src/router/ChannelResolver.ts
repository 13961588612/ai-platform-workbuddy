/**
 * ChannelResolver.ts — 渠道解析器
 *
 * 根据请求来源解析渠道类型，生成符合 v1.4.1 命名规范的 session_id。
 *
 * session_id 命名规范：
 * - Web/H5: web-{uuid}
 * - 企业微信 Bot: wecom-bot-{uuid}
 * - 企业微信 H5: wecom-h5-{uuid}
 *
 * @module router/ChannelResolver
 */

import { randomUUID } from 'node:crypto';
import type { ChannelType } from '../channels/ChannelCapability.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 渠道来源标识 */
export type ChannelSource = 'web' | 'wecom-h5' | 'wecom-bot';

/** 渠道解析结果 */
export interface ChannelResolveResult {
  /** 渠道类型 */
  channelType: ChannelType;
  /** 渠道来源标识 */
  source: ChannelSource;
  /** 会话 ID */
  sessionId: string;
  /** session_id 前缀 */
  sessionPrefix: string;
}

// ============================================================================
// 常量
// ============================================================================

/** 渠道来源到 ChannelType 映射 */
const SOURCE_TO_CHANNEL: Record<ChannelSource, ChannelType> = {
  web: 'h5',
  'wecom-h5': 'wecom-h5',
  'wecom-bot': 'wecom-bot',
};

/** session_id 前缀映射 */
const SESSION_PREFIX: Record<ChannelSource, string> = {
  web: 'web-',
  'wecom-h5': 'wecom-h5-',
  'wecom-bot': 'wecom-bot-',
};

// ============================================================================
// ChannelResolver
// ============================================================================

/**
 * 渠道解析器
 *
 * 根据请求的 URL 路径、Header 或查询参数解析渠道来源，
 * 并生成符合命名规范的 session_id。
 */
export class ChannelResolver {
  /**
   * 从请求路径解析渠道来源
   *
   * 路径规则：
   * - /api/wecom/h5/* → wecom-h5
   * - /api/wecom/bot/* → wecom-bot
   * - /api/web/* 或 /ws/* → web
   *
   * @param path - 请求路径
   * @returns 渠道来源标识
   */
  static resolveFromPath(path: string): ChannelSource {
    if (path.startsWith('/api/wecom/h5') || path.startsWith('/wecom/h5')) {
      return 'wecom-h5';
    }
    if (path.startsWith('/api/wecom/bot') || path.startsWith('/wecom/bot')) {
      return 'wecom-bot';
    }
    // 默认为 web 渠道
    return 'web';
  }

  /**
   * 从 WebSocket 连接路径解析渠道来源
   *
   * @param path - WebSocket 连接路径
   * @returns 渠道来源标识
   */
  static resolveFromWsPath(path: string): ChannelSource {
    if (path.includes('wecom-h5') || path.includes('wecom/h5')) {
      return 'wecom-h5';
    }
    if (path.includes('wecom-bot') || path.includes('wecom/bot')) {
      return 'wecom-bot';
    }
    return 'web';
  }

  /**
   * 从 Header 解析渠道来源
   *
   * @param headers - 请求头
   * @returns 渠道来源标识或 undefined
   */
  static resolveFromHeaders(
    headers: Record<string, string | string[] | undefined>,
  ): ChannelSource | undefined {
    const channel = headers['x-channel'];
    if (typeof channel === 'string') {
      if (channel === 'wecom-h5' || channel === 'wecom-bot' || channel === 'web') {
        return channel;
      }
    }
    return undefined;
  }

  /**
   * 综合解析渠道来源
   *
   * 优先级：Header > 路径 > 默认(web)
   *
   * @param path - 请求路径
   * @param headers - 请求头
   * @returns 渠道解析结果
   */
  static resolve(
    path: string,
    headers?: Record<string, string | string[] | undefined>,
  ): ChannelResolveResult {
    // 优先从 Header 获取
    let source: ChannelSource | undefined;
    if (headers != null) {
      source = this.resolveFromHeaders(headers);
    }

    // 回退到路径解析
    if (source == null) {
      source = this.resolveFromPath(path);
    }

    const channelType = SOURCE_TO_CHANNEL[source];
    const sessionPrefix = SESSION_PREFIX[source];
    const sessionId = this.generateSessionId(source);

    return {
      channelType,
      source,
      sessionId,
      sessionPrefix,
    };
  }

  /**
   * 生成符合命名规范的 session_id
   *
   * @param source - 渠道来源
   * @returns session_id（如 web-{uuid}）
   */
  static generateSessionId(source: ChannelSource): string {
    return `${SESSION_PREFIX[source]}${randomUUID()}`;
  }

  /**
   * 根据 session_id 解析渠道来源
   *
   * @param sessionId - 会话 ID
   * @returns 渠道来源标识或 undefined
   */
  static resolveFromSessionId(sessionId: string): ChannelSource | undefined {
    for (const [source, prefix] of Object.entries(SESSION_PREFIX)) {
      if (sessionId.startsWith(prefix)) {
        return source as ChannelSource;
      }
    }
    return undefined;
  }

  /**
   * 根据 ChannelType 获取默认渠道来源
   *
   * @param channelType - 渠道类型
   * @returns 渠道来源标识
   */
  static getDefaultSource(channelType: ChannelType): ChannelSource {
    for (const [source, type] of Object.entries(SOURCE_TO_CHANNEL)) {
      if (type === channelType) {
        return source as ChannelSource;
      }
    }
    return 'web';
  }
}
