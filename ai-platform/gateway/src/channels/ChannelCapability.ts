/**
 * ChannelCapability.ts — 渠道能力声明接口
 *
 * 定义渠道能力的 11 维度声明，用于 EventTransformer 能力感知降级。
 * 三渠道（wecom-h5 / wecom-bot / h5）各自实现此接口。
 *
 * @module channels/ChannelCapability
 */

// ============================================================================
// 枚举定义
// ============================================================================

/** 渠道类型 */
export type ChannelType = 'wecom-h5' | 'wecom-bot' | 'h5';

/** Markdown 支持级别 */
export type MarkdownSupportLevel = 'full' | 'limited' | 'none';

/** AgentEvent 事件类型 */
export type AgentEventType =
  | 'text.delta'
  | 'tool.call'
  | 'tool.result'
  | 'ui.render'
  | 'approval.request'
  | 'error'
  | 'done';

/** 企业微信 Bot template_card 类型 */
export type TemplateCardType =
  | 'text_notice'
  | 'news_notice'
  | 'button_interaction'
  | 'vote_interaction'
  | 'multiple_interaction'
  | 'template_notice';

// ============================================================================
// AgentEvent 定义
// ============================================================================

/** Token 用量 */
export interface TokenUsage {
  /** 提示 Token 数 */
  prompt: number;
  /** 生成 Token 数 */
  completion: number;
  /** 总 Token 数 */
  total: number;
}

/** Agent 事件（统一流式协议） */
export interface AgentEvent {
  /** 事件类型 */
  type: AgentEventType;
  /** 文本内容（text.delta 使用） */
  content?: string;
  /** 工具名称（tool.call / tool.result 使用） */
  toolName?: string;
  /** 工具参数（tool.call 使用） */
  args?: Record<string, unknown>;
  /** 工具结果（tool.result 使用） */
  result?: Record<string, unknown>;
  /** UI 组件名称（ui.render 使用） */
  component?: string;
  /** UI 组件属性（ui.render 使用） */
  props?: Record<string, unknown>;
  /** Skill ID（approval.request 使用） */
  skillId?: string;
  /** 审批详情（approval.request 使用） */
  detail?: Record<string, unknown>;
  /** 错误码（error 使用） */
  errorCode?: string;
  /** 错误消息（error 使用） */
  errorMessage?: string;
  /** Token 用量（done 使用） */
  tokenUsage?: TokenUsage;
}

// ============================================================================
// 渠道能力接口
// ============================================================================

/**
 * 渠道能力声明接口（11 维度）
 *
 * 各渠道（wecom-h5 / wecom-bot / h5）实现此接口，
 * EventTransformer 根据 canRender() 和 getCardType() 进行能力感知降级。
 */
export interface ChannelCapability {
  /** 渠道类型 */
  readonly channelType: ChannelType;

  // ===== 能力维度 1-6（架构 8.9 节能力矩阵） =====

  /** 是否支持流式输出 */
  readonly supportsStreaming: boolean;
  /** 是否支持自定义 UI（Generative UI） */
  readonly supportsCustomUI: boolean;
  /** 支持的卡片类型列表（Bot 渠道为 6 种 template_card，H5 渠道为空） */
  readonly supportedCardTypes: TemplateCardType[];
  /** 是否支持文件上传 */
  readonly supportsFileUpload: boolean;
  /** 最大消息长度 */
  readonly maxMessageLength: number;
  /** Markdown 支持级别 */
  readonly markdownSupportLevel: MarkdownSupportLevel;

  // ===== 扩展能力维度 7-11 =====

  /** 是否支持快捷回复 */
  readonly supportsQuickReply: boolean;
  /** 是否支持轮播 */
  readonly supportsCarousel: boolean;
  /** 是否支持表单输入 */
  readonly supportsFormInput: boolean;
  /** 是否支持按钮交互 */
  readonly supportsButtons: boolean;

  // ===== 能力判断方法 =====

  /**
   * 判断该渠道是否能渲染指定事件类型
   * @param eventType - AgentEvent 事件类型
   * @returns 是否可渲染
   */
  canRender(eventType: AgentEventType): boolean;

  /**
   * 根据组件类型获取对应的卡片类型（Bot 渠道使用）
   * @param componentType - UI 组件类型名称
   * @returns 匹配的 template_card 类型，无法匹配时返回 'text_notice'
   */
  getCardType(componentType: string): TemplateCardType;
}

// ============================================================================
// 企业微信 H5 渠道能力
// ============================================================================

/** 企业微信 H5 渠道能力实现 */
export class WecomH5Capability implements ChannelCapability {
  readonly channelType: ChannelType = 'wecom-h5';
  readonly supportsStreaming = true;
  readonly supportsCustomUI = true;
  readonly supportedCardTypes: TemplateCardType[] = [];
  readonly supportsFileUpload = false;
  readonly maxMessageLength = 4096;
  readonly markdownSupportLevel: MarkdownSupportLevel = 'full';
  readonly supportsQuickReply = true;
  readonly supportsCarousel = true;
  readonly supportsFormInput = true;
  readonly supportsButtons = true;

  canRender(_eventType: AgentEventType): boolean {
    // H5 渠道支持所有事件类型（通过 CopilotKit Generative UI 渲染）
    return true;
  }

  getCardType(_componentType: string): TemplateCardType {
    // H5 渠道不使用卡片，返回默认值
    return 'text_notice';
  }
}

// ============================================================================
// 企业微信 Bot 渠道能力
// ============================================================================

/** 企业微信 Bot 渠道支持的 6 种 template_card */
const BOT_CARD_TYPES: TemplateCardType[] = [
  'text_notice',
  'news_notice',
  'button_interaction',
  'vote_interaction',
  'multiple_interaction',
  'template_notice',
];

/** 组件类型到卡片类型的映射规则 */
const COMPONENT_CARD_MAP: Record<string, TemplateCardType> = {
  // 表格/列表类 → text_notice
  table: 'text_notice',
  list: 'text_notice',
  datagrid: 'text_notice',
  leavereportcard: 'text_notice',
  // 图表/图片类 → news_notice
  chart: 'news_notice',
  saleschart: 'news_notice',
  image: 'news_notice',
  graph: 'news_notice',
  // 按钮/操作类 → button_interaction
  buttons: 'button_interaction',
  actionbuttons: 'button_interaction',
  actions: 'button_interaction',
  // 表单类 → multiple_interaction
  form: 'multiple_interaction',
  reportform: 'multiple_interaction',
  // 模板通知类 → template_notice
  notice: 'template_notice',
  notification: 'template_notice',
};

/** 企业微信 Bot 渠道能力实现 */
export class WecomBotCapability implements ChannelCapability {
  readonly channelType: ChannelType = 'wecom-bot';
  readonly supportsStreaming = false;
  readonly supportsCustomUI = false;
  readonly supportedCardTypes: TemplateCardType[] = [...BOT_CARD_TYPES];
  readonly supportsFileUpload = false;
  readonly maxMessageLength = 2048;
  readonly markdownSupportLevel: MarkdownSupportLevel = 'limited';
  readonly supportsQuickReply = false;
  readonly supportsCarousel = false;
  readonly supportsFormInput = true;
  readonly supportsButtons = true;

  canRender(eventType: AgentEventType): boolean {
    // Bot 渠道不支持流式输出和自定义 UI（需降级为卡片）
    switch (eventType) {
      case 'text.delta':
        // 不支持流式，需缓冲后发送
        return false;
      case 'ui.render':
        // 不支持自定义 UI，需降级为卡片
        return false;
      case 'tool.call':
        // 工具调用状态不直接渲染
        return false;
      default:
        // tool.result / approval.request / error / done 可渲染（降级后）
        return true;
    }
  }

  getCardType(componentType: string): TemplateCardType {
    const normalized = componentType.toLowerCase().replace(/[^a-z]/g, '');
    return COMPONENT_CARD_MAP[normalized] ?? 'text_notice';
  }
}

// ============================================================================
// 独立 H5 渠道能力
// ============================================================================

/** 独立 H5 渠道能力实现 */
export class H5Capability implements ChannelCapability {
  readonly channelType: ChannelType = 'h5';
  readonly supportsStreaming = true;
  readonly supportsCustomUI = true;
  readonly supportedCardTypes: TemplateCardType[] = [];
  readonly supportsFileUpload = true;
  readonly maxMessageLength = 8192;
  readonly markdownSupportLevel: MarkdownSupportLevel = 'full';
  readonly supportsQuickReply = true;
  readonly supportsCarousel = true;
  readonly supportsFormInput = true;
  readonly supportsButtons = true;

  canRender(_eventType: AgentEventType): boolean {
    // 独立 H5 渠道支持所有事件类型
    return true;
  }

  getCardType(_componentType: string): TemplateCardType {
    // H5 渠道不使用卡片
    return 'text_notice';
  }
}
