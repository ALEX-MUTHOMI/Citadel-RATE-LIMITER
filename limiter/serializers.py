from rest_framework import serializers


class RateLimitCheckSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=256)
    cost = serializers.FloatField(min_value=0.01, default=1)
