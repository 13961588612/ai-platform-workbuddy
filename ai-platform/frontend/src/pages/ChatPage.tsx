/**
 * ChatPage — Main AI chat page.
 *
 * Full-screen chat interface with the ChatPanel component.
 * Includes an authentication guard — redirects to /login if not
 * authenticated.
 */

import { useEffect } from "react";
import { Navigate } from "react-router-dom";
import { ChatPanel } from "../components/ChatPanel";
import { useAuthStore } from "../store/authStore";

// ===== Component =====

/**
 * ChatPage — the primary AI conversation interface.
 *
 * Renders the ChatPanel in a full-height container.
 * Redirects to /login if the user is not authenticated.
 */
export function ChatPage(): JSX.Element {
  const { isAuthenticated, initialize } = useAuthStore();

  // Initialize auth state on mount
  useEffect(() => {
    initialize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auth guard
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="h-screen w-full bg-surface-muted">
      <ChatPanel />
    </div>
  );
}

export default ChatPage;
