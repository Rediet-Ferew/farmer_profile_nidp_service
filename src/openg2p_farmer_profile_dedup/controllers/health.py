from fastapi import APIRouter

from ..config import get_settings


class HealthController:
    def __init__(self):
        self.router = APIRouter(tags=["health"])
        self.router.add_api_route("/health", self.health, methods=["GET"])

    async def health(self):
        settings = get_settings()
        return {
            "status": "ok",
            "service": settings.openapi_title,
            "version": settings.openapi_version,
        }
