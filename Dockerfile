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

COPY pyproject.toml ./
RUN poetry install --only main --no-interaction --no-ansi --no-root

COPY . .
RUN poetry install --only main --no-interaction --no-ansi \
    && chmod +x docker/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health/ || exit 1

ENTRYPOINT ["./docker/entrypoint.sh"]
