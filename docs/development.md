# Development

## Local Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Main Commands

```powershell
pytest
ta-batch run --help
ta-batch staging-parquet --help
```

Docker-based test run:

```bash
docker compose run --rm --entrypoint python analytics -m pytest /workspace/tests
```

Lint example:

```bash
docker compose run --rm --user 0:0 --workdir /workspace --entrypoint ruff analytics check src tests
```

## Repository Layout

| Path | Purpose |
|------|------|
| `src/transcriptions_analysis/` | Package code |
| `scripts/` | Helper scripts |
| `tests/` | Pytest suite |
| `tests/fixtures/` | Small multiline CSV fixtures |
| `docs/` | Public documentation |
| `outputs/` | Generated run artifacts |

## Contributor Notes

- Prefer keeping the public docs aligned with code and tests.
- Treat the CSV schema in [data-contract.md](data-contract.md) as the public input contract.
- Keep new output artifacts documented in [operations.md](operations.md).
- Keep new modules or pipeline stages documented in [architecture.md](architecture.md).

## Testing Focus

The existing tests cover:

- multiline CSV ingest
- transcript parsing
- Layer A metrics
- Layer B metrics
- aggregation
- content category logic
- visual report generation

## Auxiliary Scripts

| Script | Purpose |
|------|------|
| `scripts/analyze_raw_transcriptions.py` | Ad-hoc raw CSV summary outside `ta-batch` |
| `scripts/build_final_research_report.py` | Builds a standalone final HTML from an existing run |
| `scripts/build_duration_distribution_report.py` | Builds a standalone duration-distribution HTML and monthly duration stats CSV from an existing run |
