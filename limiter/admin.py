from django.contrib import admin

from limiter.models import ClientProject


@admin.register(ClientProject)
class ClientProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "algorithm", "capacity", "refill_rate", "is_active")
    search_fields = ("name",)
    readonly_fields = ("token_hash", "created_at")
