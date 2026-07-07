/**
 * WecomJSSDKHelper.ts — 企业微信 JS-SDK 签名/鉴权辅助
 *
 * 实现企业微信 JS-SDK 签名流程：
 * corpid + corpsecret → access_token → jsapi_ticket → 签名
 *
 * 签名算法：SHA1(jsapi_ticket=xxx&noncestr=xxx&timestamp=xxx&url=xxx)
 *
 * @module adapters/wecom/WecomJSSDKHelper
 */

import axios from 'axios';
import crypto from 'node:crypto';
import { logger } from '../../middleware/logger.js';
import { withRetry, isNetworkError } from '../../utils/retry.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 企业微信 JS-SDK 配置 */
export interface WecomJsSdkConfig {
  /** 企业 ID */
  corpId: string;
  /** 应用 Agent ID */
  agentId: string;
  /** 应用 Secret */
  corpSecret: string;
  /** 企业微信 API 基础 URL */
  apiBaseUrl: string;
}

/** JS-SDK 签名结果（返回给前端） */
export interface JsSdkSignature {
  /** 企业 ID（前端 wx.qy.config 的 appId） */
  appId: string;
  /** 时间戳 */
  timestamp: string;
  /** 随机字符串 */
  nonceStr: string;
  /** 签名 */
  signature: string;
}

/** access_token 响应 */
interface AccessTokenResponse {
  errcode: number;
  errmsg: string;
  access_token: string;
  expires_in: number;
}

/** jsapi_ticket 响应 */
interface JsApiTicketResponse {
  errcode: number;
  errmsg: string;
  ticket: string;
  expires_in: number;
}

// ============================================================================
// 常量
// ============================================================================

/** access_token 缓存 TTL（秒），提前 5 分钟过期 */
const ACCESS_TOKEN_TTL_BUFFER = 300;

/** jsapi_ticket 缓存 TTL（秒），提前 5 分钟过期 */
const JSAPI_TICKET_TTL_BUFFER = 300;

/** 企业微信 API 默认基础 URL */
const DEFAULT_API_BASE_URL = 'https://qyapi.weixin.qq.com';

// ============================================================================
// 缓存项
// ============================================================================

interface CacheItem<T> {
  value: T;
  expiresAt: number;
}

// ============================================================================
// WecomJSSDKHelper
// ============================================================================

/**
 * 企业微信 JS-SDK 签名/鉴权辅助
 *
 * 负责：
 * 1. 获取企业微信 access_token（corpid + corpsecret）
 * 2. 获取 jsapi_ticket（使用 access_token）
 * 3. 生成 JS-SDK 签名
 *
 * access_token 和 jsapi_ticket 带缓存，避免频繁调用企业微信 API。
 */
export class WecomJSSDKHelper {
  private readonly config: WecomJsSdkConfig;
  private accessTokenCache: CacheItem<string> | null = null;
  private jsApiTicketCache: CacheItem<string> | null = null;

  constructor(config: Partial<WecomJsSdkConfig> & { corpId: string; corpSecret: string }) {
    this.config = {
      corpId: config.corpId,
      agentId: config.agentId ?? '',
      corpSecret: config.corpSecret,
      apiBaseUrl: config.apiBaseUrl ?? DEFAULT_API_BASE_URL,
    };
  }

  /**
   * 获取企业微信 access_token
   *
   * access_token 是企业微信 API 的全局调用凭证，有效期 7200 秒。
   * 内部带缓存，提前 5 分钟刷新。
   *
   * @returns access_token
   */
  async getAccessToken(): Promise<string> {
    // 检查缓存
    if (this.accessTokenCache != null && Date.now() < this.accessTokenCache.expiresAt) {
      return this.accessTokenCache.value;
    }

    const url = `${this.config.apiBaseUrl}/cgi-bin/gettoken`;
    const response = await withRetry(
      () =>
        axios.get<AccessTokenResponse>(url, {
          params: {
            corpid: this.config.corpId,
            corpsecret: this.config.corpSecret,
          },
          timeout: 10000,
        }),
      {
        maxRetries: 3,
        initialDelayMs: 1000,
        retryOn: (error) => isNetworkError(error) || (axios.isAxiosError(error) && error.response?.status != null && error.response.status >= 500),
      },
    );

    const data = response.data;
    if (data.errcode !== 0) {
      throw new Error(
        `Failed to get access_token: ${data.errcode} ${data.errmsg}`,
      );
    }

    // 缓存 access_token
    const expiresAt =
      Date.now() + (data.expires_in - ACCESS_TOKEN_TTL_BUFFER) * 1000;
    this.accessTokenCache = {
      value: data.access_token,
      expiresAt,
    };

    logger.debug(
      { expiresInSeconds: data.expires_in - ACCESS_TOKEN_TTL_BUFFER },
      'access_token acquired and cached',
    );

    return data.access_token;
  }

  /**
   * 获取 jsapi_ticket
   *
   * jsapi_ticket 是企业微信 JS-SDK 的临时票据，有效期 7200 秒。
   * 内部带缓存，提前 5 分钟刷新。
   *
   * @returns jsapi_ticket
   */
  async getJsApiTicket(): Promise<string> {
    // 检查缓存
    if (this.jsApiTicketCache != null && Date.now() < this.jsApiTicketCache.expiresAt) {
      return this.jsApiTicketCache.value;
    }

    const accessToken = await this.getAccessToken();
    const url = `${this.config.apiBaseUrl}/cgi-bin/get_jsapi_ticket`;
    const response = await withRetry(
      () =>
        axios.get<JsApiTicketResponse>(url, {
          params: { access_token: accessToken },
          timeout: 10000,
        }),
      {
        maxRetries: 3,
        initialDelayMs: 1000,
        retryOn: (error) => isNetworkError(error) || (axios.isAxiosError(error) && error.response?.status != null && error.response.status >= 500),
      },
    );

    const data = response.data;
    if (data.errcode !== 0) {
      throw new Error(
        `Failed to get jsapi_ticket: ${data.errcode} ${data.errmsg}`,
      );
    }

    // 缓存 jsapi_ticket
    const expiresAt =
      Date.now() + (data.expires_in - JSAPI_TICKET_TTL_BUFFER) * 1000;
    this.jsApiTicketCache = {
      value: data.ticket,
      expiresAt,
    };

    logger.debug(
      { expiresInSeconds: data.expires_in - JSAPI_TICKET_TTL_BUFFER },
      'jsapi_ticket acquired and cached',
    );

    return data.ticket;
  }

  /**
   * 生成 JS-SDK 签名
   *
   * 签名算法：SHA1(jsapi_ticket=xxx&noncestr=xxx&timestamp=xxx&url=xxx)
   *
   * @param url - 当前页面 URL（不含 # 及之后部分）
   * @returns JS-SDK 签名配置（传给前端 wx.qy.config）
   */
  async getJsSdkConfig(url: string): Promise<JsSdkSignature> {
    const ticket = await this.getJsApiTicket();
    const nonceStr = crypto.randomBytes(16).toString('hex');
    const timestamp = Math.floor(Date.now() / 1000).toString();

    // 按字典序排序参数并拼接
    const params = `jsapi_ticket=${ticket}&noncestr=${nonceStr}&timestamp=${timestamp}&url=${url}`;
    const signature = crypto.createHash('sha1').update(params).digest('hex');

    logger.debug(
      { url, timestamp, nonceStr },
      'JS-SDK signature generated',
    );

    return {
      appId: this.config.corpId,
      timestamp,
      nonceStr,
      signature,
    };
  }

  /**
   * 强制刷新缓存（access_token 和 jsapi_ticket）
   */
  invalidateCache(): void {
    this.accessTokenCache = null;
    this.jsApiTicketCache = null;
    logger.info('JS-SDK cache invalidated');
  }
}
