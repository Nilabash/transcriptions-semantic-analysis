# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POLARS_SKIP_CPU_CHECK=0

WORKDIR /workspace

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin ta

COPY pyproject.toml README.md requirements-lock.txt ./
COPY src ./src
COPY tests ./tests
COPY scripts/docker-entrypoint-analytics.sh /usr/local/bin/docker-entrypoint-analytics.sh

# Guard against stale BuildKit layers that copied empty stubs (ImportError: cannot import name main).
RUN python -c "from pathlib import Path; p = Path('src/transcriptions_analysis/cli.py'); n = p.stat().st_size; assert n >= 6144, ('cli.py is %sb in build context; verify host file then: docker compose build --no-cache analytics' % n); t = p.read_text(encoding='utf-8'); assert 'def main(' in t, 'cli.py missing def main'"
RUN pip install --upgrade pip \
    && pip install -e ".[dev]" \
    && chmod +x /usr/local/bin/docker-entrypoint-analytics.sh \
    && python -c "from transcriptions_analysis.cli import main; assert callable(main)"

USER ta

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-analytics.sh"]

FROM base AS notebook

USER root
RUN pip install "jupyterlab>=4,<5"
USER ta

EXPOSE 8888

CMD ["/bin/sh", "-c", "exec jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --notebook-dir=/workspace --IdentityProvider.token=${JUPYTER_TOKEN:-}"]
