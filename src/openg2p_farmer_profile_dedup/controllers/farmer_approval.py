from fastapi import APIRouter

from ..schemas import (
    FarmerApprovalRunRequest,
    FarmerApprovalRunResponse,
    FarmerApprovalStatusResponse,
)
from ..services import get_farmer_approval_worker


class FarmerApprovalController:
    def __init__(self):
        self.router = APIRouter(prefix="/farmer-approval", tags=["farmer-approval"])
        self.worker = get_farmer_approval_worker()
        self.router.add_api_route(
            "/run-once",
            self.run_once,
            methods=["POST"],
            response_model=FarmerApprovalRunResponse,
        )
        self.router.add_api_route(
            "/status",
            self.status,
            methods=["GET"],
            response_model=FarmerApprovalStatusResponse,
        )

    async def run_once(self, request: FarmerApprovalRunRequest | None = None):
        request = request or FarmerApprovalRunRequest()
        return await self.worker.run_once_with_lock(
            limit=request.limit,
            dry_run=request.dry_run,
        )

    async def status(self):
        status = self.worker.service.get_status().model_dump()
        status.update(self.worker.get_status_values())
        status["latest_persisted_run"] = (
            await self.worker.service.get_latest_persisted_run()
        )
        return FarmerApprovalStatusResponse.model_validate(status)
