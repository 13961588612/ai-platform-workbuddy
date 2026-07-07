/**
 * WecomBotCardBuilder.ts — 企业微信 Bot template_card 构建器
 *
 * 构建 6 种企业微信 template_card 类型：
 * 1. text_notice — 文本通知
 * 2. news_notice — 图文通知
 * 3. button_interaction — 按钮交互
 * 4. vote_interaction — 投票交互
 * 5. multiple_interaction — 多选交互
 * 6. template_notice — 模板通知
 *
 * @module adapters/wecom/WecomBotCardBuilder
 */

import { randomUUID } from 'node:crypto';
import type { TemplateCardType } from '../../channels/ChannelCapability.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 卡片按钮 */
export interface CardButton {
  /** 按钮文案 */
  text: string;
  /** 按钮样式：primary(主要) | default(次要) | warning(警示) */
  style?: 'primary' | 'default' | 'warning';
  /** 按钮点击动作的 key（用户点击后回调中携带） */
  key: string;
  /** 点击跳转 URL（可选，与 key 二选一） */
  url?: string;
}

/** 投票选项 */
export interface VoteOption {
  /** 选项 ID */
  id: number;
  /** 选项文案 */
  text: string;
}

/** 多选交互字段 */
export interface InteractionField {
  /** 字段类型：textarea | select */
  type: 'textarea' | 'select';
  /** 字段名称 */
  name: string;
  /** 字段占位文案 */
  placeholder: string;
  /** 下拉选项（type=select 时使用） */
  options?: Array<{ text: string; value: string }>;
  /** 是否必填 */
  required?: boolean;
}

/** 基础卡片数据 */
export interface BaseCardData {
  /** 卡片类型 */
  cardType: TemplateCardType;
  /** 卡片来源名称 */
  sourceName: string;
  /** 卡片来源图标 URL */
  sourceIconUrl?: string;
  /** 主标题 */
  title: string;
  /** 次标题（副标题） */
  secondaryTitle?: string;
}

/** text_notice 卡片数据 */
export interface TextNoticeData extends BaseCardData {
  cardType: 'text_notice';
  /** 卡片正文内容（支持有限 Markdown） */
  content: string;
  /** 卡片左下角强调文本 */
  emphasizedContent?: string;
  /** 卡片左下角强调文本标题 */
  emphasizedTitle?: string;
  /** 卡片右下角跳转链接文本 */
  linkText?: string;
  /** 卡片右下角跳转链接 URL */
  linkUrl?: string;
}

/** news_notice 卡片数据 */
export interface NewsNoticeData extends BaseCardData {
  cardType: 'news_notice';
  /** 摘要描述 */
  summary: string;
  /** 封面图片 URL */
  imageUrl: string;
  /** 跳转链接 URL */
  linkUrl: string;
}

/** button_interaction 卡片数据 */
export interface ButtonInteractionData extends BaseCardData {
  cardType: 'button_interaction';
  /** 卡片正文内容 */
  content: string;
  /** 按钮列表 */
  buttons: CardButton[];
  /** 任务执行 ID（用于更新卡片状态） */
  taskId: string;
}

/** vote_interaction 卡片数据 */
export interface VoteInteractionData extends BaseCardData {
  cardType: 'vote_interaction';
  /** 卡片正文内容 */
  content: string;
  /** 投票选项列表 */
  options: VoteOption[];
  /** 任务执行 ID */
  taskId: string;
}

/** multiple_interaction 卡片数据 */
export interface MultipleInteractionData extends BaseCardData {
  cardType: 'multiple_interaction';
  /** 卡片正文内容 */
  content: string;
  /** 交互字段列表 */
  fields: InteractionField[];
  /** 提交按钮文案 */
  submitText: string;
  /** 任务执行 ID */
  taskId: string;
}

/** template_notice 卡片数据 */
export interface TemplateNoticeData extends BaseCardData {
  cardType: 'template_notice';
  /** 模板 ID */
  templateId: string;
  /** 模板参数 */
  templateData: Record<string, string>;
  /** 卡片正文内容 */
  content: string;
}

/** 卡片数据联合类型 */
export type CardData =
  | TextNoticeData
  | NewsNoticeData
  | ButtonInteractionData
  | VoteInteractionData
  | MultipleInteractionData
  | TemplateNoticeData;

/** 构建完成的 template_card 消息 */
export interface TemplateCard {
  /** 卡片类型 */
  card_type: TemplateCardType;
  /** 卡片数据（企业微信 API 格式） */
  data: Record<string, unknown>;
}

// ============================================================================
// 常量
// ============================================================================

const DEFAULT_SOURCE_NAME = 'AI智能助手';

// ============================================================================
// WecomBotCardBuilder
// ============================================================================

/**
 * 企业微信 Bot template_card 构建器
 *
 * 构建符合企业微信智能机器人 API 规范的 template_card 消息。
 */
export class WecomBotCardBuilder {
  private readonly sourceName: string;
  private readonly sourceIconUrl: string | undefined;

  constructor(sourceName = DEFAULT_SOURCE_NAME, sourceIconUrl?: string) {
    this.sourceName = sourceName;
    this.sourceIconUrl = sourceIconUrl;
  }

  /**
   * 构建 text_notice（文本通知）卡片
   *
   * 用于展示纯文本/有限 Markdown 内容，如 Agent 回复、工具结果摘要、错误信息。
   *
   * @param title - 主标题
   * @param content - 正文内容（支持有限 Markdown）
   * @param options - 额外选项
   * @returns template_card 消息
   */
  buildTextNotice(
    title: string,
    content: string,
    options?: {
      secondaryTitle?: string;
      emphasizedContent?: string;
      emphasizedTitle?: string;
      linkText?: string;
      linkUrl?: string;
    },
  ): TemplateCard {
    const data: Record<string, unknown> = {
      source: {
        name: this.sourceName,
        ...(this.sourceIconUrl != null ? { icon_url: this.sourceIconUrl } : {}),
      },
      main_title: {
        title,
        ...(options?.secondaryTitle != null
          ? { desc: options.secondaryTitle }
          : {}),
      },
      emphasis_content: {
        title: options?.emphasizedTitle ?? '',
        value: options?.emphasizedContent ?? '',
      },
      sub_title_text: content,
      ...(options?.linkText != null && options?.linkUrl != null
        ? {
            card_action: {
              type: 1,
              url: options.linkUrl,
              text: options.linkText,
            },
          }
        : {}),
    };

    return { card_type: 'text_notice', data };
  }

  /**
   * 构建 news_notice（图文通知）卡片
   *
   * 用于展示带图片的图文信息，如图表数据、报告配图。
   *
   * @param title - 主标题
   * @param summary - 摘要描述
   * @param imageUrl - 封面图片 URL
   * @param linkUrl - 跳转链接 URL
   * @param options - 额外选项
   * @returns template_card 消息
   */
  buildNewsNotice(
    title: string,
    summary: string,
    imageUrl: string,
    linkUrl: string,
    options?: { secondaryTitle?: string },
  ): TemplateCard {
    const data: Record<string, unknown> = {
      source: {
        name: this.sourceName,
        ...(this.sourceIconUrl != null ? { icon_url: this.sourceIconUrl } : {}),
      },
      main_title: {
        title,
        ...(options?.secondaryTitle != null
          ? { desc: options.secondaryTitle }
          : {}),
      },
      card_image: {
        url: imageUrl,
      },
      image_text_region: {
        title,
        desc: summary,
        url: linkUrl,
        type: 1,
      },
      card_action: {
        type: 1,
        url: linkUrl,
      },
    };

    return { card_type: 'news_notice', data };
  }

  /**
   * 构建 button_interaction（按钮交互）卡片
   *
   * 用于需要用户做出选择的场景，如 HITL 审批（同意/拒绝）。
   *
   * @param title - 主标题
   * @param content - 正文内容
   * @param buttons - 按钮列表
   * @param options - 额外选项
   * @returns template_card 消息
   */
  buildButtonInteraction(
    title: string,
    content: string,
    buttons: CardButton[],
    options?: { secondaryTitle?: string; taskId?: string },
  ): TemplateCard {
    const taskId = options?.taskId ?? randomUUID();

    const data: Record<string, unknown> = {
      source: {
        name: this.sourceName,
        ...(this.sourceIconUrl != null ? { icon_url: this.sourceIconUrl } : {}),
      },
      main_title: {
        title,
        ...(options?.secondaryTitle != null
          ? { desc: options.secondaryTitle }
          : {}),
      },
      sub_title_text: content,
      task_id: taskId,
      button_list: buttons.map((btn) => ({
        text: btn.text,
        style: btn.style ?? 'default',
        type: btn.url != null ? 1 : 2,
        ...(btn.url != null ? { url: btn.url } : { key: btn.key }),
      })),
      button_selection: {
        option_list: buttons.map((btn) => ({
          id: btn.key,
          text: btn.text,
          style: btn.style ?? 'default',
        })),
      },
    };

    return { card_type: 'button_interaction', data };
  }

  /**
   * 构建 vote_interaction（投票交互）卡片
   *
   * 用于需要用户投票选择的场景。
   *
   * @param title - 主标题
   * @param content - 正文内容
   * @param options - 投票选项列表
   * @param extraOptions - 额外选项
   * @returns template_card 消息
   */
  buildVoteInteraction(
    title: string,
    content: string,
    options: VoteOption[],
    extraOptions?: { secondaryTitle?: string; taskId?: string },
  ): TemplateCard {
    const taskId = extraOptions?.taskId ?? randomUUID();

    const data: Record<string, unknown> = {
      source: {
        name: this.sourceName,
        ...(this.sourceIconUrl != null ? { icon_url: this.sourceIconUrl } : {}),
      },
      main_title: {
        title,
        ...(extraOptions?.secondaryTitle != null
          ? { desc: extraOptions.secondaryTitle }
          : {}),
      },
      sub_title_text: content,
      task_id: taskId,
      vote_list: options.map((opt) => ({
        vote_id: opt.id,
        text: opt.text,
      })),
    };

    return { card_type: 'vote_interaction', data };
  }

  /**
   * 构建 multiple_interaction（多选交互）卡片
   *
   * 用于需要用户填写表单的场景，如报告表单、配置表单。
   *
   * @param title - 主标题
   * @param fields - 交互字段列表
   * @param submitText - 提交按钮文案
   * @param options - 额外选项
   * @returns template_card 消息
   */
  buildMultipleInteraction(
    title: string,
    fields: InteractionField[],
    submitText: string,
    options?: {
      content?: string;
      secondaryTitle?: string;
      taskId?: string;
    },
  ): TemplateCard {
    const taskId = options?.taskId ?? randomUUID();

    const data: Record<string, unknown> = {
      source: {
        name: this.sourceName,
        ...(this.sourceIconUrl != null ? { icon_url: this.sourceIconUrl } : {}),
      },
      main_title: {
        title,
        ...(options?.secondaryTitle != null
          ? { desc: options.secondaryTitle }
          : {}),
      },
      ...(options?.content != null ? { sub_title_text: options.content } : {}),
      task_id: taskId,
      submit_button: {
        text: submitText,
        key: 'submit',
      },
      select_list: fields
        .filter((f) => f.type === 'select')
        .map((f, idx) => ({
          question_key: f.name,
          title: f.placeholder,
          option_list:
            f.options?.map((opt) => ({
              id: opt.value,
              text: opt.text,
            })) ?? [],
          ...(f.required != null ? { required: f.required ? 1 : 0 } : {}),
          selected_id: '',
        })),
      textarea_list: fields
        .filter((f) => f.type === 'textarea')
        .map((f) => ({
          question_key: f.name,
          title: f.placeholder,
          ...(f.required != null ? { required: f.required ? 1 : 0 } : {}),
          value: '',
        })),
    };

    return { card_type: 'multiple_interaction', data };
  }

  /**
   * 构建 template_notice（模板通知）卡片
   *
   * 用于使用预定义模板发送通知消息。
   *
   * @param templateId - 模板 ID
   * @param templateData - 模板参数
   * @param title - 主标题
   * @param content - 正文内容
   * @param options - 额外选项
   * @returns template_card 消息
   */
  buildTemplateNotice(
    templateId: string,
    templateData: Record<string, string>,
    title: string,
    content: string,
    options?: { secondaryTitle?: string },
  ): TemplateCard {
    const data: Record<string, unknown> = {
      source: {
        name: this.sourceName,
        ...(this.sourceIconUrl != null ? { icon_url: this.sourceIconUrl } : {}),
      },
      main_title: {
        title,
        ...(options?.secondaryTitle != null
          ? { desc: options.secondaryTitle }
          : {}),
      },
      template_card: {
        template_id: templateId,
        template_variable: templateData,
      },
      sub_title_text: content,
    };

    return { card_type: 'template_notice', data };
  }

  /**
   * 根据卡片数据构建 template_card（统一入口）
   *
   * @param cardData - 卡片数据
   * @returns template_card 消息
   */
  build(cardData: CardData): TemplateCard {
    switch (cardData.cardType) {
      case 'text_notice':
        return this.buildTextNotice(cardData.title, cardData.content, {
          secondaryTitle: cardData.secondaryTitle,
          emphasizedContent: cardData.emphasizedContent,
          emphasizedTitle: cardData.emphasizedTitle,
          linkText: cardData.linkText,
          linkUrl: cardData.linkUrl,
        });

      case 'news_notice':
        return this.buildNewsNotice(
          cardData.title,
          cardData.summary,
          cardData.imageUrl,
          cardData.linkUrl,
          { secondaryTitle: cardData.secondaryTitle },
        );

      case 'button_interaction':
        return this.buildButtonInteraction(
          cardData.title,
          cardData.content,
          cardData.buttons,
          { secondaryTitle: cardData.secondaryTitle, taskId: cardData.taskId },
        );

      case 'vote_interaction':
        return this.buildVoteInteraction(
          cardData.title,
          cardData.content,
          cardData.options,
          { secondaryTitle: cardData.secondaryTitle, taskId: cardData.taskId },
        );

      case 'multiple_interaction':
        return this.buildMultipleInteraction(
          cardData.title,
          cardData.fields,
          cardData.submitText,
          {
            content: cardData.content,
            secondaryTitle: cardData.secondaryTitle,
            taskId: cardData.taskId,
          },
        );

      case 'template_notice':
        return this.buildTemplateNotice(
          cardData.templateId,
          cardData.templateData,
          cardData.title,
          cardData.content,
          { secondaryTitle: cardData.secondaryTitle },
        );

      default: {
        const exhaustive: never = cardData;
        throw new Error(`Unknown card type: ${String(exhaustive)}`);
      }
    }
  }
}
