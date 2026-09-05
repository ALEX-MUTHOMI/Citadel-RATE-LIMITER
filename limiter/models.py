import hashlib

from django.db import models


class Algorithm(models.TextChoices):
    TOKEN_BUCKET = "token_bucket", "Token bucket"
    SLIDING_WINDOW = "sliding_window", "Sliding window"
    SHOPIFY_LEAKY_BUCKET = "shopify_leaky_bucket", "Shopify leaky bucket"


class ClientProject(models.Model):
    name = models.CharField(max_length=128, unique=True)
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    algorithm = models.CharField(
        max_length=32,
        choices=Algorithm.choices,
        default=Algorithm.TOKEN_BUCKET,
    )
    capacity = models.PositiveIntegerField(default=40)
    refill_rate = models.FloatField(default=2.0)
    window_seconds = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
