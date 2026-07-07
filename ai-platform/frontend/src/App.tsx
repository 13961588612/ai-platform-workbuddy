/**
 * Root application component.
 *
 * Renders the Router component which handles all route definitions
 * including:
 * - /login              — Login page (public)
 * - /chat               — AI chat interface (protected)
 * - /admin/skills       — Skill management (protected)
 * - /admin/monitor      — System monitoring (protected)
 * - /admin/approvals    — Approval center (protected)
 * - /admin/agents       — Agent management (protected, T06)
 * - /admin/users        — User permissions (protected, T06)
 *
 * The Router component includes an authentication guard that redirects
 * unauthenticated users to /login.
 *
 * BrowserRouter is configured in main.tsx.
 */

import { Router } from "./routes/router";

function App(): JSX.Element {
  return <Router />;
}

export default App;
