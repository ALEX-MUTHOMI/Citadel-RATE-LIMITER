from django.urls import path

from limiter.views import RateLimitCheckView

urlpatterns = [
    path("limits/check/", RateLimitCheckView.as_view(), name="rate-limit-check"),
]
