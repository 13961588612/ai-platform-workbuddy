/**
 * Skill-related type definitions for the frontend.
 *
 * Mirrors backend's src/skills/models.py — Skill, SkillCreateRequest,
 * SkillUpdateRequest, SkillListResponse — converted to camelCase TS.
 */

// ===== Enums =====

/** Origin of a Skill. */
export type SkillSource = "custom" | "mcp" | "builtin";

/** Lifecycle status of a Skill. */
export type SkillStatus = "active" | "inactive" | "deprecated";

/** Top-level Skill categories aligned with business systems. */
export type SkillCategory =
  | "finance"
  | "retail"
  | "department_store"
  | "hr"
  | "property"
  | "crm"
  | "valuecard"
  | "built_in";

// ===== Skill Parameter =====

/** A single parameter definition for a Skill (JSON-Schema-like). */
export interface SkillParameter {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default: unknown;
  enum: unknown[] | null;
}

// ===== Skill =====

/** Canonical Skill representation used throughout the platform. */
export interface Skill {
  skillId: string;
  name: string;
  description: string;
  category: SkillCategory;
  tags: string[];
  parameters: Record<string, unknown>;
  requiredPermissions: string[];
  handler: string;
  timeout: number;
  version: string;
  status: SkillStatus;
  source: SkillSource;
  priority: number;
  requiresApproval: boolean;
  mcpServer: string | null;
  callCount: number;
  lastCalledAt: string | null;
}

// ===== Skill Score (for ranking display) =====

/** A Skill paired with its retrieval/ranking score. */
export interface SkillScore {
  skill: Skill;
  score: number;
  semanticSimilarity: number;
  usageFrequency: number;
  recencyBonus: number;
  categoryMatch: number;
}

// ===== Create / Update Requests =====

/** Request body for creating a new Skill via API. */
export interface SkillCreateRequest {
  skillId: string;
  name: string;
  description: string;
  category: SkillCategory;
  tags: string[];
  parameters: Record<string, unknown>;
  requiredPermissions: string[];
  handler: string;
  timeout: number;
  version: string;
  priority: number;
  requiresApproval: boolean;
}

/** Request body for partially updating a Skill. */
export interface SkillUpdateRequest {
  name?: string;
  description?: string;
  category?: SkillCategory;
  tags?: string[];
  parameters?: Record<string, unknown>;
  requiredPermissions?: string[];
  handler?: string;
  timeout?: number;
  version?: string;
  status?: SkillStatus;
  priority?: number;
  requiresApproval?: boolean;
}

// ===== List Response =====

/** Paginated list of Skills. */
export interface SkillListResponse {
  items: Skill[];
  total: number;
  page: number;
  pageSize: number;
}

// ===== Statistics =====

/** Registry statistics response. */
export interface SkillStats {
  total: number;
  active: number;
  inactive: number;
  byCategory: Record<string, number>;
  bySource: Record<string, number>;
}
