/**
 * EventTransformer.ts — EventTransformer 能力感知降级器
 *
 * 将 Agent 产生的统一 AgentEvent 流转换为各渠道的原生消息格式。
 * 核心逻辑是能力感知降级：
 * - H5 渠道：原样透传（支持流式 + Generative UI）
 * - Bot 渠道：依据 ChannelCapability 降级为 template_card
 *
 * 降级映射规则（架构 8.8 节）：
 * | AgentEvent | H5 渠道 | Bot 渠道 |
 * |------------|---------|---------|
 * | text.delta | SSE 流式推送 | 缓冲累积 → text_notice |
 * | ui.render | 原样透传 | 匹配卡片类型，否则降级为 text_notice |
 * | approval.request | 弹窗审批 | button_interaction |
 * | tool.result | 工具结果卡片 | text_notice 摘要 |
 * | error | 错误提示 | text_notice 错误信息 |
 *
 * @module router/EventTransformer
 */

import type {
  AgentEvent,
  ChannelCapability,
  ChannelType,
} from '../channels/ChannelCapability.js';
import { getCapabilityRegistry } from '../channels/CapabilityRegistry.js';
import type { TemplateCard } from '../adapters/wecom/WecomBotCardBuilder.js';
import { BotEventMapper, type BotMappingResult, type ApprovalDetail } from './BotEventMapper.js';
import { logger } from '../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 转换后的渠道消息 */
export interface ChannelMessage {
  /** 消息类型 */
  type: 'stream' | 'card' | 'approval' | 'tool' | 'error' | 'done';
  /** 目标渠道 */
  channel: ChannelType;
  /** 原始事件类型 */
  eventType: string;
  /** H5/Web 渠道：透传的事件数据 */
  eventData?: AgentEvent;
  /** Bot 渠道：转换后的 template_card */
  card?: TemplateCard;
  /** 是否为降级转换 */
  degraded: boolean;
  /** 追踪 ID */
  traceId?: string;
}

// ============================================================================
// EventTransformer
// ============================================================================

/**
 * EventTransformer 能力感知降级器
 *
 * Gateway 层核心组件，负责将 Agent 产生的统一 AgentEvent 流
 * 转换为各渠道的原生消息格式。
 *
 * 核心方法：
 * - transform(event, channel): 通用转换入口
 * - toH5Event(event): H5 渠道转换（原样透传）
 * - toBotCard(event): Bot 渠道转换（降级为卡片）
 * - toWecomAppMessage(event): 企业微信应用消息转换
 * - degradeByCapability(event, capability): 能力感知降级
 * - flushBufferedEvents(channel): 刷新缓冲事件（Bot 渠道使用）
 */
export class EventTransformer {
  private readonly capabilityRegistry = getCapabilityRegistry();
  private readonly botEventMapper: BotEventMapper;

  constructor(botEventMapper?: BotEventMapper) {
    this.botEventMapper = botEventMapper ?? new BotEventMapper();
  }

  /**
   * 通用转换入口
   *
   * 根据渠道类型和渠道能力自动选择转换策略：
   * - H5 渠道（supportsStreaming=true）：原样透传为流式事件
   * - Bot 渠道（supportsStreaming=false）：降级为 template_card
   *
   * @param event - Agent 事件
   * @param channel - 目标渠道
   * @returns 转换后的渠道消息
   */
  transform(event: AgentEvent, channel: ChannelType): ChannelMessage {
    const capability = this.capabilityRegistry.getCapability(channel);

    // 检查渠道是否能直接渲染该事件
    if (capability.canRender(event.type)) {
      // 渠道原生支持，透传
      return this.toH5Event(event, channel);
    }

    // 渠道不支持，执行降级
    return this.degradeByCapability(event, capability);
  }

  /**
   * 转换为 H5/Web 渠道事件（原样透传）
   *
   * H5 渠道支持流式输出和 Generative UI，AgentEvent 原样透传。
   *
   * @param event - Agent 事件
   * @param channel - 目标渠道（默认 h5）
   * @returns 透传的渠道消息
   */
  toH5Event(event: AgentEvent, channel: ChannelType = 'h5'): ChannelMessage {
    let type: ChannelMessage['type'] = 'stream';

    switch (event.type) {
      case 'text.delta':
        type = 'stream';
        break;
      case 'ui.render':
        type = 'card';
        break;
      case 'approval.request':
        type = 'approval';
        break;
      case 'tool.call':
      case 'tool.result':
        type = 'tool';
        break;
      case 'error':
        type = 'error';
        break;
      case 'done':
        type = 'done';
        break;
    }

    return {
      type,
      channel,
      eventType: event.type,
      eventData: event,
      degraded: false,
    };
  }

  /**
   * 转换为企业微信应用消息（通知引导 H5）
   *
   * 当 Bot 渠道需要引导用户打开 H5 时，生成应用消息内容。
   *
   * @param event - Agent 事件
   * @returns 应用消息文本内容
   */
  toWecomAppMessage(event: AgentEvent): { title: string; content: string } {
    switch (event.type) {
      case 'text.delta':
        return {
          title: 'AI助手回复',
          content: event.content ?? '',
        };

      case 'ui.render':
        return {
          title: event.component ?? '动态内容',
          content: '请打开 H5 页面查看完整内容',
        };

      case 'approval.request':
        return {
          title: '审批通知',
          content: event.detail?.['description'] as string ?? '您有一条待审批事项，请及时处理',
        };

      case 'tool.result':
        return {
          title: `工具执行完成: ${event.toolName ?? ''}`,
          content: '请打开 H5 页面查看详细结果',
        };

      case 'error':
        return {
          title: '处理出错',
          content: `错误码: ${event.errorCode ?? 'UNKNOWN'}\n错误信息: ${event.errorMessage ?? '未知错误'}`,
        };

      case 'done':
        return {
          title: '处理完成',
          content: 'AI助手已完成处理',
        };

      default:
        return {
          title: '通知',
          content: '您有一条新消息',
        };
    }
  }

  /**
   * 转换为 Bot 渠道 template_card
   *
   * 委托 BotEventMapper 完成具体映射。
   *
   * @param event - Agent 事件
   * @param cardType - 指定卡片类型（可选）
   * @returns 包含 template_card 的渠道消息
   */
  toBotCard(event: AgentEvent): ChannelMessage {
    let mappingResult: BotMappingResult;

    switch (event.type) {
      case 'text.delta':
        // 缓冲 text.delta
        this.botEventMapper.bufferTextDelta(event);
        // 不立即返回卡片，等待 done 或 flushBufferedEvents
        return {
          type: 'stream',
          channel: 'wecom-bot',
          eventType: event.type,
          degraded: true,
        };

      case 'ui.render':
        mappingResult = this.botEventMapper.mapUIRender(
          event.component ?? 'Unknown',
          event.props ?? {},
        );
        break;

      case 'approval.request': {
        const detail: ApprovalDetail = {
          title: (event.detail?.['title'] as string) ?? '审批请求',
          description: (event.detail?.['description'] as string) ?? '请处理以下审批事项',
          skillId: event.skillId ?? '',
          approvalId: (event.detail?.['approvalId'] as string) ?? '',
        };
        mappingResult = this.botEventMapper.mapApprovalRequest(detail);
        break;
      }

      case 'tool.call':
        mappingResult = this.botEventMapper.mapToolCall(event.toolName ?? '');
        break;

      case 'tool.result':
        mappingResult = this.botEventMapper.mapToolResult(
          event.toolName ?? '',
          event.result ?? {},
        );
        break;

      case 'error':
        mappingResult = this.botEventMapper.mapError(
          event.errorCode ?? 'UNKNOWN',
          event.errorMessage ?? '未知错误',
        );
        break;

      case 'done':
        // done 事件触发缓冲文本刷新
        if (this.botEventMapper.hasBufferedText()) {
          mappingResult = this.botEventMapper.mapTextDelta();
        } else {
          // 无缓冲文本，返回 done 消息
          return {
            type: 'done',
            channel: 'wecom-bot',
            eventType: event.type,
            degraded: false,
          };
        }
        break;

      default:
        // 未知事件类型，降级为错误卡片
        mappingResult = this.botEventMapper.mapError(
          'UNKNOWN_EVENT',
          `无法处理的事件类型: ${event.type}`,
        );
    }

    return {
      type: 'card',
      channel: 'wecom-bot',
      eventType: event.type,
      card: mappingResult.card,
      degraded: mappingResult.degraded,
    };
  }

  /**
   * 能力感知降级
   *
   * 根据渠道能力声明，将不支持的事件类型降级为渠道可渲染的格式。
   *
   * @param event - Agent 事件
   * @param capability - 渠道能力声明
   * @returns 降级后的渠道消息
   */
  degradeByCapability(
    event: AgentEvent,
    capability: ChannelCapability,
  ): ChannelMessage {
    logger.debug(
      {
        eventType: event.type,
        channelType: capability.channelType,
        supportsStreaming: capability.supportsStreaming,
        supportsCustomUI: capability.supportsCustomUI,
      },
      'Degrading event by channel capability',
    );

    // Bot 渠道降级
    if (capability.channelType === 'wecom-bot') {
      return this.toBotCard(event);
    }

    // H5 渠道不需要降级（支持所有事件类型）
    return this.toH5Event(event, capability.channelType);
  }

  /**
   * 刷新缓冲事件
   *
   * Bot 渠道使用：将缓冲的 text.delta 合并为 text_notice 卡片一次性发送。
   * 通常在 done 事件或会话结束时调用。
   *
   * @param channel - 目标渠道
   * @returns 刷新后的渠道消息，无缓冲时返回 null
   */
  flushBufferedEvents(channel: ChannelType): ChannelMessage | null {
    if (channel !== 'wecom-bot') {
      return null;
    }

    if (!this.botEventMapper.hasBufferedText()) {
      return null;
    }

    const mappingResult = this.botEventMapper.mapTextDelta();

    return {
      type: 'card',
      channel: 'wecom-bot',
      eventType: 'text.delta',
      card: mappingResult.card,
      degraded: true,
    };
  }

  /**
   * 重置状态（清空缓冲区）
   */
  reset(): void {
    this.botEventMapper.clearBuffer();
  }

  /**
   * 获取 BotEventMapper 实例（供外部调用卡片更新等方法）
   * @returns BotEventMapper 实例
   */
  getBotEventMapper(): BotEventMapper {
    return this.botEventMapper;
  }
}
