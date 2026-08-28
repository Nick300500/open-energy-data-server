# Template: streamlit-app branch's Dockerfile (see server_zugang_recherche.md).
# Differs from it because this project uses Poetry ([tool.poetry] in
# pyproject.toml, no requirements.txt) and runs three background schedulers
# instead of a web UI -- see docker/entrypoint.sh.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH=/app
# PYTHONPATH=/app: needed so Python finds the cosema package when running
# `python schedulers/x.py` (the script's own directory goes on sys.path, not cwd).

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ libpq-dev libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# All three schedulers import pypsa concurrently at startup (see
# docker/entrypoint.sh) and pypsa's own check-then-mkdir for this directory
# isn't safe under that race -- observed FileExistsError crashing the
# container on first real deploy (2026-08-28). Pre-creating it here means
# it already exists by the time any of the three processes gets to it.
RUN mkdir -p /root/.local/share/pypsa-networks

RUN pip install poetry

# Copied separately from the rest of the source so `poetry install` is only
# re-run (and re-cached) when dependencies actually change, not on every
# code edit. poetry.lock is intentionally excluded from the later `COPY . /app`
# (see .dockerignore) -- it used to silently clobber the lock file poetry
# writes here with the (possibly stale) one sitting in the build context.
COPY pyproject.toml poetry.lock* /app/
RUN poetry install --no-root --only main

COPY . /app
RUN chmod +x docker/entrypoint.sh

CMD ["bash", "./docker/entrypoint.sh"]
