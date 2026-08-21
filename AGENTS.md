# AGENTS.md — MishkaStrategy/TB AI bootstrap

## Organization AI policy

For every non-trivial task in `MishkaStrategy/TB`, load the current `main` version of `MishkaStrategy/.github/AI_AGENT_POLICY.md` once for the current working session.

Use `AI_SKILL_ROUTING.md` whenever specialized Skill/Plugin selection is materially relevant, non-obvious, or required. Do not skip a relevant specialized workflow merely to save context, latency, or tool calls.

In ordinary ChatGPT Chat, the current conversation remains one working session across commits, PRs, merges, CI cycles, reviews, and milestones. Reuse unchanged instructions when safe, but reread any policy, prompt, architecture material, or Skill instructions whenever correctness, uncertainty, a failure, or a changed task stage makes that useful.

Context efficiency is only an optimization of redundant retrieval. It must never reduce reasoning depth, necessary repository/code inspection, verification quality, relevant Skill use, answer completeness, or the product-level model/reasoning mode selected by the user.

A PR, merge, green CI result, milestone, elapsed time, or perceived context size is not by itself a reason to stop, hand off, or create a fresh chat. A technical/platform limit must be concrete, not inferred.

Repository-specific instructions in this repository take precedence over organization defaults where they conflict. Platform safety/permission rules and the user's explicit current request remain higher priority.

GitHub is the source of truth for repository state. Re-verify mutable facts needed for state-dependent claims or changes; reread stable context whenever it materially improves correctness. Old chat summaries and handoffs are orientation only.

Do not copy the full organization policy into this repository. Keep organization-wide rules centralized in `MishkaStrategy/.github`.