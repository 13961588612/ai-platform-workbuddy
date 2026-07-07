/**
 * retry.ts — 重试工具（指数退避）
 *
 * 提供通用的异步操作重试机制，支持指数退避策略，
 * 可配置最大重试次数、初始延迟、最大延迟和重试条件。
 *
 * @module utils/retry
 */

// ============================================================================
// 类型定义
// ============================================================================

/** 重试配置选项 */
export interface RetryOptions {
  /** 最大重试次数（不包含首次尝试），默认 3 */
  maxRetries: number;
  /** 初始延迟（毫秒），默认 1000 */
  initialDelayMs: number;
  /** 最大延迟（毫秒），默认 30000 */
  maxDelayMs: number;
  /** 退避乘数，每次延迟乘以此系数，默认 2 */
  backoffMultiplier: number;
  /** 是否添加抖动（jitter）以避免惊群效应，默认 true */
  jitter: boolean;
  /** 判断错误是否可重试的函数，返回 true 则重试 */
  retryOn?: (error: unknown) => boolean;
  /** 每次重试前的回调 */
  onRetry?: (error: unknown, attempt: number, delayMs: number) => void;
}

/** 重试结果 */
export interface RetryResult<T> {
  /** 最终结果值 */
  value: T;
  /** 总尝试次数（含首次） */
  totalAttempts: number;
  /** 总耗时（毫秒） */
  totalDurationMs: number;
}

// ============================================================================
// 默认配置
// ============================================================================

const DEFAULT_OPTIONS: RetryOptions = {
  maxRetries: 3,
  initialDelayMs: 1000,
  maxDelayMs: 30000,
  backoffMultiplier: 2,
  jitter: true,
};

// ============================================================================
// 工具函数
// ============================================================================

/**
 * 延迟指定毫秒
 * @param ms - 延迟毫秒数
 * @returns Promise 在延迟后 resolve
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 计算第 N 次重试的延迟时间（指数退避）
 * @param attempt - 重试次数（从 0 开始）
 * @param options - 重试配置
 * @returns 延迟毫秒数
 */
export function calculateDelay(
  attempt: number,
  options: RetryOptions,
): number {
  const baseDelay =
    options.initialDelayMs * Math.pow(options.backoffMultiplier, attempt);
  let delay = Math.min(baseDelay, options.maxDelayMs);

  if (options.jitter) {
    // 添加 ±25% 的抖动
    const jitterRange = delay * 0.25;
    delay = delay - jitterRange + Math.random() * jitterRange * 2;
  }

  return Math.max(0, Math.round(delay));
}

/**
 * 判断错误是否为网络错误（可重试）
 * @param error - 错误对象
 * @returns 是否为可重试的网络错误
 */
export function isNetworkError(error: unknown): boolean {
  if (error == null || typeof error !== 'object') {
    return false;
  }
  const err = error as Record<string, unknown>;
  const code = err.code as string | undefined;

  return (
    code === 'ECONNRESET' ||
    code === 'ECONNREFUSED' ||
    code === 'ETIMEDOUT' ||
    code === 'EPIPE' ||
    code === 'EAI_AGAIN' ||
    code === 'ENOTFOUND' ||
    code === 'EHOSTUNREACH' ||
    code === 'ENETUNREACH'
  );
}

/**
 * 判断 HTTP 状态码是否可重试
 * @param statusCode - HTTP 状态码
 * @returns 是否可重试
 */
export function isRetryableStatusCode(statusCode: number): boolean {
  return statusCode === 408 || statusCode === 429 || statusCode >= 500;
}

// ============================================================================
// 核心重试函数
// ============================================================================

/**
 * 带指数退避的异步重试执行器
 *
 * @param fn - 要执行的异步函数
 * @param options - 重试配置
 * @returns 重试结果
 * @throws 当所有重试都失败后抛出最后一次错误
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  options?: Partial<RetryOptions>,
): Promise<RetryResult<T>> {
  const opts: RetryOptions = { ...DEFAULT_OPTIONS, ...options };
  const startTime = Date.now();
  let lastError: unknown;
  let attempt = 0;

  for (let i = 0; i <= opts.maxRetries; i++) {
    attempt = i;
    try {
      const value = await fn();
      return {
        value,
        totalAttempts: i + 1,
        totalDurationMs: Date.now() - startTime,
      };
    } catch (error) {
      lastError = error;

      // 判断是否可重试
      if (i >= opts.maxRetries) {
        break;
      }

      if (opts.retryOn && !opts.retryOn(error)) {
        break;
      }

      const delayMs = calculateDelay(i, opts);
      if (opts.onRetry) {
        opts.onRetry(error, i + 1, delayMs);
      }
      await sleep(delayMs);
    }
  }

  const totalDurationMs = Date.now() - startTime;
  const error = new Error(
    `Retry exhausted after ${attempt + 1} attempts (${totalDurationMs}ms): ${
      lastError instanceof Error ? lastError.message : String(lastError)
    }`,
  ) as Error & { cause: unknown; totalAttempts: number; totalDurationMs: number };
  error.cause = lastError;
  error.totalAttempts = attempt + 1;
  error.totalDurationMs = totalDurationMs;
  throw error;
}

/**
 * 带超时的异步执行器
 *
 * @param fn - 要执行的异步函数
 * @param timeoutMs - 超时毫秒数
 * @param timeoutMessage - 超时错误消息
 * @returns 函数执行结果
 * @throws 超时或函数错误
 */
export async function withTimeout<T>(
  fn: () => Promise<T>,
  timeoutMs: number,
  timeoutMessage = 'Operation timed out',
): Promise<T> {
  let timeoutHandle: NodeJS.Timeout | undefined;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutHandle = setTimeout(
      () => reject(new Error(`${timeoutMessage} (${timeoutMs}ms)`)),
      timeoutMs,
    );
  });

  try {
    return await Promise.race([fn(), timeoutPromise]);
  } finally {
    if (timeoutHandle !== undefined) {
      clearTimeout(timeoutHandle);
    }
  }
}

/**
 * 带重试和超时的异步执行器（组合）
 *
 * @param fn - 要执行的异步函数
 * @param options - 重试配置
 * @param timeoutMs - 每次尝试的超时毫秒数
 * @returns 重试结果
 */
export async function withRetryAndTimeout<T>(
  fn: () => Promise<T>,
  options?: Partial<RetryOptions>,
  timeoutMs?: number,
): Promise<RetryResult<T>> {
  return withRetry(
    () => (timeoutMs ? withTimeout(fn, timeoutMs) : fn()),
    options,
  );
}
