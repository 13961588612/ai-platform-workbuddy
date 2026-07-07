/**
 * crypto.ts — 加解密工具（企业微信消息加解密 AES-CBC）
 *
 * 实现企业微信回调消息的 AES-256-CBC 加解密，用于：
 * - 企业微信回调消息体解密
 * - 企业微信被动回复消息加密
 * - 签名校验（SHA1）
 *
 * @module utils/crypto
 */

import crypto from 'node:crypto';
import { XMLParser, XMLBuilder } from 'fast-xml-parser';

// ============================================================================
// 类型定义
// ============================================================================

/** 企业微信加密消息结构 */
export interface WecomEncryptedMessage {
  /** XML 消息内容 */
  xmlContent: string;
  /** 消息签名 */
  msgSignature: string;
  /** 时间戳 */
  timestamp: string;
  /** 随机数 */
  nonce: string;
}

/** 解密后的消息体 */
export interface WecomDecryptedMessage {
  /** 消息内容（明文 XML） */
  content: string;
  /** 接收者 */
  toUserName: string;
}

// ============================================================================
// 常量
// ============================================================================

const BLOCK_SIZE = 32;
const AES_KEY_LENGTH = 43;

// ============================================================================
// 工具函数
// ============================================================================

/**
 * Base64 编码
 * @param data - 原始数据
 * @returns Base64 字符串
 */
export function base64Encode(data: Buffer): string {
  return data.toString('base64');
}

/**
 * Base64 解码
 * @param encoded - Base64 字符串
 * @returns 原始数据 Buffer
 */
export function base64Decode(encoded: string): Buffer {
  return Buffer.from(encoded, 'base64');
}

/**
 * 将企业微信 EncodingAESKey（43 字符 Base64）转换为 AES 密钥 Buffer（32 字节）
 * @param encodingAesKey - 43 字符的 EncodingAESKey
 * @returns 32 字节 AES 密钥
 */
export function decodeAesKey(encodingAesKey: string): Buffer {
  if (encodingAesKey.length !== AES_KEY_LENGTH) {
    throw new Error(
      `Invalid EncodingAESKey length: expected ${AES_KEY_LENGTH}, got ${encodingAesKey.length}`,
    );
  }
  return base64Decode(`${encodingAesKey}=`);
}

/**
 * PKCS#7 填充
 * @param data - 原始数据
 * @returns 填充后的数据
 */
export function pkcs7Pad(data: Buffer): Buffer {
  const padLength = BLOCK_SIZE - (data.length % BLOCK_SIZE);
  const padBuffer = Buffer.alloc(padLength, padLength);
  return Buffer.concat([data, padBuffer]);
}

/**
 * PKCS#7 去填充
 * @param data - 填充后的数据
 * @returns 去填充后的原始数据
 */
export function pkcs7Unpad(data: Buffer): Buffer {
  if (data.length === 0) {
    throw new Error('Cannot unpad empty buffer');
  }
  const padLength = data[data.length - 1];
  if (padLength < 1 || padLength > BLOCK_SIZE) {
    throw new Error(`Invalid PKCS#7 padding length: ${padLength}`);
  }
  return data.subarray(0, data.length - padLength);
}

/**
 * 生成随机字符串（16 字节 hex）
 * @returns 32 字符的随机十六进制字符串
 */
export function generateRandomString(): string {
  return crypto.randomBytes(16).toString('hex');
}

// ============================================================================
// 签名计算
// ============================================================================

/**
 * 计算企业微信消息签名（SHA1）
 *
 * 签名算法：
 * 1. 将 token、timestamp、nonce、encrypt 四个参数进行字典序排序
 * 2. 将排序后的四个参数拼接成一个字符串
 * 3. 对拼接后的字符串进行 SHA1 计算
 *
 * @param token - 企业微信回调配置的 Token
 * @param timestamp - 时间戳
 * @param nonce - 随机数
 * @param encrypt - 加密消息体
 * @returns SHA1 签名（40 字符小写十六进制）
 */
export function calculateSignature(
  token: string,
  timestamp: string,
  nonce: string,
  encrypt: string,
): string {
  const sorted = [token, timestamp, nonce, encrypt].sort();
  const joined = sorted.join('');
  return crypto.createHash('sha1').update(joined).digest('hex');
}

/**
 * 验证企业微信消息签名
 * @param token - 企业微信回调配置的 Token
 * @param timestamp - 时间戳
 * @param nonce - 随机数
 * @param encrypt - 加密消息体
 * @param signature - 待验证的签名
 * @returns 签名是否匹配
 */
export function verifySignature(
  token: string,
  timestamp: string,
  nonce: string,
  encrypt: string,
  signature: string,
): boolean {
  const calculated = calculateSignature(token, timestamp, nonce, encrypt);
  return calculated === signature;
}

// ============================================================================
// AES-256-CBC 加解密
// ============================================================================

/**
 * 加密企业微信消息
 *
 * 加密格式：
 * [16 字节随机字符串] [4 字节消息长度（大端序）] [消息内容] [接收者 CorpID]
 * 整体进行 PKCS#7 填充后用 AES-256-CBC 加密，IV 为密钥前 16 字节
 *
 * @param message - 明文消息
 * @param aesKey - AES 密钥（32 字节）
 * @param corpId - 企业 CorpID
 * @returns Base64 编码的加密消息
 */
export function encryptMessage(
  message: string,
  aesKey: Buffer,
  corpId: string,
): string {
  const randomBytes = crypto.randomBytes(16);
  const messageBuffer = Buffer.from(message, 'utf-8');
  const lengthBuffer = Buffer.alloc(4);
  lengthBuffer.writeUInt32BE(messageBuffer.length, 0);
  const corpIdBuffer = Buffer.from(corpId, 'utf-8');

  const rawMessage = Buffer.concat([
    randomBytes,
    lengthBuffer,
    messageBuffer,
    corpIdBuffer,
  ]);

  const paddedMessage = pkcs7Pad(rawMessage);
  const iv = aesKey.subarray(0, 16);

  const cipher = crypto.createCipheriv('aes-256-cbc', aesKey, iv);
  cipher.setAutoPadding(false);
  const encrypted = Buffer.concat([cipher.update(paddedMessage), cipher.final()]);

  return base64Encode(encrypted);
}

/**
 * 解密企业微信消息
 *
 * @param encryptedMessage - Base64 编码的加密消息
 * @param aesKey - AES 密钥（32 字节）
 * @param expectedCorpId - 预期的 CorpID（用于校验）
 * @returns 解密后的消息内容和接收者
 */
export function decryptMessage(
  encryptedMessage: string,
  aesKey: Buffer,
  expectedCorpId: string,
): WecomDecryptedMessage {
  const encryptedBuffer = base64Decode(encryptedMessage);
  const iv = aesKey.subarray(0, 16);

  const decipher = crypto.createDecipheriv('aes-256-cbc', aesKey, iv);
  decipher.setAutoPadding(false);
  const decrypted = Buffer.concat([
    decipher.update(encryptedBuffer),
    decipher.final(),
  ]);

  const unpadded = pkcs7Unpad(decrypted);

  // 跳过 16 字节随机字符串
  const messageLength = unpadded.readUInt32BE(16);
  const content = unpadded.subarray(20, 20 + messageLength).toString('utf-8');
  const toUserName = unpadded
    .subarray(20 + messageLength)
    .toString('utf-8');

  if (toUserName !== expectedCorpId) {
    throw new Error(
      `CorpID mismatch: expected ${expectedCorpId}, got ${toUserName}`,
    );
  }

  return { content, toUserName };
}

// ============================================================================
// XML 工具
// ============================================================================

const xmlParser = new XMLParser({
  ignoreAttributes: false,
  parseTagValue: true,
  trimValues: true,
});

const xmlBuilder = new XMLBuilder({
  ignoreAttributes: false,
  format: false,
});

/**
 * 解析 XML 字符串为对象
 * @param xml - XML 字符串
 * @returns 解析后的对象
 */
export function parseXml<T = Record<string, unknown>>(xml: string): T {
  return xmlParser.parse(xml) as T;
}

/**
 * 将对象构建为 XML 字符串
 * @param obj - 待转换的对象
 * @returns XML 字符串
 */
export function buildXml(obj: Record<string, unknown>): string {
  return xmlBuilder.build(obj);
}

// ============================================================================
// 高层加解密封装
// ============================================================================

/**
 * 企业微信消息加解密器
 *
 * 封装完整的加解密流程，提供便捷的加密/解密/验签方法。
 */
export class WecomCrypto {
  private readonly aesKey: Buffer;
  private readonly token: string;
  private readonly corpId: string;

  /**
   * @param encodingAesKey - 43 字符的 EncodingAESKey
   * @param token - 企业微信回调配置的 Token
   * @param corpId - 企业 CorpID
   */
  constructor(encodingAesKey: string, token: string, corpId: string) {
    this.aesKey = decodeAesKey(encodingAesKey);
    this.token = token;
    this.corpId = corpId;
  }

  /**
   * 解密并验证企业微信回调消息
   * @param encryptedMessage - 加密消息信息
   * @returns 解密后的消息内容
   */
  decrypt(encryptedMessage: WecomEncryptedMessage): string {
    const isValid = verifySignature(
      this.token,
      encryptedMessage.timestamp,
      encryptedMessage.nonce,
      encryptedMessage.msgSignature,
      encryptedMessage.xmlContent,
    );
    if (!isValid) {
      throw new Error('Signature verification failed');
    }
    const result = decryptMessage(
      encryptedMessage.xmlContent,
      this.aesKey,
      this.corpId,
    );
    return result.content;
  }

  /**
   * 加密回复消息
   * @param replyMessage - 明文回复消息（XML 字符串）
   * @returns 包含加密消息和签名的回复对象
   */
  encrypt(replyMessage: string): {
    encrypt: string;
    signature: string;
    timestamp: string;
    nonce: string;
  } {
    const timestamp = Math.floor(Date.now() / 1000).toString();
    const nonce = generateRandomString();
    const encrypt = encryptMessage(replyMessage, this.aesKey, this.corpId);
    const signature = calculateSignature(
      this.token,
      timestamp,
      nonce,
      encrypt,
    );
    return { encrypt, signature, timestamp, nonce };
  }
}
