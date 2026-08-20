# AGENTS.md — MishkaStrategy/TB AI bootstrap

## Organization AI policy

For every non-trivial task in `MishkaStrategy/TB`, load the current `main` versions of the canonical organization policy files from `MishkaStrategy/.github` before execution:

- `AI_AGENT_POLICY.md`;
- `AI_SKILL_ROUTING.md`.

Use connected GitHub access when available. Load organization policy once at the start of a working session, after a material pause, or when policy may have changed. Do not refetch unchanged policy before every tiny subtask.

Repository-specific instructions in this repository take precedence over organization defaults where they conflict. Platform safety/permission rules and the user's explicit current request remain higher priority.

GitHub is the source of truth for repository state. Re-verify material current state before state-dependent claims or changes; old chat summaries and handoffs are orientation only.

Do not copy the full organization policy into this repository. Keep organization-wide rules centralized in `MishkaStrategy/.github`.
