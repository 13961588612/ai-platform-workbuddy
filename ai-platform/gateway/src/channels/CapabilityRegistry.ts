/**
 * CapabilityRegistry.ts — 渠道能力注册表
 *
 * 管理三渠道（wecom-h5 / wecom-bot / h5）的能力矩阵注册与查询。
 * EventTransformer 和适配器通过此注册表获取指定渠道的能力声明。
 *
 * @module channels/CapabilityRegistry
 */

import type { ChannelCapability, ChannelType } from './ChannelCapability.js';
import {
  WecomH5Capability,
  WecomBotCapability,
  H5Capability,
} from './ChannelCapability.js';
import { logger } from '../middleware/logger.js';

// ============================================================================
// 类型定义
// ============================================================================

/** 渠道能力矩阵映射 */
export type CapabilityMatrix = Map<ChannelType, ChannelCapability>;

// ============================================================================
// 渠道能力注册表
// ============================================================================

/**
 * 渠道能力注册表
 *
 * 单例模式，管理三渠道的能力声明。
 * 提供按渠道类型查询能力、注册自定义能力实现的功能。
 */
export class CapabilityRegistry {
  private readonly capabilities: CapabilityMatrix;
  private static instance: CapabilityRegistry | null = null;

  private constructor() {
    this.capabilities = new Map();

    // 注册三渠道默认能力
    this.register(new WecomH5Capability());
    this.register(new WecomBotCapability());
    this.register(new H5Capability());

    logger.info(
      {
        channels: Array.from(this.capabilities.keys()),
      },
      'CapabilityRegistry initialized with default channels',
    );
  }

  /**
   * 获取单例实例
   * @returns 注册表单例
   */
  static getInstance(): CapabilityRegistry {
    if (CapabilityRegistry.instance == null) {
      CapabilityRegistry.instance = new CapabilityRegistry();
    }
    return CapabilityRegistry.instance;
  }

  /**
   * 注册渠道能力
   * @param capability - 渠道能力实现
   */
  register(capability: ChannelCapability): void {
    this.capabilities.set(capability.channelType, capability);
    logger.debug(
      { channelType: capability.channelType },
      'Channel capability registered',
    );
  }

  /**
   * 获取指定渠道的能力声明
   * @param channelType - 渠道类型
   * @returns 渠道能力实现
   * @throws 渠道未注册时抛出错误
   */
  getCapability(channelType: ChannelType): ChannelCapability {
    const capability = this.capabilities.get(channelType);
    if (capability == null) {
      throw new Error(
        `Channel capability not registered for channel: ${channelType}`,
      );
    }
    return capability;
  }

  /**
   * 尝试获取指定渠道的能力声明
   * @param channelType - 渠道类型
   * @returns 渠道能力实现或 undefined
   */
  tryGetCapability(channelType: ChannelType): ChannelCapability | undefined {
    return this.capabilities.get(channelType);
  }

  /**
   * 检查渠道是否已注册
   * @param channelType - 渠道类型
   * @returns 是否已注册
   */
  has(channelType: ChannelType): boolean {
    return this.capabilities.has(channelType);
  }

  /**
   * 获取所有已注册渠道类型
   * @returns 渠道类型列表
   */
  listChannels(): ChannelType[] {
    return Array.from(this.capabilities.keys());
  }

  /**
   * 获取所有已注册渠道的能力声明
   * @returns 渠道能力列表
   */
  listCapabilities(): ChannelCapability[] {
    return Array.from(this.capabilities.values());
  }

  /**
   * 获取渠道能力矩阵摘要（用于管理后台展示）
   * @returns 能力矩阵摘要
   */
  getMatrixSummary(): Array<{
    channelType: ChannelType;
    supportsStreaming: boolean;
    supportsCustomUI: boolean;
    supportedCardTypes: string[];
    supportsFileUpload: boolean;
    maxMessageLength: number;
    markdownSupportLevel: string;
    supportsQuickReply: boolean;
    supportsCarousel: boolean;
    supportsFormInput: boolean;
    supportsButtons: boolean;
  }> {
    return this.listCapabilities().map((cap) => ({
      channelType: cap.channelType,
      supportsStreaming: cap.supportsStreaming,
      supportsCustomUI: cap.supportsCustomUI,
      supportedCardTypes: cap.supportedCardTypes,
      supportsFileUpload: cap.supportsFileUpload,
      maxMessageLength: cap.maxMessageLength,
      markdownSupportLevel: cap.markdownSupportLevel,
      supportsQuickReply: cap.supportsQuickReply,
      supportsCarousel: cap.supportsCarousel,
      supportsFormInput: cap.supportsFormInput,
      supportsButtons: cap.supportsButtons,
    }));
  }
}

/**
 * 获取全局能力注册表单例
 * @returns 能力注册表
 */
export function getCapabilityRegistry(): CapabilityRegistry {
  return CapabilityRegistry.getInstance();
}
