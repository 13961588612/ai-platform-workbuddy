/**
 * Agent API adapter — normalizes backend snake_case to frontend camelCase.
 */

import type { AgentState, AgentSummary } from "../types/agent";

/** Raw agent summary as returned by GET /api/v1/agents. */
export interface RawAgentSummary {
  agent_id?: string;
  agentId?: string;
  display_name?: string;
  displayName?: string;
  state?: string;
  runtime_type?: string;
  runtimeType?: string;
  active_sessions?: number;
  activeSessions?: number;
  is_active?: boolean;
  isActive?: boolean;
}

/** Convert a backend agent summary to frontend AgentSummary. */
export function normalizeAgentSummary(raw: RawAgentSummary): AgentSummary {
  return {
    agentId: raw.agentId ?? raw.agent_id ?? "",
    displayName: raw.displayName ?? raw.display_name ?? raw.agent_id ?? "",
    state: (raw.state ?? "stopped") as AgentState,
    runtimeType: raw.runtimeType ?? raw.runtime_type ?? "",
    activeSessions: raw.activeSessions ?? raw.active_sessions ?? 0,
    isActive: raw.isActive ?? raw.is_active ?? false,
  };
}

/** Normalize a list of agent summaries from the API. */
export function normalizeAgentList(
  items: RawAgentSummary[] | null | undefined,
): AgentSummary[] {
  return (items ?? [])
    .map(normalizeAgentSummary)
    .filter((agent) => agent.agentId.length > 0);
}
