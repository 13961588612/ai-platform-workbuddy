/**
 * Agent-related type definitions for the frontend.
 *
 * These types mirror the backend's AgentConfig (src/agent/config.py),
 * AgentSummary / AgentDetail (src/api/routes/agent.py) and
 * InstanceState (src/agent/lifecycle.py) — converted from
 * snake_case (Python) to camelCase (TypeScript) convention.
 */

// ===== Agent Lifecycle =====

/** Agent instance lifecycle states. */
export type AgentState =
  | "created"
  | "starting"
  | "running"
  | "paused"
  | "stopping"
  | "stopped"
  | "error";

// ===== Agent Summary (list response) =====

/** Summary of an Agent instance for list responses. */
export interface AgentSummary {
  agentId: string;
  displayName: string;
  state: AgentState;
  runtimeType: string;
  activeSessions: number;
  isActive: boolean;
}

// ===== Agent Detail =====

/** Detailed Agent information. */
export interface AgentDetail {
  agentId: string;
  displayName: string;
  description: string;
  version: string;
  tags: string[];
  state: AgentState;
  runtimeType: string;
  activeSessions: number;
  modelPrimary: string;
  modelFallback: string;
  routingEnabled: boolean;
  routingPriority: number;
  routingKeywords: string[];
  startedAt: string | null;
}

// ===== Agent Config sub-sections =====

/** Runtime type and parameters for an Agent. */
export interface RuntimeConfig {
  type: string;
  version: string;
  params: Record<string, unknown>;
  prompts: Record<string, string>;
  middleware: Record<string, unknown>;
}

/** LLM model configuration for an Agent. */
export interface ModelConfig {
  primary: string;
  fallback: string;
  strategy: string;
  gateway: string;
}

/** Reference to a Skill in an Agent's configuration. */
export interface SkillRef {
  skillId: string;
  enabled: boolean;
  overrides: Record<string, unknown>;
}

/** MCP Server connection configuration. */
export interface MCPServerConfig {
  name: string;
  transport: string;
  endpoint: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
}

/** Access control configuration for an Agent. */
export interface AccessControl {
  departments: string[];
  roles: string[];
  skillPermissions: Record<string, string[]>;
  sensitiveOps: Record<string, unknown>[];
}

/** Proactive push configuration for an Agent. */
export interface PushConfig {
  enabled: boolean;
  channels: string[];
  schedules: Record<string, unknown>[];
}

/** Agent memory configuration. */
export interface MemoryConfig {
  staticEnabled: boolean;
  personalityFile: string;
  factsDir: string;
  dynamicEnabled: boolean;
  collection: string;
  topK: number;
  writeBack: boolean;
  ttlDays: number;
  maxPerUser: number;
}

/** AgentRouter routing configuration for an Agent. */
export interface RoutingConfig {
  keywords: string[];
  enabled: boolean;
  priority: number;
}

/** Agent metadata for AgentRouter semantic search. */
export interface AgentMetadata {
  name: string;
  displayName: string;
  description: string;
  tags: string[];
  version: string;
  enabled: boolean;
  capabilities: string[];
}

// ===== Complete Agent Config =====

/** Complete configuration for an Agent instance. */
export interface AgentConfig {
  agentId: string;
  name: string;
  displayName: string;
  description: string;
  version: string;
  tags: string[];
  runtime: RuntimeConfig;
  model: ModelConfig;
  systemPrompt: string;
  skills: SkillRef[];
  mcpServers: MCPServerConfig[];
  accessControl: AccessControl;
  push: PushConfig;
  memory: MemoryConfig;
  routing: RoutingConfig;
  metadata: AgentMetadata | null;
  createdAt: string;
  updatedAt: string;
  includes: Record<string, string>;
  configPath: string;
}

// ===== Create / Update Agent Request =====

/** Request body for creating a new Agent. */
export interface CreateAgentRequest {
  agentId: string;
  displayName: string;
  description: string;
  version: string;
  tags: string[];
  runtimeType: string;
  modelPrimary: string;
  modelFallback: string;
  keywords: string[];
  routingEnabled: boolean;
  routingPriority: number;
}

/** Request body for updating an Agent's configuration. */
export interface UpdateAgentRequest {
  displayName?: string;
  description?: string;
  version?: string;
  tags?: string[];
  keywords?: string[];
  routingEnabled?: boolean;
  routingPriority?: number;
}
