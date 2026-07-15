from ..config import get_settings
from ..engine import get_session
from ..repositories import FarmerIdRepository, FarmerUpdateRepository
from ..schemas import DedupRunResponse, DedupStatusResponse
from ..utils.chunks import chunked
from .nidp_client import NidpClient
from .response_transformer import ResponseTransformer


class NationalIdDedupService:
    """Orchestrates fetch, NIDP processing, transformation, and DB updates."""

    def __init__(self):
        self.settings = get_settings()
        self.farmer_id_repository = FarmerIdRepository()
        self.farmer_update_repository = FarmerUpdateRepository()
        self.nidp_client = NidpClient()
        self.response_transformer = ResponseTransformer()

    async def run_once(
        self,
        limit: int | None = None,
        dry_run: bool | None = None,
    ) -> DedupRunResponse:
        effective_dry_run = self.settings.dry_run if dry_run is None else dry_run
        effective_limit = limit or self.settings.fetch_limit

        async with get_session() as session:
            pending_ids = await self.farmer_id_repository.fetch_pending_ids(
                session=session,
                include_id_types=self.settings.include_id_type_list,
                limit=effective_limit,
            )

        sent_to_nidp = 0
        nidp_chunks = 0
        nidp_errors = 0
        processed = 0
        failed = 0
        transformed = 0
        updated = 0

        for pending_chunk in chunked(pending_ids, self.settings.chunk_limit):
            lookup_values = [pending_id.value for pending_id in pending_chunk]
            nidp_chunks += 1
            sent_to_nidp += len(lookup_values)

            result = await self.nidp_client.call_get_data_by_id(lookup_values)
            if not result.ok:
                nidp_errors += 1
                continue

            id_type_by_value = {
                pending_id.value: pending_id.id_type for pending_id in pending_chunk
            }
            chunk_updates = self.response_transformer.transform_get_data_by_id_response(
                result.response,
                id_type_by_value=id_type_by_value,
            )
            transformed += len(chunk_updates)
            processed += sum(
                1 for update in chunk_updates if update.is_valid_complete_update
            )
            failed += sum(
                1
                for update in chunk_updates
                if any(
                    id_update.status == "invalid"
                    for id_update in update.id_updates
                )
            )

            if effective_dry_run or not chunk_updates:
                continue

            async with get_session() as session:
                updated += await self.farmer_update_repository.apply_updates(
                    session,
                    chunk_updates,
                )
                await session.commit()

        return DedupRunResponse(
            fetched=len(pending_ids),
            sent_to_nidp=sent_to_nidp,
            nidp_chunks=nidp_chunks,
            nidp_errors=nidp_errors,
            processed=processed,
            failed=failed,
            transformed=transformed,
            updated=updated,
            dry_run=effective_dry_run,
            status="dry_run_complete" if effective_dry_run else "db_update_complete",
        )

    def get_status(self) -> DedupStatusResponse:
        return DedupStatusResponse(
            background_enabled=self.settings.background_enabled,
            lock_enabled=self.settings.lock_enabled,
            dry_run=self.settings.dry_run,
            chunk_limit=self.settings.chunk_limit,
            fetch_limit=self.settings.fetch_limit,
            include_id_types=self.settings.include_id_type_list,
            processed_flag_value=self.settings.processed_flag_value,
            response_id_type=self.settings.response_id_type,
            response_id_field=self.settings.response_id_field,
        )
