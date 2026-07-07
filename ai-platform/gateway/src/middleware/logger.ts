/**
 * logger.ts — 请求日志（pino）
 *
 * 结构化 JSON 日志，支持 traceId 链路追踪、敏感字段脱敏、
 * 请求/响应日志记录。
 *
 * @module middleware/logger
 */

import pino from 'pino';
import type { FastifyInstance, FastifyRequest, FastifyReply } from 'fastify';
import { randomUUID } from 'node:crypto';

// ============================================================================
// 常量
// ============================================================================

const SENSITIVE_FIELDS = [
  'password',
  'token',
  'api_key',
  'apikey',
  'api-key',
  'secret',
  'aes_key',
  'aesKey',
  'authorization',
  'cookie',
  'access_token',
  'accessToken',
  'refresh_token',
  'refreshToken',
  'corpSecret',
  'corp_secret',
  'encodingAesKey',
  'encoding_aes_key',
];

const MASK_VALUE = '***';

// ============================================================================
// 日志器创建
// ============================================================================

const isDevelopment = process.env['NODE_ENV'] !== 'production';
const logLevel = process.env['LOG_LEVEL'] ?? 'info';

/**
 * 根日志志器实例
 *
 * 输出 JSON 结构化日志，包含 timestamp、level、service、traceId、message 字段。
 */
export const logger = pino({
  level: logLevel,
  base: {
    service: 'ai-platform-gateway',
  },
  timestamp: pino.stdTimeFunctions.isoTime,
  redact: {
    paths: SENSITIVE_FIELDS.map((field) => `*.${field}`),
    censor: MASK_VALUE,
  },
  ...(isDevelopment
    ? {
        transport: {
          target: 'pino-pretty',
          options: {
            colorize: true,
            translateTime: 'SYS:standard',
            ignore: 'pid,hostname',
          },
        },
      }
    : {}),
});

/**
 * 创建带 traceId 的子日志器
 * @param traceId - 链路追踪 ID
 * @returns 子日志器实例
 */
export function createChildLogger(traceId: string): pino.Logger {
  return logger.child({ traceId });
}

// ============================================================================
// 请求 ID 生成
// ============================================================================

/**
 * 生成请求追踪 ID
 * @returns UUID v4 格式的追踪 ID
 */
export function generateTraceId(): string {
  return randomUUID();
}

// ============================================================================
// 敏感字段脱敏
// ============================================================================

/**
 * 递归脱敏对象中的敏感字段
 * @param obj - 原始对象
 * @param depth - 递归深度（内部使用）
 * @returns 脱敏后的对象副本
 */
export function maskSensitiveFields(
  obj: unknown,
  depth = 0,
): unknown {
  if (depth > 10 || obj == null) {
    return obj;
  }

  if (typeof obj !== 'object') {
    return obj;
  }

  if (Array.isArray(obj)) {
    return obj.map((item) => maskSensitiveFields(item, depth + 1));
  }

  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
    if (SENSITIVE_FIELDS.includes(key.toLowerCase())) {
      result[key] = MASK_VALUE;
    } else if (typeof value === 'object' && value !== null) {
      result[key] = maskSensitiveFields(value, depth + 1);
    } else {
      result[key] = value;
    }
  }
  return result;
}

// ============================================================================
// Fastify 插件
// ============================================================================

/**
 * 请求日志中间件
 *
 * 为每个请求生成 traceId，记录请求和响应日志。
 * 使用 onRequest + onResponse 钩子实现。
 *
 * @param app - Fastify 实例
 */
export function registerLoggerMiddleware(app: FastifyInstance): void {
  // 为每个请求注入 traceId
  app.addHook('onRequest', async (req: FastifyRequest) => {
    const traceId =
      (req.headers['x-trace-id'] as string | undefined) ?? generateTraceId();
    req.id = traceId;
    req.log = logger.child({ traceId });

    const logData = {
      method: req.method,
      url: req.url,
      ip: req.ip,
      userAgent: req.headers['user-agent'] ?? '-',
    };
    req.log.info(logData, 'Incoming request');
  });

  // 响应日志
  app.addHook('onResponse', async (req: FastifyRequest, reply: FastifyReply) => {
    const responseTime = reply.elapsedTime.toFixed(2);
    const logData = {
      method: req.method,
      url: req.url,
      statusCode: reply.statusCode,
      responseTimeMs: responseTime,
    };
    if (reply.statusCode >= 500) {
      req.log.error(logData, 'Request completed with error');
    } else if (reply.statusCode >= 400) {
      req.log.warn(logData, 'Request completed with client error');
    } else {
      req.log.info(logData, 'Request completed');
    }
  });

  // 错误日志
  app.addHook('onError', async (req: FastifyRequest, reply: FastifyReply, error: Error) => {
    req.log.error(
      {
        method: req.method,
        url: req.url,
        statusCode: reply.statusCode,
        error: error.name,
        message: error.message,
        stack: isDevelopment ? error.stack : undefined,
      },
      'Request error',
    );
  });
}

export { pino };
