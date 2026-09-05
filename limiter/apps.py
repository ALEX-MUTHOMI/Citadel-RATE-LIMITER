from django.apps import AppConfig


class LimiterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "limiter"
    verbose_name = "Citadel Rate Limiter"
