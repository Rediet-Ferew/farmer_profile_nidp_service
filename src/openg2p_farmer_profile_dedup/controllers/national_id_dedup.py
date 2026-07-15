from fastapi import APIRouter

from ..schemas import DedupRunRequest, DedupRunResponse, DedupStatusResponse
from ..services import get_background_worker


class NationalIdDedupController:
    def __init__(self):
        self.router = APIRouter(prefix="/national-id-dedup", tags=["national-id-dedup"])
        self.worker = get_background_worker()
        self.router.add_api_route(
            "/run-once",
            self.run_once,
            methods=["POST"],
            response_model=DedupRunResponse,
        )
        self.router.add_api_route(
            "/status",
            self.status,
            methods=["GET"],
            response_model=DedupStatusResponse,
        )

    async def run_once(self, request: DedupRunRequest | None = None):
        request = request or DedupRunRequest()
        return await self.worker.run_once_with_lock(
            limit=request.limit,
            dry_run=request.dry_run,
        )

    async def status(self):
        status = self.worker.service.get_status().model_dump()
        status.update(self.worker.get_status_values())
        return DedupStatusResponse.model_validate(status)
