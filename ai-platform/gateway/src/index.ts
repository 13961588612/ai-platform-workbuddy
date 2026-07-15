/**
 * index.ts — Gateway 入口
 *
 * 启动 Message Gateway 服务：
 * 1. 从环境变量加载配置
 * 2. 创建 Redis 连接
 * 3. 创建并启动 Fastify 服务器
 * 4. 启动企业微信 Bot WebSocket 长连接
 * 5. 注册优雅关闭钩子
 *
 * @module index
 */

import 'dotenv/config';

import Redis from 'ioredis';
import { logger } from './middleware/logger.js';
import {
  createServer,
  startServer,
  shutdownServer,
  type GatewayServerConfig,
} from './server.js';
import { StreamConsumer } from './queue/redisStream.js';
import type { InboundMessage } from './queue/redisStream.js';
import { EventTransformer } from './router/EventTransformer.js';
import {
  parseBackendAgentEvent,
  toGatewayChannel,
} from './router/agentEventParser.js';

// ============================================================================
// 配置加载
// ============================================================================

/**
 * 从环境变量加载 Gateway 配置
 *
 * 环境变量：
 * - GATEWAY_PORT: 监听端口（默认 8080）
 * - GATEWAY_HOST: 监听地址（默认 0.0.0.0）
 * - REDIS_URL: Redis 连接 URL
 * - JWT_SECRET: JWT 签名密钥
 * - JWT_ISSUER: JWT 签发者（默认 ai-platform）
 * - WECOM_CORP_ID: 企业微信 CorpID
 * - WECOM_AGENT_ID: 企业微信应用 AgentID
 * - WECOM_SECRET: 企业微信应用 Secret
 * - WECOM_API_BASE_URL: 企业微信 API 基础 URL
 * - WECOM_BOT_CALLBACK_TOKEN: 企业微信 Bot 回调 Token（URL 回调模式）
 * - WECOM_BOT_ID: 智能机器人 BotID（长连接鉴权）
 * - WECOM_BOT_SECRET: 智能机器人长连接 Secret
 * - WECOM_BOT_WS_URL: 可选，默认 wss://openws.work.weixin.qq.com
 * - AGENT_CORE_API_URL: Agent Core API URL
 * - CORS_ORIGINS: CORS 允许的源（逗号分隔）
 *
 * @returns Gateway 配置
 */
function loadConfig(): GatewayServerConfig {
  // 核心必填：Redis + JWT。企微自建应用凭证仅 H5 需要，可留空。
  const requiredEnvVars = ['REDIS_URL', 'JWT_SECRET'];
  for (const envVar of requiredEnvVars) {
    if (process.env[envVar] == null || process.env[envVar] === '') {
      throw new Error(`Missing required environment variable: ${envVar}`);
    }
  }

  return {
    port: parseInt(process.env['GATEWAY_PORT'] ?? '8080', 10),
    host: process.env['GATEWAY_HOST'] ?? '0.0.0.0',
    corsOrigins: (process.env['CORS_ORIGINS'] ?? '*').split(',').map((s) => s.trim()),
    auth: {
      jwtSecret: process.env['JWT_SECRET']!,
      jwtIssuer: process.env['JWT_ISSUER'] ?? 'ai-platform',
      accessTokenTtl: parseInt(process.env['JWT_ACCESS_TOKEN_TTL'] ?? '7200', 10),
      wecomCallbackToken: process.env['WECOM_BOT_CALLBACK_TOKEN'] ?? '',
      wecomCallbackAesKey: process.env['WECOM_BOT_CALLBACK_ENCODING_AES_KEY'] ?? '',
    },
    wecomH5: {
      corpId: process.env['WECOM_CORP_ID'] ?? '',
      agentId: process.env['WECOM_AGENT_ID'] ?? '',
      corpSecret: process.env['WECOM_SECRET'] ?? '',
      apiBaseUrl: process.env['WECOM_API_BASE_URL'] ?? 'https://qyapi.weixin.qq.com',
    },
    wecomBot: {
      botId: process.env['WECOM_BOT_ID'] ?? '',
      secret: process.env['WECOM_BOT_SECRET'] ?? '',
      wsUrl: process.env['WECOM_BOT_WS_URL'] ?? 'wss://openws.work.weixin.qq.com',
      heartbeatIntervalSec: parseInt(process.env['WECOM_BOT_HEARTBEAT_INTERVAL'] ?? '30', 10),
      heartbeatTimeoutCount: 3,
      maxReconnectAttempts: 10,
      initialReconnectDelayMs: 1000,
      maxReconnectDelayMs: 30000,
      reconnectBackoffMultiplier: 2,
      subscribeTimeoutMs: parseInt(process.env['WECOM_BOT_SUBSCRIBE_TIMEOUT_MS'] ?? '10000', 10),
      sourceName: process.env['WECOM_BOT_SOURCE_NAME'] ?? 'AI智能助手',
      ...(process.env['WECOM_BOT_SOURCE_ICON_URL'] != null
        ? { sourceIconUrl: process.env['WECOM_BOT_SOURCE_ICON_URL'] }
        : {}),
    },
    agentCoreApiUrl: process.env['AGENT_CORE_API_URL'] ?? 'http://backend:8000',
  };
}

// ============================================================================
// Redis 连接
// ============================================================================

/**
 * 创建 Redis 连接
 *
 * @param redisUrl - Redis 连接 URL
 * @returns Redis 客户端
 */
function createRedisConnection(redisUrl: string): Redis {
  const redis = new Redis(redisUrl, {
    maxRetriesPerRequest: 3,
    enableReadyCheck: true,
    retryStrategy: (times: number) => {
      if (times > 10) {
        logger.error(
          { times },
          'Redis connection retry limit exceeded',
        );
        return null;
      }
      const delay = Math.min(times * 500, 5000);
      logger.warn(
        { times, delayMs: delay },
        'Redis connection retrying',
      );
      return delay;
    },
    reconnectOnError: (error: Error) => {
      const targetErrors = ['READONLY', 'ECONNRESET', 'ETIMEDOUT'];
      return targetErrors.some((e) => error.message.includes(e));
    },
  });

  redis.on('connect', () => {
    logger.info('Redis connected');
  });

  redis.on('error', (error: Error) => {
    logger.error({ error: error.message }, 'Redis connection error');
  });

  redis.on('close', () => {
    logger.warn('Redis connection closed');
  });

  return redis;
}

// ============================================================================
// 主函数
// ============================================================================

/**
 * Gateway 主入口
 */
async function main(): Promise<void> {
  let redis: Redis | null = null;
  let isShuttingDown = false;

  try {
    // 加载配置
    const config = loadConfig();
    logger.info(
      {
        port: config.port,
        host: config.host,
        agentCoreApiUrl: config.agentCoreApiUrl,
      },
      'Starting AI Platform Gateway',
    );

    // 业务连接（路由 / 亲和查询 / HTTP 侧）
    redis = createRedisConnection(process.env['REDIS_URL']!);
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Redis connection timeout'));
      }, 10000);

      redis!.on('ready', () => {
        clearTimeout(timeout);
        resolve();
      });
      redis!.on('error', (error) => {
        clearTimeout(timeout);
        reject(error);
      });
    });

    // 消费连接必须独立：XREADGROUP BLOCK 会占满单连接，拖慢 GET/XADD（实测 route 可达 10s+）
    const redisConsumer = createRedisConnection(process.env['REDIS_URL']!);
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error('Redis consumer connection timeout'));
      }, 10000);
      redisConsumer.on('ready', () => {
        clearTimeout(timeout);
        resolve();
      });
      redisConsumer.on('error', (error) => {
        clearTimeout(timeout);
        reject(error);
      });
    });

    // 创建服务器和适配器
    const {
      app,
      wecomH5Adapter,
      wecomBotAdapter,
      h5Adapter,
      messageRouter,
      eventTransformer,
    } = await createServer(redis, config);

    // 启动 HTTP 服务器
    await startServer(app, { port: config.port, host: config.host });

    // 启动企业微信 Bot WebSocket 长连接（BotID + Secret → aibot_subscribe）
    if (config.wecomBot.botId.length > 0 && config.wecomBot.secret.length > 0) {
      try {
        await wecomBotAdapter.start(async (inboundMessage: InboundMessage) => {
          await messageRouter.route(inboundMessage);
        });
        logger.info({ botId: config.wecomBot.botId }, 'Wecom Bot adapter started');
      } catch (error) {
        logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Failed to start Wecom Bot adapter, continuing without Bot',
        );
      }
    } else {
      logger.warn(
        'WECOM_BOT_ID / WECOM_BOT_SECRET not configured, skipping Bot adapter startup',
      );
    }

    // 启动事件流消费者（消费 Agent Core 返回的事件）— 使用独立 Redis 连接
    const eventConsumer = new StreamConsumer(
      redisConsumer,
      'gateway-event-group',
      `gateway-events-${process.pid}`,
    );
    await eventConsumer.start('stream:agent:events', async (message: InboundMessage) => {
      try {
        if (message.eventJson == null || message.eventJson.length === 0) {
          return;
        }

        const event = parseBackendAgentEvent(message.eventJson);
        const channel = toGatewayChannel(message.channel);

        logger.info(
          {
            sessionId: message.sessionId,
            channel,
            eventType: event.type,
            perfPhase: 'gw_event',
          },
          'Agent event for channel',
        );

        // 企微 Bot：用 aibot_respond_msg 流式更新（收到消息时已回「思考中...」）
        if (channel === 'wecom-bot') {
          if (event.type === 'text.delta' && event.content != null) {
            await wecomBotAdapter.onAgentTextDelta(message.sessionId, event.content);
          } else if (event.type === 'error') {
            await wecomBotAdapter.onAgentError(
              message.sessionId,
              event.errorMessage ?? event.errorCode ?? '处理出错',
            );
          } else if (event.type === 'done') {
            await wecomBotAdapter.onAgentDone(message.sessionId);
          }
          return;
        }

        const channelMessage = eventTransformer.transform(event, channel);

        if (channel === 'h5' && channelMessage.eventData != null) {
          await h5Adapter.send(channelMessage.eventData, message.sessionId);
        } else if (channel === 'wecom-h5' && channelMessage.eventData != null) {
          await wecomH5Adapter.send(channelMessage.eventData, message.sessionId);
        }
      } catch (error) {
        logger.error(
          {
            error: error instanceof Error ? error.message : String(error),
            sessionId: message.sessionId,
          },
          'Error processing event from stream',
        );
      }
    });

    logger.info(
      {
        port: config.port,
        wecomH5Connections: wecomH5Adapter.getConnectionCount(),
        h5Connections: h5Adapter.getConnectionCount(),
        botConnected: wecomBotAdapter.isConnected(),
      },
      'AI Platform Gateway is running',
    );

    // ===== 优雅关闭 =====

    const gracefulShutdown = async (signal: string): Promise<void> => {
      if (isShuttingDown) {
        logger.warn('Shutdown already in progress, ignoring signal');
        return;
      }
      isShuttingDown = true;

      logger.info({ signal }, 'Received shutdown signal, shutting down gracefully');

      // 停止事件消费者
      eventConsumer.stop();

      // 关闭服务器和适配器
      await shutdownServer(app, {
        wecomH5Adapter,
        wecomBotAdapter,
        h5Adapter,
      });

      // 关闭 Redis（业务连接 + 消费连接）
      if (redis != null) {
        redis.disconnect();
      }
      redisConsumer.disconnect();

      logger.info('Gateway shutdown complete');
      process.exit(0);
    };

    process.on('SIGTERM', () => void gracefulShutdown('SIGTERM'));
    process.on('SIGINT', () => void gracefulShutdown('SIGINT'));

    process.on('uncaughtException', (error: Error) => {
      logger.fatal(
        { error: error.message, stack: error.stack },
        'Uncaught exception',
      );
      void gracefulShutdown('uncaughtException');
    });

    process.on('unhandledRejection', (reason: unknown) => {
      logger.fatal(
        { reason: reason instanceof Error ? reason.message : String(reason) },
        'Unhandled rejection',
      );
      void gracefulShutdown('unhandledRejection');
    });
  } catch (error) {
    logger.fatal(
      { error: error instanceof Error ? error.message : String(error), stack: error instanceof Error ? error.stack : undefined },
      'Failed to start Gateway',
    );
    if (redis != null) {
      redis.disconnect();
    }
    process.exit(1);
  }
}

// 启动
main().catch((error) => {
  logger.fatal(
    { error: error instanceof Error ? error.message : String(error) },
    'Fatal error in main',
  );
  process.exit(1);
});
