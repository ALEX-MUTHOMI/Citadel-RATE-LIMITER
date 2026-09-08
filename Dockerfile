FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    DJANGO_SETTINGS_MODULE=citadel.settings.development

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
# Production dependencies — heavy layer, cached independently.
RUN poetry install --only main --no-interaction --no-ansi --no-root

# Dev/test packages (pure Python — no compiled extensions).
# Install separately so the prod layer above stays cached even on retry.
# Retry flags guard against Docker Desktop / PyPI network blips on Windows.
RUN pip install --no-cache-dir \
        --retries 10 --timeout 180 \
        "pytest>=8.3,<9" "pytest-django>=4.10,<5" "coverage>=7.8,<8"

COPY . .
RUN sed -i 's/\r$//' docker/entrypoint.sh \
    && chmod +x docker/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=8 \
    CMD curl -fsS http://127.0.0.1:8000/health/ || exit 1

ENTRYPOINT ["/bin/sh", "/app/docker/entrypoint.sh"]
