from citadel.settings.base import *  # noqa: F401,F403

DEBUG = True

if not SECRET_KEY:
    SECRET_KEY = "dev-only-insecure-key"

if not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["*"]

# SQLite fallback so local pytest and first-run work without Postgres.
if not os.getenv("POSTGRES_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

if os.getenv("RATE_LIMIT_BACKEND", "memory") == "memory" or not os.getenv("REDIS_URL"):
    RATE_LIMIT_BACKEND = "memory"
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "citadel-dev",
        }
    }
