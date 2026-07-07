/**
 * WecomAppMessage.ts — 企业微信应用消息推送（通知引导 H5）
 *
 * 实现企业微信应用消息推送，用于：
 * - HITL 审批通知（引导用户打开 H5 进行审批）
 * - 主动推送通知（周报/提醒等）
 * - Bot 渠道无法显示富内容时，推送应用消息引导用户打开 H5
 *
 * @module adapters/wecom/WecomAppMessage
 */

import axios from 'axios';
import { logger } from '../../middleware/logger.js';
import { withRetry, isNetworkError } from '../../utils/retry.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 应用消息类型 */
export type AppMessageType = 'text' | 'image' | 'news' | 'markdown';

/** 应用消息推送配置 */
export interface WecomAppMessageConfig {
  /** 企业 ID */
  corpId: string;
  /** 应用 Agent ID */
  agentId: string;
  /** 应用 Secret */
  corpSecret: string;
  /** 企业微信 API 基础 URL */
  apiBaseUrl: string;
}

/** 应用消息基础结构 */
export interface AppMessage {
  /** 接收人（用户 ID 列表，以 | 分隔） */
  touser: string;
  /** 接收部门（部门 ID 列表，以 | 分隔） */
  toparty?: string;
  /** 接收标签（标签 ID 列表，以 | 分隔） */
  totag?: string;
  /** 消息类型 */
  msgtype: AppMessageType;
  /** 应用 Agent ID */
  agentid: number;
  /** 文本消息内容 */
  text?: { content: string };
  /** Markdown 消息内容 */
  markdown?: { content: string };
  /** 图文消息项 */
  news?: {
    articles: Array<{
      /** 标题 */
      title: string;
      /** 描述 */
      description: string;
      /** 链接 URL */
      url: string;
      /** 封面图片 URL */
      picurl: string;
    }>;
  };
  /** 是否启用 ID 转译 */
    enable_id_trans?: boolean;
  /** 是否重复检查 */
    enable_duplicate_check?: boolean;
  /** 重复检查间隔（秒） */
    duplicate_check_interval?: number;
}

/** 应用消息发送响应 */
interface SendMessageResponse {
  errcode: number;
  errmsg: string;
  msgid: string;
  invaliduser?: string;
  invalidparty?: string;
  invalidtag?: string;
}

// ============================================================================
// 常量
// ============================================================================

const DEFAULT_API_BASE_URL = 'https://qyapi.weixin.qq.com';

// ============================================================================
// WecomAppMessage
// ============================================================================

/**
 * 企业微信应用消息推送
 *
 * 负责向企业微信用户推送应用消息，用于通知引导 H5。
 * 内部复用 WecomJSSDKHelper 的 access_token 获取逻辑。
 */
export class WecomAppMessage {
  private readonly config: WecomAppMessageConfig;
  private accessToken: string | null = null;
  private accessTokenExpiresAt = 0;

  constructor(config: Partial<WecomAppMessageConfig> & { corpId: string; corpSecret: string; agentId: string }) {
    this.config = {
      corpId: config.corpId,
      agentId: config.agentId,
      corpSecret: config.corpSecret,
      apiBaseUrl: config.apiBaseUrl ?? DEFAULT_API_BASE_URL,
    };
  }

  /**
   * 获取 access_token（内部使用，带缓存）
   * @returns access_token
   */
  private async getAccessToken(): Promise<string> {
    if (this.accessToken != null && Date.now() < this.accessTokenExpiresAt) {
      return this.accessToken;
    }

    const url = `${this.config.apiBaseUrl}/cgi-bin/gettoken`;
    const response = await withRetry(
      () =>
        axios.get(url, {
          params: {
            corpid: this.config.corpId,
            corpsecret: this.config.corpSecret,
          },
          timeout: 10000,
        }),
      {
        maxRetries: 3,
        initialDelayMs: 1000,
        retryOn: (error) =>
          isNetworkError(error) ||
          (axios.isAxiosError(error) &&
            error.response?.status != null &&
            error.response.status >= 500),
      },
    );

    const data = response.data as { errcode: number; errmsg: string; access_token: string; expires_in: number };
    if (data.errcode !== 0) {
      throw new Error(`Failed to get access_token: ${data.errcode} ${data.errmsg}`);
    }

    this.accessToken = data.access_token;
    this.accessTokenExpiresAt = Date.now() + (data.expires_in - 300) * 1000;

    return data.access_token;
  }

  /**
   * 推送文本应用消息
   *
   * @param touser - 接收人用户 ID（多个以 | 分隔）
   * @param content - 文本内容
   * @returns 消息 ID
   */
  async sendTextMessage(touser: string, content: string): Promise<string> {
    const message: AppMessage = {
      touser,
      msgtype: 'text',
      agentid: parseInt(this.config.agentId, 10),
      text: { content },
      enable_id_trans: true,
      enable_duplicate_check: true,
      duplicate_check_interval: 1800,
    };
    return this.sendMessage(message);
  }

  /**
   * 推送 Markdown 应用消息
   *
   * @param touser - 接收人用户 ID
   * @param content - Markdown 内容
   * @returns 消息 ID
   */
  async sendMarkdownMessage(touser: string, content: string): Promise<string> {
    const message: AppMessage = {
      touser,
      msgtype: 'markdown',
      agentid: parseInt(this.config.agentId, 10),
      markdown: { content },
      enable_id_trans: true,
    };
    return this.sendMessage(message);
  }

  /**
   * 推送图文应用消息（引导用户打开 H5）
   *
   * @param touser - 接收人用户 ID
   * @param title - 标题
   * @param description - 描述
   * @param url - H5 链接 URL
   * @param picurl - 封面图片 URL
   * @returns 消息 ID
   */
  async sendNewsMessage(
    touser: string,
    title: string,
    description: string,
    url: string,
    picurl = '',
  ): Promise<string> {
    const message: AppMessage = {
      touser,
      msgtype: 'news',
      agentid: parseInt(this.config.agentId, 10),
      news: {
        articles: [{ title, description, url, picurl }],
      },
      enable_id_trans: true,
    };
    return this.sendMessage(message);
  }

  /**
   * 推送审批通知应用消息（HITL 审批引导）
   *
   * @param touser - 接收人用户 ID
   * @param approvalTitle - 审批标题
   * @param approvalDescription - 审批描述
   * @param h5Url - H5 审批页面 URL
   * @returns 消息 ID
   */
  async sendApprovalNotification(
    touser: string,
    approvalTitle: string,
    approvalDescription: string,
    h5Url: string,
  ): Promise<string> {
    const content = [
      `## 审批通知`,
      ``,
      `**${approvalTitle}**`,
      ``,
      `${approvalDescription}`,
      ``,
      `[点击查看详情并处理](${h5Url})`,
    ].join('\n');

    return this.sendMarkdownMessage(touser, content);
  }

  /**
   * 发送应用消息（底层方法）
   *
   * @param message - 应用消息结构
   * @returns 消息 ID
   * @throws 发送失败时抛出错误
   */
  async sendMessage(message: AppMessage): Promise<string> {
    const accessToken = await this.getAccessToken();
    const url = `${this.config.apiBaseUrl}/cgi-bin/message/send`;

    const response = await withRetry(
      () =>
        axios.post<SendMessageResponse>(url, message, {
          params: { access_token: accessToken },
          timeout: 15000,
        }),
      {
        maxRetries: 3,
        initialDelayMs: 1000,
        retryOn: (error) =>
          isNetworkError(error) ||
          (axios.isAxiosError(error) &&
            error.response?.status != null &&
            error.response.status >= 500),
      },
    );

    const data = response.data;
    if (data.errcode !== 0) {
      throw new Error(
        `Failed to send app message: ${data.errcode} ${data.errmsg}`,
      );
    }

    logger.info(
      {
        msgid: data.msgid,
        touser: message.touser,
        msgtype: message.msgtype,
        invaliduser: data.invaliduser,
      },
      'App message sent successfully',
    );

    return data.msgid;
  }

  /**
   * 强制刷新 access_token 缓存
   */
  invalidateCache(): void {
    this.accessToken = null;
    this.accessTokenExpiresAt = 0;
    logger.info('App message access_token cache invalidated');
  }
}
