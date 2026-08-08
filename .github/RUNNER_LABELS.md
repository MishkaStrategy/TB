# Canonical runner selectors

Every GitHub Actions job must use exactly one selector:

```yaml
runs-on: [self-hosted, fast]
runs-on: [self-hosted, docker]
runs-on: [self-hosted, backtester]
runs-on: [self-hosted, macOS, ARM64]
```

All other selectors are forbidden, including hosted runners, bare `self-hosted`, dynamic or multiline values, lowercase `macos`, `Linux`, `X64`, combined capabilities, machine names and legacy `backtest`.

`.github/workflows/self-hosted-runner-policy.yml` executes the fail-closed checker for every workflow change.
