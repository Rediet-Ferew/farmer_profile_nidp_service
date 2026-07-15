import asyncio
import logging
from datetime import UTC, datetime

from ..config import get_settings
from ..engine import get_session
from ..repositories import LockRepository
from ..schemas import DedupRunResponse
from .national_id_dedup_service import NationalIdDedupService

_logger = logging.getLogger(__name__)


class BackgroundWorker:
    """Automatic background loop for farmer national ID deduplication."""

    def __init__(self):
        self.settings = get_settings()
        self.service = NationalIdDedupService()
        self.lock_repository = LockRepository()
        self.task: asyncio.Task | None = None
        self.is_running = False
        self.last_run_started_at: str | None = None
        self.last_run_finished_at: str | None = None
        self.last_run_status: str = "not_started"
        self.last_run_result: DedupRunResponse | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if not self.settings.background_enabled:
            _logger.info("Farmer dedup background worker is disabled.")
            return

        if self.task and not self.task.done():
            return

        self.task = asyncio.create_task(self.run_loop())
        _logger.info("Farmer dedup background worker started.")

    async def stop(self) -> None:
        if not self.task:
            return

        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            _logger.info("Farmer dedup background worker stopped.")

    async def run_loop(self) -> None:
        await asyncio.sleep(self.settings.initial_delay_seconds)
        while True:
            try:
                await self.run_once_with_lock()
            except Exception:
                _logger.exception("Farmer dedup background cycle failed.")
            await asyncio.sleep(self.settings.interval_seconds)

    async def run_once_with_lock(
        self,
        limit: int | None = None,
        dry_run: bool | None = None,
    ) -> DedupRunResponse:
        if self.is_running:
            return DedupRunResponse(
                dry_run=self.settings.dry_run if dry_run is None else dry_run,
                skipped=1,
                status="already_running",
            )

        if not self.settings.lock_enabled:
            return await self._run_once(limit=limit, dry_run=dry_run)

        async with get_session() as session:
            acquired = await self.lock_repository.acquire(session, self.settings.lock_id)
            if not acquired:
                result = DedupRunResponse(
                    dry_run=self.settings.dry_run if dry_run is None else dry_run,
                    skipped=1,
                    status="lock_not_acquired",
                )
                self.last_run_result = result
                self.last_run_status = result.status
                return result

            try:
                return await self._run_once(limit=limit, dry_run=dry_run)
            finally:
                await self.lock_repository.release(session, self.settings.lock_id)

    async def _run_once(
        self,
        limit: int | None = None,
        dry_run: bool | None = None,
    ) -> DedupRunResponse:
        self.is_running = True
        self.last_run_started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self.last_run_finished_at = None
        self.last_run_status = "running"
        self.last_error = None

        try:
            result = await self.service.run_once(limit=limit, dry_run=dry_run)
            self.last_run_result = result
            self.last_run_status = result.status
            return result
        except Exception as error:
            self.last_error = str(error)
            self.last_run_status = "error"
            _logger.exception("Farmer dedup run failed.")
            raise
        finally:
            self.is_running = False
            self.last_run_finished_at = datetime.now(UTC).isoformat().replace(
                "+00:00",
                "Z",
            )

    def get_status_values(self) -> dict:
        return {
            "worker_running": self.is_running,
            "last_run_started_at": self.last_run_started_at,
            "last_run_finished_at": self.last_run_finished_at,
            "last_run_status": self.last_run_status,
            "last_run_result": self.last_run_result,
            "last_error": self.last_error,
        }


_background_worker: BackgroundWorker | None = None


def get_background_worker() -> BackgroundWorker:
    global _background_worker
    if _background_worker is None:
        _background_worker = BackgroundWorker()
    return _background_worker
