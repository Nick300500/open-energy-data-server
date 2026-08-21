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

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

# Copied separately from the rest of the source so `poetry install` is only
# re-run (and re-cached) when dependencies actually change, not on every
# code edit.
COPY pyproject.toml /app/pyproject.toml
RUN poetry install --no-root --only main

COPY . /app
RUN chmod +x docker/entrypoint.sh

CMD ["bash", "./docker/entrypoint.sh"]
