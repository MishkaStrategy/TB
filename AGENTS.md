# AGENTS.md — MishkaStrategy/TB AI bootstrap

## Organization AI policy

For every non-trivial task in `MishkaStrategy/TB`, load the current `main` version of `MishkaStrategy/.github/AI_AGENT_POLICY.md` once for the current working session.

Do not automatically load `AI_SKILL_ROUTING.md`. Load it only when non-obvious Skill/Plugin selection, a specialized workflow, or capability discovery is materially needed.

In ordinary ChatGPT Chat, the current conversation remains one working session across commits, PRs, merges, CI cycles, reviews, and milestones. Reuse unchanged organization/repository instructions and already-loaded Skill instructions; between steps refresh only material mutable GitHub state and files known to have changed.

A PR, merge, green CI result, milestone, elapsed time, or perceived context size is not by itself a reason to stop, hand off, reload policy, or create a fresh chat. A technical/platform limit must be concrete, not inferred.

Repository-specific instructions in this repository take precedence over organization defaults where they conflict. Platform safety/permission rules and the user's explicit current request remain higher priority.

GitHub is the source of truth for repository state. Re-verify the mutable facts needed for state-dependent claims or changes; old chat summaries and handoffs are orientation only.

Do not copy the full organization policy into this repository. Keep organization-wide rules centralized in `MishkaStrategy/.github`.