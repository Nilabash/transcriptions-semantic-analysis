# Documentation

This folder contains the deeper technical and operational documentation for the repository. Start with the top-level [README](../README.md) for the project overview, then use the pages here when you need implementation or runbook detail.

| Document | Audience | Purpose |
|----------|----------|---------|
| [Architecture](architecture.md) | Engineers, maintainers, analysts | Explains the batch pipeline, package layout, output artifacts, and current system boundaries |
| [Operations](operations.md) | Anyone running jobs locally or in Docker | Documents Compose behavior, CLI flags, environment variables, output layout, and troubleshooting |

## Suggested Reading Order

1. [README](../README.md) for the high-level project story and quick start.
2. [Operations](operations.md) if you want to run the pipeline.
3. [Architecture](architecture.md) if you want to modify or extend the codebase.

## Scope Note

The documents in this folder are intended to stay aligned with the implemented behavior in `src/transcriptions_analysis/` and the public developer workflow exposed by the repository.
