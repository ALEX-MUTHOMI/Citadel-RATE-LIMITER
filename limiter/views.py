from rest_framework.response import Response
from rest_framework.views import APIView

from limiter.models import ClientProject
from limiter.permissions import HasCitadelToken
from limiter.serializers import RateLimitCheckSerializer
from limiter.services import RateLimiterService
from limiter.shopify.adapter import to_shopify_headers


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        return Response({"status": "ok", "service": "citadel-rate-limiter"})


class RateLimitCheckView(APIView):
    authentication_classes: list = []
    permission_classes = [HasCitadelToken]

    def initial(self, request, *args, **kwargs):
        raw = request.headers.get("X-Citadel-Token", "")
        request.citadel_client = None
        if raw:
            token_hash = ClientProject.hash_token(raw)
            request.citadel_client = ClientProject.objects.filter(
                token_hash=token_hash,
                is_active=True,
            ).first()
        super().initial(request, *args, **kwargs)

    def post(self, request):
        serializer = RateLimitCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        decision = RateLimiterService(request.citadel_client).consume(
            serializer.validated_data["key"],
            serializer.validated_data["cost"],
        )
        payload = {
            "allowed": decision.allowed,
            "remaining": decision.remaining,
            "limit": decision.limit,
            "retry_after": decision.retry_after,
            "algorithm": request.citadel_client.algorithm,
            "shopify": to_shopify_headers(decision),
        }
        status = 200 if decision.allowed else 429
        response = Response(payload, status=status)
        if not decision.allowed:
            response["Retry-After"] = str(int(decision.retry_after) or 1)
        return response
