# CLAUDE.md — Frontend

This frontend's agent guidance lives in **[AGENTS.md](./AGENTS.md)** (single source
of truth, cross-tool). Read it before working in `frontend/`.

Claude-specific reminders (the rest is in AGENTS.md):

- The repo-root `CLAUDE.md` governs the whole project (Atomic Spec framework,
  testing gotchas, constitution). This file scopes the **frontend**.
- **Biome, not eslint.** Tests run on the **host**, not the frontend container.
- Feature 004 (agentic transparency UI) is documented in AGENTS.md: the SSE
  event model (`lib/sse/agent-events.ts`) is the single source of truth, the
  agentic flag gate is **transitive** (gate on `activityLog.entries.length`,
  never a frontend flag), and the same components render on both the main chat
  and the admin sandbox.
- See AGENTS.md "Known follow-ups" for the tracked review debt before extending
  the transparency UI.
