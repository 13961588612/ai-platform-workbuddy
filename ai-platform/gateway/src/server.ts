/**
 * server.ts — Fastify 服务器启动
 *
 * 配置和启动 Fastify 服务器，包括：
 * - CORS 配置
 * - WebSocket 插件
 * - 路由注册（健康检查、WebSocket、API 路由）
 * - 中间件注册（认证、限流、日志）
 * - 优雅关闭
 *
 * @module server
 */

import Fastify, {
  type FastifyInstance,
  type FastifyRequest,
  type FastifyReply,
} from 'fastify';
import { randomUUID } from 'node:crypto';
import cors from '@fastify/cors';
import websocket, { type WebSocket } from '@fastify/websocket';
import type { Redis } from 'ioredis';
import { logger, registerLoggerMiddleware } from './middleware/logger.js';
import { registerAuthMiddleware, type AuthConfig, type JwtClaims } from './middleware/auth.js';
import { registerRateLimitMiddleware } from './middleware/rateLimit.js';
import { WecomH5Adapter } from './adapters/wecom/WecomH5Adapter.js';
import { WecomBotAdapter, type WecomBotAdapterConfig } from './adapters/wecom/WecomBotAdapter.js';
import { H5Adapter } from './adapters/h5/H5Adapter.js';
import { MessageRouter } from './router/MessageRouter.js';
import { EventTransformer } from './router/EventTransformer.js';
import { ChannelResolver } from './router/ChannelResolver.js';
import { getCapabilityRegistry } from './channels/CapabilityRegistry.js';

// ============================================================================
// 类型定义
// ============================================================================

/** Gateway 服务器配置 */
export interface GatewayServerConfig {
  /** 监听端口 */
  port: number;
  /** 监听地址 */
  host: string;
  /** CORS 允许的源 */
  corsOrigins: string[];
  /** 认证配置 */
  auth: AuthConfig;
  /** 企业微信 H5 配置 */
  wecomH5: {
    corpId: string;
    agentId: string;
    corpSecret: string;
    apiBaseUrl: string;
  };
  /** 企业微信 Bot 配置 */
  wecomBot: WecomBotAdapterConfig;
  /** 后端 Agent Core API URL */
  agentCoreApiUrl: string;
}

// ============================================================================
// 服务器创建
// ============================================================================

/**
 * 创建并配置 Fastify 服务器
 *
 * @param redis - Redis 客户端
 * @param config - 服务器配置
 * @returns 配置好的 Fastify 实例和适配器
 */
export async function createServer(
  redis: Redis,
  config: GatewayServerConfig,
): Promise<{
  app: FastifyInstance;
  wecomH5Adapter: WecomH5Adapter;
  wecomBotAdapter: WecomBotAdapter;
  h5Adapter: H5Adapter;
  messageRouter: MessageRouter;
  eventTransformer: EventTransformer;
}> {
  // 创建 Fastify 实例
  const app = Fastify({
    logger: false, // 使用自定义 pino 日志
    genReqId: () => randomUUID(),
    trustProxy: true,
    bodyLimit: 1024 * 1024, // 1MB
  });

  // ===== 注册插件 =====

  // CORS
  await app.register(cors, {
    origin: config.corsOrigins,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization', 'X-Trace-Id', 'X-Channel'],
    credentials: true,
  });

  // WebSocket
  await app.register(websocket, {
    options: {
      maxPayload: 1024 * 1024, // 1MB
    },
  });

  // ===== 注册中间件 =====

  // 日志中间件
  registerLoggerMiddleware(app);

  // 认证中间件
  registerAuthMiddleware(app, config.auth);

  // 限流中间件
  await registerRateLimitMiddleware(app, redis);

  // ===== 创建适配器 =====

  const wecomH5Adapter = new WecomH5Adapter({
    corpId: config.wecomH5.corpId,
    agentId: config.wecomH5.agentId,
    corpSecret: config.wecomH5.corpSecret,
    apiBaseUrl: config.wecomH5.apiBaseUrl,
  });

  const wecomBotAdapter = new WecomBotAdapter(config.wecomBot);

  const h5Adapter = new H5Adapter();

  // 创建消息路由器和事件转换器
  const messageRouter = new MessageRouter(redis);
  const eventTransformer = new EventTransformer();

  // ===== 注册路由 =====

  registerRoutes(
    app,
    redis,
    wecomH5Adapter,
    wecomBotAdapter,
    h5Adapter,
    messageRouter,
    eventTransformer,
    config,
  );

  logger.info(
    { port: config.port, host: config.host },
    'Gateway server created',
  );

  return {
    app,
    wecomH5Adapter,
    wecomBotAdapter,
    h5Adapter,
    messageRouter,
    eventTransformer,
  };
}

// ============================================================================
// 路由注册
// ============================================================================

/**
 * 注册所有 API 路由
 */
function registerRoutes(
  app: FastifyInstance,
  _redis: Redis,
  wecomH5Adapter: WecomH5Adapter,
  wecomBotAdapter: WecomBotAdapter,
  h5Adapter: H5Adapter,
  messageRouter: MessageRouter,
  eventTransformer: EventTransformer,
  config: GatewayServerConfig,
): void {
  // ===== 健康检查 =====

  app.get('/health', async (_req: FastifyRequest, reply: FastifyReply) => {
    return reply.send({
      code: 0,
      data: {
        status: 'healthy',
        service: 'ai-platform-gateway',
        timestamp: new Date().toISOString(),
        uptime: process.uptime(),
        connections: {
          wecomH5: wecomH5Adapter.getConnectionCount(),
          h5: h5Adapter.getConnectionCount(),
          wecomBot: wecomBotAdapter.isConnected() ? 1 : 0,
        },
      },
      message: 'ok',
      traceId: _req.id,
    });
  });

  app.get('/health/live', async (_req: FastifyRequest, reply: FastifyReply) => {
    return reply.send({ code: 0, data: { status: 'alive' }, message: 'ok', traceId: _req.id });
  });

  app.get('/health/ready', async (req: FastifyRequest, reply: FastifyReply) => {
    const botConnected = wecomBotAdapter.isConnected();
    const ready = true; // 可根据实际依赖检查调整
    return reply.code(ready ? 200 : 503).send({
      code: ready ? 0 : 5001,
      data: { ready, botConnected },
      message: ready ? 'ready' : 'not ready',
      traceId: req.id,
    });
  });

  // ===== 渠道能力查询 =====

  app.get('/api/channels/capabilities', async (req: FastifyRequest, reply: FastifyReply) => {
    const registry = getCapabilityRegistry();
    return reply.send({
      code: 0,
      data: registry.getMatrixSummary(),
      message: 'ok',
      traceId: req.id,
    });
  });

  // ===== 企业微信 H5 JS-SDK 鉴权 =====

  app.post(
    '/auth/wecom/js-sdk-config',
    async (req: FastifyRequest, reply: FastifyReply) => {
      const body = req.body as { url?: string };
      if (body?.url == null) {
        return reply.code(400).send({
          code: 1001,
          data: null,
          message: 'url is required',
          traceId: req.id,
        });
      }

      try {
        const jsSdkConfig = await wecomH5Adapter.getJsSdkConfig(body.url);
        return reply.send({
          code: 0,
          data: jsSdkConfig,
          message: 'ok',
          traceId: req.id,
        });
      } catch (error) {
        logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Failed to get JS-SDK config',
        );
        return reply.code(500).send({
          code: 5000,
          data: null,
          message: 'Failed to get JS-SDK config',
          traceId: req.id,
        });
      }
    },
  );

  // ===== H5 WebSocket 端点 =====

  app.get('/ws/chat', { websocket: true }, async (socket: WebSocket, req) => {
    const user = (req as unknown as { user?: JwtClaims }).user;
    if (user == null) {
      socket.close(4001, 'Authentication required');
      return;
    }

    const query = req.query as { sessionId?: string };
    const clientSessionId =
      typeof query.sessionId === 'string' && query.sessionId.length > 0
        ? query.sessionId
        : ChannelResolver.generateSessionId('web');

    h5Adapter.registerWsConnection(clientSessionId, socket);

    logger.info(
      { sessionId: clientSessionId, userId: user.userId },
      'H5 WebSocket connection established',
    );

    socket.on('message', async (data: Buffer) => {
      try {
        const message = JSON.parse(data.toString()) as {
          type?: string;
          content?: string;
          sessionId?: string;
          agentId?: string;
          messageType?: string;
          metadata?: Record<string, unknown>;
        };

        if (message.type === 'ping') {
          return;
        }

        if (message.type === 'session.create' || message.type === 'session.close') {
          return;
        }

        if (message.type === 'chat' || message.content != null) {
          const inbound = MessageRouter.createInboundMessage({
            userId: user.userId,
            channel: 'h5',
            content: message.content ?? '',
            sessionId: message.sessionId ?? clientSessionId,
            agentId: message.agentId,
            traceId: String(req.id),
            messageType: message.messageType,
            metadata: message.metadata,
          });
          await messageRouter.route(inbound);
        }
      } catch (error) {
        logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Error processing WebSocket message',
        );
        socket.send(
          JSON.stringify({
            type: 'error',
            message: 'Failed to process message',
          }),
        );
      }
    });

    socket.on('close', () => {
      h5Adapter.unregisterWsConnection(clientSessionId);
      logger.info({ sessionId: clientSessionId }, 'H5 WebSocket connection closed');
    });
  });

  // ===== 企业微信 H5 WebSocket 端点 =====

  app.get('/ws/wecom-h5/chat', { websocket: true }, async (socket: WebSocket, req) => {
    const user = (req as unknown as { user?: JwtClaims }).user;
    if (user == null) {
      socket.close(4001, 'Authentication required');
      return;
    }

    const sessionId = ChannelResolver.generateSessionId('wecom-h5');
    wecomH5Adapter.registerConnection(sessionId, socket);

    logger.info(
      { sessionId, userId: user.userId },
      'Wecom H5 WebSocket connection established',
    );

    socket.on('message', async (data: Buffer) => {
      try {
        const message = JSON.parse(data.toString()) as {
          content: string;
          messageType?: string;
          metadata?: Record<string, unknown>;
        };

        const inbound = wecomH5Adapter.receive(message, user.userId, sessionId);
        await messageRouter.route(inbound);
      } catch (error) {
        logger.error(
          { error: error instanceof Error ? error.message : String(error) },
          'Error processing Wecom H5 WebSocket message',
        );
      }
    });

    socket.on('close', () => {
      wecomH5Adapter.unregisterConnection(sessionId);
      logger.info({ sessionId }, 'Wecom H5 WebSocket connection closed');
    });
  });

  // ===== 消息发送 API（REST 兜底） =====

  app.post(
    '/api/messages/send',
    async (req: FastifyRequest, reply: FastifyReply) => {
      const user = (req as unknown as { user: JwtClaims }).user;
      const body = req.body as {
        content: string;
        sessionId?: string;
        channel?: string;
        messageType?: string;
      };

      if (body?.content == null) {
        return reply.code(400).send({
          code: 1001,
          data: null,
          message: 'content is required',
          traceId: req.id,
        });
      }

      const channel = body.channel ?? 'h5';
      const inbound = MessageRouter.createInboundMessage({
        userId: user.userId,
        channel,
        content: body.content,
        messageType: body.messageType ?? 'text',
        sessionId: body.sessionId,
        traceId: req.id,
      });

      const result = await messageRouter.route(inbound);

      return reply.send({
        code: 0,
        data: {
          messageId: result.messageId,
          sessionId: result.sessionId,
          streamKey: result.streamKey,
          agentId: result.agentId,
        },
        message: 'Message routed',
        traceId: req.id,
      });
    },
  );

  // ===== 企业微信 Bot 回调 URL 验证 =====

  app.get(
    '/wecom/bot/callback',
    async (req: FastifyRequest, reply: FastifyReply) => {
      const query = req.query as {
        msg_signature?: string;
        timestamp?: string;
        nonce?: string;
        echostr?: string;
      };

      // 企业微信回调 URL 验证
      // 实际验证逻辑使用 WecomCrypto.verifySignature
      if (query.echostr != null) {
        logger.info('Wecom Bot callback URL verification');
        return reply.send(query.echostr);
      }

      return reply.code(200).send();
    },
  );

  // ===== 事件流 SSE 端点 =====

  app.get('/api/events/stream', async (req: FastifyRequest, reply: FastifyReply) => {
    const user = (req as unknown as { user: JwtClaims }).user;
    const query = req.query as { sessionId?: string };

    if (query.sessionId == null) {
      return reply.code(400).send({
        code: 1001,
        data: null,
        message: 'sessionId is required',
        traceId: req.id,
      });
    }

    // 注册 SSE 连接
    h5Adapter.registerSseConnection(query.sessionId, reply);

    // 设置超时清理
    req.raw.on('close', () => {
      h5Adapter.unregisterSseConnection(query.sessionId!);
      logger.info({ sessionId: query.sessionId }, 'SSE connection closed');
    });

    // 保持连接
    reply.raw.write(': connected\n\n');
  });

  logger.info('All routes registered');
}

// ============================================================================
// 服务器启动和关闭
// ============================================================================

/**
 * 启动 Gateway 服务器
 *
 * @param app - Fastify 实例
 * @param config - 服务器配置
 * @returns 服务器地址
 */
export async function startServer(
  app: FastifyInstance,
  config: { port: number; host: string },
): Promise<string> {
  const address = await app.listen({
    port: config.port,
    host: config.host,
  });

  logger.info(
    { address, port: config.port, host: config.host },
    'Gateway server started',
  );

  return address;
}

/**
 * 优雅关闭服务器
 *
 * @param app - Fastify 实例
 * @param adapters - 需要关闭的适配器
 */
export async function shutdownServer(
  app: FastifyInstance,
  adapters: {
    wecomH5Adapter?: WecomH5Adapter;
    wecomBotAdapter?: WecomBotAdapter;
    h5Adapter?: H5Adapter;
  },
): Promise<void> {
  logger.info('Shutting down Gateway server...');

  // 关闭适配器连接
  adapters.wecomH5Adapter?.closeAllConnections();
  adapters.wecomBotAdapter?.stop();
  adapters.h5Adapter?.closeAllConnections();

  // 关闭 Fastify
  await app.close();

  logger.info('Gateway server shut down complete');
}
