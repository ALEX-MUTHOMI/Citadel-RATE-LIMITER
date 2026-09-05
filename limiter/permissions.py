from rest_framework.permissions import BasePermission


class HasCitadelToken(BasePermission):
    message = "Provide a valid X-Citadel-Token header."

    def has_permission(self, request, view) -> bool:
        return getattr(request, "citadel_client", None) is not None
