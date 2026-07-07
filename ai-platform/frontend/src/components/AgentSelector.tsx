/**
 * AgentSelector — Agent selection dropdown component.
 *
 * Fetches the list of available agents from the backend API
 * (GET /api/v1/agents) and provides a dropdown for the user
 * to select which Agent to chat with.
 *
 * Displays agent display name and state badge.
 */

import React, { useCallback, useEffect, useState } from "react";
import { apiGet } from "../utils/api";
import { normalizeAgentList, type RawAgentSummary } from "../utils/agentAdapter";
import { getAgentStateLabel, getAgentStateColor, clsx } from "../utils/format";
import type { AgentSummary, AgentState } from "../types/agent";

// ===== Types =====

/** Props for the AgentSelector component. */
interface AgentSelectorProps {
  /** Currently selected agent ID. */
  value: string | null;
  /** Callback when the selection changes. */
  onChange: (agentId: string) => void;
}

// ===== Component =====

/**
 * AgentSelector — dropdown for selecting an Agent to chat with.
 *
 * Fetches the agent list on mount and provides a native select
 * element styled with Tailwind. Only shows agents that are
 * running or paused (i.e., available for chat).
 */
export function AgentSelector({
  value,
  onChange,
}: AgentSelectorProps): JSX.Element {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch agent list
  useEffect(() => {
    let cancelled = false;

    const fetchAgents = async (): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await apiGet<RawAgentSummary[]>("/agents");
        if (!cancelled) {
          const availableAgents = normalizeAgentList(data).filter(
            (agent) => agent.state === "running" || agent.state === "paused",
          );
          setAgents(availableAgents);

          // Auto-select first available agent if none selected
          if (!value && availableAgents.length > 0) {
            onChange(availableAgents[0].agentId);
          }
        }
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof Error ? err.message : "获取 Agent 列表失败";
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    fetchAgents();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle change
  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>): void => {
      onChange(e.target.value);
    },
    [onChange],
  );

  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="agent-selector"
        className="text-sm font-medium text-surface-dark/70"
      >
        Agent:
      </label>
      <select
        id="agent-selector"
        value={value ?? ""}
        onChange={handleChange}
        disabled={isLoading || !!error}
        className={clsx(
          "rounded-md border border-surface-light bg-white px-3 py-1.5 text-sm",
          "focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        {isLoading && <option value="">加载中...</option>}
        {error && <option value="">加载失败</option>}
        {!isLoading && !error && agents.length === 0 && (
          <option value="">暂无可用 Agent</option>
        )}
        {!isLoading &&
          !error &&
          agents.map((agent: AgentSummary) => (
            <option key={agent.agentId} value={agent.agentId}>
              {agent.displayName} ({agent.state})
            </option>
          ))}
      </select>

      {/* State Badge for Selected Agent */}
      {value && agents.length > 0 && (
        <SelectedAgentBadge agents={agents} agentId={value} />
      )}
    </div>
  );
}

// ===== Selected Agent Badge =====

/** Display a state badge for the currently selected agent. */
function SelectedAgentBadge({
  agents,
  agentId,
}: {
  agents: AgentSummary[];
  agentId: string;
}): JSX.Element | null {
  const agent = agents.find((a) => a.agentId === agentId);
  if (!agent) {
    return null;
  }

  const stateLabel = getAgentStateLabel(agent.state as AgentState);
  const stateColor = getAgentStateColor(agent.state as AgentState);

  return (
    <span
      className={clsx(
        "rounded-full px-2 py-0.5 text-xs font-medium",
        stateColor,
      )}
    >
      {stateLabel}
    </span>
  );
}

export default AgentSelector;
