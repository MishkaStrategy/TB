# MishkaStrategy CI storage policy

1. GitHub Actions artifacts are temporary only. Every `actions/upload-artifact` must set `retention-days: 1`.
2. Routine successful CI must not upload artifacts. Temporary artifacts are allowed only for failure/cancelled diagnostics.
3. Small canonical manifests belong in the repository `evidence` branch and must be bound to repository, exact commit SHA, workflow run/attempt, timestamp and SHA-256 where applicable.
4. Large or canonical immutable evidence must be published directly to a GitHub Release from the same job. Do not use VDS or Actions artifact storage as the permanent evidence store.
5. Workflows must enforce this policy. Use `.github/actions/publish-release-evidence` for canonical files and `.github/workflows/org-storage-policy.yml` to reject regressions. Review obsolete GitHub Packages separately when storage pressure appears.
