/** Session API 响应归一化（Backend snake_case → Frontend） */

export interface RawCreateSessionResponse {
  session_id?: string;
  sessionId?: string;
  agent_id?: string;
  agentId?: string;
  user_id?: string;
  userId?: string;
  channel?: string;
  runtime_type?: string;
  runtimeType?: string;
}

export interface CreateSessionResult {
  sessionId: string;
  agentId: string;
  userId: string;
  channel: string;
}

export function normalizeCreateSessionResponse(
  raw: RawCreateSessionResponse,
): CreateSessionResult {
  const sessionId = raw.sessionId ?? raw.session_id ?? "";
  if (!sessionId) {
    throw new Error("创建会话失败：服务端未返回 session_id");
  }
  return {
    sessionId,
    agentId: raw.agentId ?? raw.agent_id ?? "",
    userId: raw.userId ?? raw.user_id ?? "",
    channel: raw.channel ?? "web",
  };
}
