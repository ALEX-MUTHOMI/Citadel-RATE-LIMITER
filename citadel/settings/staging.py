from django.core.exceptions import ImproperlyConfigured

from citadel.settings.base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,api").split(",")
    if host.strip()
]

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in staging.")
