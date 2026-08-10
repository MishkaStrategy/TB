# Self-hosted runner selector policy

Workflow jobs use capability selectors, never physical runner names. The project allowlist is intentionally exact so CI routing stays reproducible and auditable.

## Allowed selectors

Only these self-hosted selectors are permitted:

```yaml
runs-on: [self-hosted, fast]
runs-on: [self-hosted, docker]
runs-on: [self-hosted, backtester]
runs-on: [self-hosted, Linux]
runs-on: [self-hosted, macOS, ARM64]
```

Use them as follows:

- `[self-hosted, fast]` — linters, type checks, unit tests, documentation and fast application checks;
- `[self-hosted, docker]` — Docker, Compose and container integration checks;
- `[self-hosted, backtester]` — long-running backtests, benchmarks and load checks;
- `[self-hosted, Linux]` — checks that specifically require a native Linux/systemd environment;
- `[self-hosted, macOS, ARM64]` — Apple Silicon/macOS or Apple API checks.

Bare `self-hosted`, arbitrary capability combinations, machine names and undocumented labels are forbidden. GitHub-hosted runners are not a convenience fallback; if a future job genuinely requires a Linux dependency unavailable on the self-hosted fleet, that exception must be reviewed and documented together with the workflow change.

## Runner registration

Each runner must carry the exact capability labels needed by one of the selectors above. Labels describe capabilities, not individual machines.

## Enforcement

`.github/scripts/check_runner_selectors.py` scans every workflow and rejects any `runs-on` value outside the allowlist. `.github/workflows/runner-label-policy.yml` runs the check on runner-policy/workflow changes and on manual dispatch.
