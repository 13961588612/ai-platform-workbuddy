"""
AI Platform — Agent Core Backend Package.

This package contains all backend service modules:
- api/        — FastAPI route handlers
- agent/      — Agent lifecycle management
- router/     — AgentRouter intelligent routing
- llm/        — LLM Gateway (multi-provider, key pool, quota, proxy)
- skills/     — Skill registry, retrieval, ranking
- identity/   — Authentication and authorization
- mcp/        — MCP Server management
- runtime/    — Agent runtime abstraction (OpenHarness)
- config_manager/ — Configuration management (file + DB dual mode)
- memory/     — Agent memory mechanism (static + dynamic)
- models/     — SQLAlchemy data models
- db/         — Database session management
- utils/      — Shared utilities
- push/       — Proactive push service
- hitl/       — Human-in-the-loop approval workflow
"""
