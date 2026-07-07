/**
 * rateLimit.ts — 限流中间件
 *
 * 基于 Redis 的滑动窗口限流，支持按 IP / 用户 / 渠道维度限流。
 * 使用 @fastify/rate-limit 作为本地限流兜底。
 *
 * @module middleware/rateLimit
 */

import type { FastifyInstance } from 'fastify';
import rateLimit from '@fastify/rate-limit';
import { logger } from './logger.js';
import type { JwtClaims } from './auth.js';
import type { Redis } from 'ioredis';

// ============================================================================
// 类型定义
// ============================================================================

/** 限流配置 */
export interface RateLimitConfig {
  /** 全局时间窗口（秒） */
  globalWindowSec: number;
  /** 全局时间窗口内最大请求数 */
  globalMaxRequests: number;
  /** 单用户时间窗口（秒） */
  userWindowSec: number;
  /** 单用户时间窗口内最大请求数 */
  userMaxRequests: number;
  /** 单 IP 时间窗口（秒） */
  ipWindowSec: number;
  /** 单 IP 时间窗口内最大请求数 */
  ipMaxRequests: number;
}

/** 限流检查结果 */
interface RateLimitResult {
  /** 是否允许通过 */
  allowed: boolean;
  /** 剩余可用请求数 */
  remaining: number;
  /** 限流重置时间（Unix 时间戳，秒） */
  resetAt: number;
  /** 限流键 */
  key: string;
}

// ============================================================================
// 默认配置
// ============================================================================

const DEFAULT_CONFIG: RateLimitConfig = {
  globalWindowSec: 60,
  globalMaxRequests: 1000,
  userWindowSec: 60,
  userMaxRequests: 60,
  ipWindowSec: 60,
  ipMaxRequests: 100,
};

// ============================================================================
// Redis 滑动窗口限流器
// ============================================================================

/**
 * Redis 滑动窗口限流器
 *
 * 使用 Redis Sorted Set 实现滑动窗口限流：
 * - 每次请求将当前时间戳作为 score 和 member 添加到有序集合
 * - 清除窗口外的过期记录
 * - 检查当前窗口内的记录数是否超限
 */
export class RedisRateLimiter {
  private readonly redis: Redis;
  private readonly config: RateLimitConfig;

  constructor(redis: Redis, config?: Partial<RateLimitConfig>) {
    this.redis = redis;
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * 检查限流
   * @param key - 限流键（如 rate:user:{userId} 或 rate:ip:{ip}）
   * @param windowSec - 时间窗口（秒）
   * @param maxRequests - 窗口内最大请求数
   * @returns 限流检查结果
   */
  async check(
    key: string,
    windowSec: number,
    maxRequests: number,
  ): Promise<RateLimitResult> {
    const now = Date.now();
    const windowStart = now - windowSec * 1000;
    const resetAt = Math.floor((now + windowSec * 1000) / 1000);

    // 使用 Lua 脚本保证原子性
    const luaScript = `
      local key = KEYS[1]
      local now = tonumber(ARGV[1])
      local window_start = tonumber(ARGV[2])
      local max_requests = tonumber(ARGV[3])
      local member = ARGV[4]

      -- 清除窗口外的记录
      redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

      -- 获取当前窗口内的请求数
      local count = redis.call('ZCARD', key)

      if count >= max_requests then
        return {0, max_requests - count, redis.call('ZSCORE', key, member) or tostring(now)}
      end

      -- 添加当前请求
      redis.call('ZADD', key, now, member)
      redis.call('EXPIRE', key, tonumber(ARGV[5]) + 1)

      return {1, max_requests - count - 1, tostring(now)}
    `;

    const member = `${now}:${Math.random().toString(36).slice(2, 10)}`;
    const result = (await this.redis.eval(
      luaScript,
      1,
      key,
      now.toString(),
      windowStart.toString(),
      maxRequests.toString(),
      member,
      windowSec.toString(),
    )) as number[];

    return {
      allowed: result[0] === 1,
      remaining: Math.max(0, result[1] ?? 0),
      resetAt,
      key,
    };
  }

  /**
   * 检查用户级别限流
   * @param userId - 用户 ID
   * @returns 限流检查结果
   */
  async checkUser(userId: string): Promise<RateLimitResult> {
    return this.check(
      `rate:user:${userId}`,
      this.config.userWindowSec,
      this.config.userMaxRequests,
    );
  }

  /**
   * 检查 IP 级别限流
   * @param ip - 客户端 IP
   * @returns 限流检查结果
   */
  async checkIp(ip: string): Promise<RateLimitResult> {
    return this.check(
      `rate:ip:${ip}`,
      this.config.ipWindowSec,
      this.config.ipMaxRequests,
    );
  }

  /**
   * 检查全局限流
   * @returns 限流检查结果
   */
  async checkGlobal(): Promise<RateLimitResult> {
    return this.check(
      'rate:global',
      this.config.globalWindowSec,
      this.config.globalMaxRequests,
    );
  }

  /**
   * 综合限流检查（用户 + IP + 全局）
   * @param userId - 用户 ID（可选）
   * @param ip - 客户端 IP
   * @returns 限流检查结果（取最严格的限制）
   */
  async checkAll(
    userId: string | undefined,
    ip: string,
  ): Promise<RateLimitResult> {
    const checks: Promise<RateLimitResult>[] = [this.checkIp(ip), this.checkGlobal()];

    if (userId != null) {
      checks.push(this.checkUser(userId));
    }

    const results = await Promise.all(checks);

    // 返回第一个被拒绝的结果
    const denied = results.find((r) => !r.allowed);
    if (denied != null) {
      return denied;
    }

    // 返回剩余请求数最少的结果
    return results.reduce((min, curr) =>
      curr.remaining < min.remaining ? curr : min,
    );
  }
}

// ============================================================================
// Fastify 插件
// ============================================================================

/**
 * 注册限流中间件
 *
 * - 注册 @fastify/rate-limit 作为本地快速限流（防突发）
 * - 注册 Redis 滑动窗口限流（精确控制）
 *
 * @param app - Fastify 实例
 * @param redis - Redis 客户端
 * @param config - 限流配置
 */
export async function registerRateLimitMiddleware(
  app: FastifyInstance,
  redis: Redis,
  config?: Partial<RateLimitConfig>,
): Promise<void> {
  const fullConfig = { ...DEFAULT_CONFIG, ...config };
  const limiter = new RedisRateLimiter(redis, fullConfig);

  // 注册本地限流（快速兜底，防突发，使用内存存储）
  // 精确的 Redis 滑动窗口限流由下方的 preHandler 钩子处理
  await app.register(rateLimit, {
    max: fullConfig.ipMaxRequests,
    timeWindow: `${fullConfig.ipWindowSec}s`,
    // 使用自定义标识符
    keyGenerator: (req) => {
      const user = (req as unknown as { user?: JwtClaims }).user;
      return user != null ? `user:${user.userId}` : `ip:${req.ip}`;
    },
    errorResponseBuilder: (_req, context) => ({
      code: 5001,
      data: null,
      message: `Rate limit exceeded. Try again in ${Math.ceil(context.ttl / 1000)} seconds.`,
      traceId: _req.id,
    }),
    skipOnError: true,
  });

  // Redis 滑动窗口限流（精确控制）
  app.addHook('preHandler', async (req, reply) => {
    const user = (req as unknown as { user?: JwtClaims }).user;
    const userId = user?.userId;
    const ip = req.ip;

    try {
      const result = await limiter.checkAll(userId, ip);
      if (!result.allowed) {
        // 设置限流响应头
        reply.header('X-RateLimit-Limit', fullConfig.userMaxRequests.toString());
        reply.header('X-RateLimit-Remaining', '0');
        reply.header(
          'X-RateLimit-Reset',
          result.resetAt.toString(),
        );

        reply.code(429).send({
          code: 5001,
          data: null,
          message: 'Rate limit exceeded. Please try again later.',
          traceId: req.id,
        });
        return reply;
      }

      // 设置限流响应头
      reply.header('X-RateLimit-Remaining', result.remaining.toString());
      reply.header('X-RateLimit-Reset', result.resetAt.toString());
    } catch (error) {
      // Redis 限流检查失败时放行（不阻塞正常请求）
      logger.warn(
        { error: error instanceof Error ? error.message : String(error), ip },
        'Rate limit check failed, allowing request',
      );
    }
  });
}
