/**
 * BotEventMapper.ts — Bot 渠道 AgentEvent → template_card 映射器
 *
 * 将 AgentEvent 流映射为企业微信 Bot 渠道的 template_card：
 * - text.delta → 缓冲累积 → text_notice
 * - ui.render → 按组件类型匹配卡片
 * - approval.request → button_interaction
 * - tool.result → text_notice 摘要
 * - error → text_notice 错误信息
 *
 * @module router/BotEventMapper
 */

import type { AgentEvent, TemplateCardType } from '../channels/ChannelCapability.js';
import type { TemplateCard } from '../adapters/wecom/WecomBotCardBuilder.js';
import { WecomBotCardBuilder } from '../adapters/wecom/WecomBotCardBuilder.js';
import { logger } from '../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 审批详情（从 approval.request 事件提取） */
export interface ApprovalDetail {
  /** 审批标题 */
  title: string;
  /** 审批描述 */
  description: string;
  /** Skill ID */
  skillId: string;
  /** 审批 ID */
  approvalId: string;
}

/** 映射结果 */
export interface BotMappingResult {
  /** 生成的 template_card */
  card: TemplateCard;
  /** 映射的事件类型 */
  eventType: string;
  /** 是否为降级映射 */
  degraded: boolean;
}

// ============================================================================
// 常量
// ============================================================================

/** 默认卡片来源名称 */
const DEFAULT_SOURCE_NAME = 'AI智能助手';

/** Bot 消息最大长度 */
const BOT_MAX_LENGTH = 2048;

/** 工具调用中文描述前缀 */
const TOOL_CALL_PREFIX = '正在执行';

const TOOL_RESULT_PREFIX = '执行完成';

// ============================================================================
// BotEventMapper
// ============================================================================

/**
 * Bot 渠道 AgentEvent → template_card 映射器
 *
 * 核心映射逻辑：
 * | AgentEvent | Bot 卡片类型 | 说明 |
 * |-----------|------------|------|
 * | text.delta | 缓冲 → text_notice | 流式文本缓冲后一次性发送 |
 * | ui.render | 卡片匹配 | 匹配 supportedCardTypes，否则降级 |
 * | approval.request | button_interaction | 审批按钮卡片 |
 * | tool.result | text_notice | 工具结果摘要 |
 * | error | text_notice | 错误信息 |
 */
export class BotEventMapper {
  private readonly cardBuilder: WecomBotCardBuilder;
  private textBuffer: string[] = [];

  constructor(cardBuilder?: WecomBotCardBuilder) {
    this.cardBuilder = cardBuilder ?? new WecomBotCardBuilder(DEFAULT_SOURCE_NAME);
  }

  /**
   * 缓冲 text.delta 事件
   *
   * Bot 渠道不支持流式输出，需要将所有 text.delta 事件缓冲后，
   * 在 done 事件时一次性发送为 text_notice 卡片。
   *
   * @param event - text.delta 事件
   */
  bufferTextDelta(event: AgentEvent): void {
    if (event.type === 'text.delta' && event.content != null) {
      this.textBuffer.push(event.content);
      logger.debug(
        { bufferedLength: this.textBuffer.length },
        'text.delta buffered for Bot channel',
      );
    }
  }

  /**
   * 将缓冲的 text.delta 映射为 text_notice 卡片
   *
   * @returns 包含 text_notice 卡片的映射结果
   */
  mapTextDelta(): BotMappingResult {
    const fullText = this.textBuffer.join('');
    this.textBuffer = [];

    // 截断超长文本
    const truncatedText =
      fullText.length > BOT_MAX_LENGTH
        ? `${fullText.slice(0, BOT_MAX_LENGTH - 20)}...(内容过长已截断)`
        : fullText;

    const card = this.cardBuilder.buildTextNotice(
      'AI助手回复',
      truncatedText,
      {
        emphasizedContent: '',
        emphasizedTitle: '',
      },
    );

    return {
      card,
      eventType: 'text.delta',
      degraded: true,
    };
  }

  /**
   * 将 ui.render 事件映射为 template_card
   *
   * 映射规则：
   * - 表格/列表组件 → text_notice
   * - 图表/图片组件 → news_notice
   * - 按钮/操作组件 → button_interaction
   * - 表单组件 → multiple_interaction
   * - 无法匹配 → text_notice（降级）
   *
   * @param component - UI 组件名称
   * @param props - 组件属性
   * @returns 包含匹配卡片的映射结果
   */
  mapUIRender(
    component: string,
    props: Record<string, unknown>,
  ): BotMappingResult {
    const cardType = this.resolveCardType(component);
    const title = this.extractTitle(props, component);

    let card: TemplateCard;

    switch (cardType) {
      case 'text_notice': {
        // 表格/列表 → 文本摘要
        const content = this.formatComponentAsText(component, props);
        card = this.cardBuilder.buildTextNotice(title, content, {});
        break;
      }

      case 'news_notice': {
        // 图表/图片 → 图文通知
        const imageUrl = this.extractStringProp(props, 'imageUrl') ?? '';
        const linkUrl = this.extractStringProp(props, 'linkUrl') ?? '#';
        const summary = this.extractStringProp(props, 'summary') ?? '';
        card = this.cardBuilder.buildNewsNotice(title, summary, imageUrl, linkUrl, {});
        break;
      }

      case 'button_interaction': {
        // 按钮/操作 → 按钮交互
        const buttons = this.extractButtons(props);
        const content = this.extractStringProp(props, 'content') ?? '';
        card = this.cardBuilder.buildButtonInteraction(title, content, buttons, {});
        break;
      }

      case 'multiple_interaction': {
        // 表单 → 多选交互
        const fields = this.extractFields(props);
        const submitText = this.extractStringProp(props, 'submitText') ?? '提交';
        const content = this.extractStringProp(props, 'content') ?? '';
        card = this.cardBuilder.buildMultipleInteraction(title, fields, submitText, {
          content,
        });
        break;
      }

      case 'vote_interaction': {
        // 投票
        const options = this.extractVoteOptions(props);
        const content = this.extractStringProp(props, 'content') ?? '';
        card = this.cardBuilder.buildVoteInteraction(title, content, options, {});
        break;
      }

      case 'template_notice': {
        // 模板通知
        const templateId = this.extractStringProp(props, 'templateId') ?? '';
        const templateData = this.extractTemplateData(props);
        const content = this.extractStringProp(props, 'content') ?? '';
        card = this.cardBuilder.buildTemplateNotice(
          templateId,
          templateData,
          title,
          content,
        );
        break;
      }

      default: {
        // 降级为 text_notice
        const content = this.formatComponentAsText(component, props);
        card = this.cardBuilder.buildTextNotice(
          title,
          `${content}\n\n> 💡 请打开 H5 页面查看完整内容`,
          {},
        );
        break;
      }
    }

    return {
      card,
      eventType: 'ui.render',
      degraded: cardType === 'text_notice',
    };
  }

  /**
   * 将 approval.request 事件映射为 button_interaction 卡片
   *
   * @param detail - 审批详情
   * @returns 包含 button_interaction 卡片的映射结果
   */
  mapApprovalRequest(detail: ApprovalDetail): BotMappingResult {
    const content = detail.description;
    const buttons = [
      {
        text: '同意',
        style: 'primary' as const,
        key: `approve:${detail.approvalId}`,
      },
      {
        text: '拒绝',
        style: 'warning' as const,
        key: `reject:${detail.approvalId}`,
      },
      {
        text: '查看详情',
        style: 'default' as const,
        key: `detail:${detail.approvalId}`,
        url: `#/approval/${detail.approvalId}`,
      },
    ];

    const card = this.cardBuilder.buildButtonInteraction(
      detail.title,
      content,
      buttons,
      { taskId: detail.approvalId },
    );

    return {
      card,
      eventType: 'approval.request',
      degraded: true,
    };
  }

  /**
   * 将 tool.result 事件映射为 text_notice 摘要卡片
   *
   * @param toolName - 工具名称
   * @param result - 工具执行结果
   * @returns 包含 text_notice 卡片的映射结果
   */
  mapToolResult(
    toolName: string,
    result: Record<string, unknown>,
  ): BotMappingResult {
    const summary = this.summarizeResult(result);
    const title = `${TOOL_RESULT_PREFIX}: ${this.formatToolName(toolName)}`;
    const card = this.cardBuilder.buildTextNotice(title, summary, {});

    return {
      card,
      eventType: 'tool.result',
      degraded: true,
    };
  }

  /**
   * 将 error 事件映射为 text_notice 错误信息卡片
   *
   * @param errorCode - 错误码
   * @param errorMessage - 错误消息
   * @returns 包含 text_notice 卡片的映射结果
   */
  mapError(errorCode: string, errorMessage: string): BotMappingResult {
    const title = '⚠️ 处理出错';
    const content = `**错误码**: ${errorCode}\n\n**错误信息**: ${errorMessage}\n\n请稍后重试或联系管理员。`;
    const card = this.cardBuilder.buildTextNotice(title, content, {});

    return {
      card,
      eventType: 'error',
      degraded: true,
    };
  }

  /**
   * 创建工具调用中通知卡片
   *
   * @param toolName - 工具名称
   * @returns 包含 text_notice 卡片的映射结果
   */
  mapToolCall(toolName: string): BotMappingResult {
    const title = `${TOOL_CALL_PREFIX}`;
    const content = `正在调用 **${this.formatToolName(toolName)}**，请稍候...`;
    const card = this.cardBuilder.buildTextNotice(title, content, {});

    return {
      card,
      eventType: 'tool.call',
      degraded: true,
    };
  }

  /**
   * 检查是否有缓冲的文本待发送
   * @returns 是否有缓冲文本
   */
  hasBufferedText(): boolean {
    return this.textBuffer.length > 0;
  }

  /**
   * 清空文本缓冲区
   */
  clearBuffer(): void {
    this.textBuffer = [];
  }

  // ========================================================================
  // 私有辅助方法
  // ========================================================================

  /**
   * 根据组件名称解析卡片类型
   */
  private resolveCardType(component: string): TemplateCardType {
    const normalized = component.toLowerCase().replace(/[^a-z]/g, '');

    // 表格/列表 → text_notice
    if (
      normalized.includes('table') ||
      normalized.includes('list') ||
      normalized.includes('datagrid') ||
      normalized.includes('leavereport') ||
      normalized.includes('report')
    ) {
      return 'text_notice';
    }

    // 图表/图片 → news_notice
    if (
      normalized.includes('chart') ||
      normalized.includes('image') ||
      normalized.includes('graph') ||
      normalized.includes('sales')
    ) {
      return 'news_notice';
    }

    // 按钮/操作 → button_interaction
    if (
      normalized.includes('button') ||
      normalized.includes('action')
    ) {
      return 'button_interaction';
    }

    // 表单 → multiple_interaction
    if (normalized.includes('form')) {
      return 'multiple_interaction';
    }

    // 投票 → vote_interaction
    if (normalized.includes('vote') || normalized.includes('poll')) {
      return 'vote_interaction';
    }

    // 通知 → template_notice
    if (normalized.includes('notice') || normalized.includes('notification')) {
      return 'template_notice';
    }

    // 默认降级
    return 'text_notice';
  }

  /**
   * 从组件属性中提取标题
   */
  private extractTitle(
    props: Record<string, unknown>,
    component: string,
  ): string {
    return (
      this.extractStringProp(props, 'title') ??
      this.extractStringProp(props, 'name') ??
      component
    );
  }

  /**
   * 将组件格式化为文本摘要
   */
  private formatComponentAsText(
    component: string,
    props: Record<string, unknown>,
  ): string {
    const title = this.extractTitle(props, component);
    const description =
      this.extractStringProp(props, 'description') ??
      this.extractStringProp(props, 'summary') ??
      '';

    // 如果有数据，尝试格式化为文本表格
    const data = props['data'] ?? props['items'];
    if (Array.isArray(data)) {
      const lines = data.map((item) => {
        if (typeof item === 'object' && item != null) {
          const entries = Object.entries(item as Record<string, unknown>);
          return entries.map(([k, v]) => `${k}: ${String(v)}`).join(' | ');
        }
        return String(item);
      });
      return `${title}\n\n${description}\n\n${lines.join('\n')}`;
    }

    return `${title}\n\n${description}`.trim();
  }

  /**
   * 从属性中提取按钮列表
   */
  private extractButtons(
    props: Record<string, unknown>,
  ): Array<{ text: string; style: 'primary' | 'default' | 'warning'; key: string; url?: string }> {
    const rawButtons =
      (props['buttons'] as unknown[]) ??
      (props['actions'] as unknown[]) ??
      [];

    return rawButtons.map((raw, idx) => {
      if (typeof raw === 'object' && raw != null) {
        const obj = raw as Record<string, unknown>;
        return {
          text: this.extractStringProp(obj, 'text') ?? this.extractStringProp(obj, 'label') ?? `按钮${idx + 1}`,
          style: (this.extractStringProp(obj, 'style') as 'primary' | 'default' | 'warning') ?? 'default',
          key: this.extractStringProp(obj, 'key') ?? this.extractStringProp(obj, 'value') ?? `btn_${idx}`,
          url: this.extractStringProp(obj, 'url'),
        };
      }
      return {
        text: String(raw),
        style: 'default' as const,
        key: `btn_${idx}`,
      };
    });
  }

  /**
   * 从属性中提取表单字段
   */
  private extractFields(
    props: Record<string, unknown>,
  ): Array<{
    type: 'textarea' | 'select';
    name: string;
    placeholder: string;
    options?: Array<{ text: string; value: string }>;
    required?: boolean;
  }> {
    const rawFields = (props['fields'] as unknown[]) ?? [];

    return rawFields.map((raw) => {
      if (typeof raw === 'object' && raw != null) {
        const obj = raw as Record<string, unknown>;
        const type = (this.extractStringProp(obj, 'type') === 'select' ? 'select' : 'textarea') as 'textarea' | 'select';
        const name = this.extractStringProp(obj, 'name') ?? '';
        const placeholder = this.extractStringProp(obj, 'placeholder') ?? '';
        const required = obj['required'] === true;
        const rawOptions = (obj['options'] as unknown[]) ?? undefined;
        const options = rawOptions?.map((opt) => {
          if (typeof opt === 'object' && opt != null) {
            const o = opt as Record<string, unknown>;
            return {
              text: this.extractStringProp(o, 'text') ?? this.extractStringProp(o, 'label') ?? '',
              value: this.extractStringProp(o, 'value') ?? '',
            };
          }
          return { text: String(opt), value: String(opt) };
        });

        return { type, name, placeholder, options, required };
      }
      return {
        type: 'textarea' as const,
        name: String(raw),
        placeholder: String(raw),
      };
    });
  }

  /**
   * 从属性中提取投票选项
   */
  private extractVoteOptions(
    props: Record<string, unknown>,
  ): Array<{ id: number; text: string }> {
    const rawOptions = (props['options'] as unknown[]) ?? [];

    return rawOptions.map((raw, idx) => {
      if (typeof raw === 'object' && raw != null) {
        const obj = raw as Record<string, unknown>;
        return {
          id: idx + 1,
          text: this.extractStringProp(obj, 'text') ?? this.extractStringProp(obj, 'label') ?? `选项${idx + 1}`,
        };
      }
      return { id: idx + 1, text: String(raw) };
    });
  }

  /**
   * 从属性中提取模板数据
   */
  private extractTemplateData(
    props: Record<string, unknown>,
  ): Record<string, string> {
    const raw = props['templateData'] ?? props['variables'];
    if (typeof raw === 'object' && raw != null) {
      const result: Record<string, string> = {};
      for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
        result[k] = String(v);
      }
      return result;
    }
    return {};
  }

  /**
   * 格式化工具名称
   */
  private formatToolName(toolName: string): string {
    // 将 skill-leave-query → 查询请假
    const parts = toolName.split('-').filter((p) => p !== 'skill');
    return parts.join(' ');
  }

  /**
   * 摘要工具结果
   */
  private summarizeResult(result: Record<string, unknown>): string {
    const entries = Object.entries(result);
    if (entries.length === 0) {
      return '操作已完成';
    }

    const lines = entries.slice(0, 10).map(([key, value]) => {
      const displayValue =
        typeof value === 'object' && value != null
          ? JSON.stringify(value)
          : String(value);
      const truncated =
        displayValue.length > 200
          ? `${displayValue.slice(0, 200)}...`
          : displayValue;
      return `**${key}**: ${truncated}`;
    });

    if (entries.length > 10) {
      lines.push(`\n...(共 ${entries.length} 项结果)`);
    }

    return lines.join('\n');
  }

  /**
   * 从对象中安全提取字符串属性
   */
  private extractStringProp(
    obj: Record<string, unknown>,
    key: string,
  ): string | undefined {
    const value = obj[key];
    return typeof value === 'string' ? value : undefined;
    }
}
