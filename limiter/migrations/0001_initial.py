from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ClientProject",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=128, unique=True)),
                ("token_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                (
                    "algorithm",
                    models.CharField(
                        choices=[
                            ("token_bucket", "Token bucket"),
                            ("sliding_window", "Sliding window"),
                            ("shopify_leaky_bucket", "Shopify leaky bucket"),
                        ],
                        default="token_bucket",
                        max_length=32,
                    ),
                ),
                ("capacity", models.PositiveIntegerField(default=40)),
                ("refill_rate", models.FloatField(default=2.0)),
                ("window_seconds", models.PositiveIntegerField(default=60)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["name"],
            },
        ),
    ]
