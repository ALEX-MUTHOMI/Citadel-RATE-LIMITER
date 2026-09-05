from django.conf import settings
from django.core.management.base import BaseCommand

from limiter.models import ClientProject


class Command(BaseCommand):
    help = "Create or update the bootstrap client from CITADEL_API_TOKEN."

    def handle(self, *args, **options):
        raw = getattr(settings, "CITADEL_API_TOKEN", "")
        name = getattr(settings, "CITADEL_BOOTSTRAP_CLIENT", "local-docker")
        if not raw:
            self.stdout.write("CITADEL_API_TOKEN is not set; skipping bootstrap.")
            return
        token_hash = ClientProject.hash_token(raw)
        client, created = ClientProject.objects.update_or_create(
            name=name,
            defaults={"token_hash": token_hash, "is_active": True},
        )
        action = "created" if created else "updated"
        self.stdout.write(f"Bootstrap client {action}: {client.name}")
