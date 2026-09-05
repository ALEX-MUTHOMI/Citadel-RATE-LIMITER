# Citadel Rate Limiter

Shared Django REST rate limiter for other Citadel projects. Other apps send a project token and a limit key; this service allows or denies the request using token bucket, sliding window, or Shopify-style leaky bucket.

## Branches

| Branch | GitHub environment | Use |
| --- | --- | --- |
| `DEVELOPMENT` (default) | `development` | Local and CI work |
| `STAGING` | `staging` | Pre-production |
| `MAIN` | `production` | Production |

## Secret hygiene

Never commit live credentials. The repository ignores `.env`, `docker/secrets/`, keys, and token files. GitHub Actions runs Gitleaks on every push.

**Keep in GitHub only (already set):**

- Repository secret `DOCKERHUB_TOKEN`
- Repository secret `DOCKERHUB_USERNAME`
- Environment variables `DOCKER_REGISTRY`, `IMAGE_NAME`, `DOCKERHUB_USERNAME`

**Keep on your machine only:**

1. Copy `.env.example` to `.env`
2. Fill `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, and `CITADEL_API_TOKEN`
3. Do not paste Docker Hub tokens into the repo, README, or chat

Docker Hub login stays local:

```powershell
docker login -u backtofrontdev
```

Use a Hub access token as the password. GitHub Actions reads `secrets.DOCKERHUB_TOKEN`; it does not read files from this repo.

## Local Python

Requires Python 3.12+ and [Poetry](https://python-poetry.org/).

```powershell
copy .env.example .env
poetry install
poetry run python manage.py migrate
poetry run python manage.py bootstrap_client
poetry run python manage.py runserver
poetry run pytest
```

Pip fallback:

```powershell
python -m pip install -r requirements/development.txt
```

DSA simulator:

```powershell
poetry run python -m limiter.dsa --algorithm token_bucket --requests 20
```

## Docker Desktop

```powershell
copy .env.example .env
docker compose up --build
```

This starts **api**, **postgres**, and **redis** (`citadel-api`, `citadel-postgres`, `citadel-redis` in Docker Desktop). GitHub Actions publishes the image with `vars.DOCKERHUB_USERNAME` and `secrets.DOCKERHUB_TOKEN`. Re-save the token in GitHub if login fails: no quotes, no extra spaces.

Host ports: API `8000`, Postgres `5433`, Redis `6380` (5432/6379 are often already in use on Windows).

| Service | URL |
| --- | --- |
| Rate limiter API | http://localhost:8000 |
| Health | http://localhost:8000/health/ |
| OpenAPI docs | http://localhost:8000/api/docs/ |
| Postgres | localhost:5433 |
| Redis | localhost:6380 |

## Connect another project

```http
POST /api/v1/limits/check/
X-Citadel-Token: <CITADEL_API_TOKEN>
Content-Type: application/json

{"key": "orders:create:shop-1", "cost": 1}
```

`200` means allowed. `429` means limited; `Retry-After` is set.

## Layout

```
citadel/     Django project and settings
limiter/     REST API, DSA algorithms, Shopify adapter
docker/      Compose helpers (Toxiproxy)
requirements/  pip extras generated from Poetry
.github/     CI, secret scan, Docker Hub publish
```
