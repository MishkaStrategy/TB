# Self-hosted runner label policy

Every job that targets a self-hosted GitHub Actions runner **must declare the capabilities it actually needs**. A bare `runs-on: self-hosted` or `runs-on: [self-hosted]` is forbidden.

GitHub treats a label array as an intersection: a runner must match every specified label before it can accept the job.

## Required selection patterns

- Docker required: `runs-on: [self-hosted, docker]`
- macOS required: `runs-on: [self-hosted, macos]`
- Any general-purpose fast self-hosted machine: `runs-on: [self-hosted, fast]`
- Multiple hard requirements: `runs-on: [self-hosted, fast, docker]`

Add other capability labels only when they are real requirements, for example `linux`, `windows`, `arm64`, `x64`, `gpu`, or a project-specific toolchain label.

Do not select a physical machine by name unless the workflow truly cannot run anywhere else. Prefer capability labels so jobs can move between suitable runners.

GitHub-hosted runners such as `ubuntu-latest`, `macos-latest`, and `windows-latest` remain allowed when intentionally used.

## Runner registration

Each self-hosted runner must carry all labels that describe its available capabilities. For example, a fast Linux runner with Docker should have at least `self-hosted`, `fast`, `linux`, and `docker`.

## Enforcement

`.github/workflows/runner-label-policy.yml` checks all workflow files and fails when a self-hosted job has no additional capability label.
