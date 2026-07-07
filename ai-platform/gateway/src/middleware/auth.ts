/**
 * auth.ts — 认证中间件（JWT 验证、企业微信签名验证）
 *
 * 实现：
 * - JWT Token 验证（本地 HS256 验签）
 * - 企业微信回调签名验证
 * - 可选认证（WebSocket 连接时）
 *
 * @module middleware/auth
 */

import type { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import crypto from 'node:crypto';
import { logger } from './logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** JWT 载荷 */
export interface JwtClaims {
  /** 用户 ID */
  userId: string;
  /** 用户名 */
  username: string;
  /** 部门 */
  department: string;
  /** 角色列表 */
  roles: string[];
  /** 渠道 */
  channel: string;
  /** Agent ID（可选） */
  agentId?: string;
  /** 签发者 */
  iss: string;
  /** 过期时间（Unix 时间戳） */
  exp: number;
  /** 签发时间（Unix 时间戳） */
  iat: number;
}

/** 认证配置 */
export interface AuthConfig {
  /** JWT 签名密钥 */
  jwtSecret: string;
  /** JWT 签发者 */
  jwtIssuer: string;
  /** Access Token 有效期（秒） */
  accessTokenTtl: number;
  /** 企业微信回调 Token */
  wecomCallbackToken: string;
  /** 企业微信回调 EncodingAESKey */
  wecomCallbackAesKey: string;
}

// ============================================================================
// JWT 工具
// ============================================================================

/**
 * Base64URL 解码
 * @param input - Base64URL 字符串
 * @returns 解码后的 Buffer
 */
function base64UrlDecode(input: string): Buffer {
  const padded = input.replace(/-/g, '+').replace(/_/g, '/');
  const pad = padded.length % 4 === 0 ? '' : '='.repeat(4 - (padded.length % 4));
  return Buffer.from(padded + pad, 'base64');
}

/**
 * Base64URL 编码
 * @param buffer - 原始 Buffer
 * @returns Base64URL 字符串
 */
function base64UrlEncode(buffer: Buffer): string {
  return buffer
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '');
}

/**
 * 验证 JWT Token（本地 HS256 验签）
 *
 * @param token - JWT Token 字符串
 * @param secret - HS256 签名密钥
 * @param expectedIssuer - 预期的签发者
 * @returns JWT 载荷
 * @throws Token 无效或过期时抛出错误
 */
export function verifyJwt(
  token: string,
  secret: string,
  expectedIssuer: string,
): JwtClaims {
  const parts = token.split('.');
  if (parts.length !== 3) {
    throw new AuthError('Invalid JWT format: expected 3 parts', 1001);
  }

  const [headerB64, payloadB64, signatureB64] = parts;

  // 验证签名
  const signingInput = Buffer.from(`${headerB64}.${payloadB64}`);
  const expectedSignature = crypto
    .createHmac('sha256', secret)
    .update(signingInput)
    .digest();
  const actualSignature = base64UrlDecode(signatureB64);

  if (!crypto.timingSafeEqual(expectedSignature, actualSignature)) {
    throw new AuthError('JWT signature verification failed', 1002);
  }

  // 解析载荷（兼容 user_id / userId）
  const raw = JSON.parse(
    base64UrlDecode(payloadB64).toString('utf-8'),
  ) as JwtClaims & { user_id?: string };

  const payload: JwtClaims = {
    ...raw,
    userId: raw.userId ?? raw.user_id ?? '',
  };

  // 验证签发者
  if (payload.iss !== expectedIssuer) {
    throw new AuthError(
      `JWT issuer mismatch: expected ${expectedIssuer}, got ${payload.iss}`,
      1003,
    );
  }

  // 验证过期时间
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp <= now) {
    throw new AuthError('JWT token expired', 1004);
  }

  return payload;
}

/**
 * 从请求中提取 JWT Token
 *
 * 支持从 Authorization Header 或查询参数中提取。
 *
 * @param req - Fastify 请求对象
 * @returns JWT Token 字符串或 undefined
 */
export function extractToken(req: FastifyRequest): string | undefined {
  // 优先从 Authorization Header 提取
  const authHeader = req.headers['authorization'];
  if (authHeader != null && authHeader.startsWith('Bearer ')) {
    return authHeader.slice(7);
  }

  // 回退到查询参数（WebSocket 连接时使用）
  const queryToken = (req.query as Record<string, string> | undefined)?.['token'];
  if (typeof queryToken === 'string' && queryToken.length > 0) {
    return queryToken;
  }

  return undefined;
}

// ============================================================================
// 错误类
// ============================================================================

/** 认证错误 */
export class AuthError extends Error {
  /** 错误码 */
  readonly code: number;

  constructor(message: string, code: number) {
    super(message);
    this.name = 'AuthError';
    this.code = code;
  }
}

// ============================================================================
// 企业微信签名验证
// ============================================================================

/**
 * 计算企业微信回调签名
 *
 * @param token - 企业微信回调配置的 Token
 * @param timestamp - 时间戳
 * @param nonce - 随机数
 * @param encrypt - 加密消息体
 * @returns SHA1 签名
 */
export function calculateWecomSignature(
  token: string,
  timestamp: string,
  nonce: string,
  encrypt: string,
): string {
  const sorted = [token, timestamp, nonce, encrypt].sort();
  return crypto
    .createHash('sha1')
    .update(sorted.join(''))
    .digest('hex');
}

/**
 * 验证企业微信回调签名
 *
 * @param token - 企业微信回调配置的 Token
 * @param timestamp - 时间戳
 * @param nonce - 随机数
 * @param encrypt - 加密消息体
 * @param signature - 待验证的签名
 * @returns 签名是否匹配
 */
export function verifyWecomSignature(
  token: string,
  timestamp: string,
  nonce: string,
  encrypt: string,
  signature: string,
): boolean {
  const calculated = calculateWecomSignature(token, timestamp, nonce, encrypt);
  return crypto.timingSafeEqual(
    Buffer.from(calculated),
    Buffer.from(signature),
  );
}

// ============================================================================
// Fastify 插件
// ============================================================================

/** 公开路径列表（不需要认证） */
const PUBLIC_PATHS = [
  '/health',
  '/health/live',
  '/health/ready',
  '/auth/wecom/js-sdk-config',
  '/auth/wecom/callback',
  '/auth/login',
  '/auth/refresh',
];

/**
 * 判断路径是否为公开路径
 * @param path - 请求路径
 * @returns 是否为公开路径
 */
function isPublicPath(path: string): boolean {
  return PUBLIC_PATHS.some((p) => path === p || path.startsWith(`${p}/`));
}

/**
 * 注册认证中间件
 *
 * - 公开路径跳过认证
 * - WebSocket 路径从查询参数提取 Token
 * - 其他路径从 Authorization Header 提取 Token
 *
 * @param app - Fastify 实例
 * @param config - 认证配置
 */
export function registerAuthMiddleware(
  app: FastifyInstance,
  config: AuthConfig,
): void {
  app.addHook('onRequest', async (req: FastifyRequest, reply: FastifyReply) => {
    // 公开路径跳过
    if (isPublicPath(req.url.split('?')[0] ?? '')) {
      return;
    }

    // 提取 Token
    const token = extractToken(req);
    if (token == null) {
      reply.code(401).send({
        code: 1001,
        data: null,
        message: 'Authentication required: no token provided',
        traceId: req.id,
      });
      return reply;
    }

    // 验证 Token
    try {
      const claims = verifyJwt(token, config.jwtSecret, config.jwtIssuer);
      // 将用户信息注入请求上下文
      (req as unknown as { user: JwtClaims }).user = claims;
    } catch (error) {
      const message =
        error instanceof AuthError
          ? error.message
          : 'JWT verification failed';
      const code = error instanceof AuthError ? error.code : 1002;

      logger.warn(
        { url: req.url, code, message },
        'Authentication failed',
      );

      reply.code(401).send({
        code,
        data: null,
        message,
        traceId: req.id,
      });
      return reply;
    }
  });
}
