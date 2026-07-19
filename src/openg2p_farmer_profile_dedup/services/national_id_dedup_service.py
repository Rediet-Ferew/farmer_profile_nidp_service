import logging
from typing import Any

from ..config import get_settings
from ..engine import get_service_session, get_session
from ..repositories import DedupLogRepository, FarmerIdRepository, FarmerUpdateRepository
from ..schemas import DedupRunResponse, DedupStatusResponse
from ..utils.chunks import chunked
from .nidp_client import NidpClient
from .response_transformer import ResponseTransformer

_logger = logging.getLogger(__name__)


class NationalIdDedupService:
    """Orchestrates fetch, NIDP processing, transformation, and DB updates."""

    def __init__(self):
        self.settings = get_settings()
        self.farmer_id_repository = FarmerIdRepository()
        self.farmer_update_repository = FarmerUpdateRepository()
        self.log_repository = DedupLogRepository()
        self.nidp_client = NidpClient()
        self.response_transformer = ResponseTransformer()

    async def run_once(
        self,
        limit: int | None = None,
        dry_run: bool | None = None,
    ) -> DedupRunResponse:
        effective_dry_run = self.settings.dry_run if dry_run is None else dry_run
        effective_limit = limit or self.settings.fetch_limit
        run_id = await self._create_log_run(
            dry_run=effective_dry_run,
            fetch_limit=effective_limit,
        )

        async with get_session() as session:
            pending_ids = await self.farmer_id_repository.fetch_pending_ids(
                session=session,
                include_id_types=self.settings.include_id_type_list,
                limit=effective_limit,
                partner_unique_id_prefix=self.settings.partner_unique_id_prefix,
            )
        _logger.info(
            "Farmer dedup run %s fetched %s pending IDs. dry_run=%s limit=%s "
            "id_types=%s unique_id_prefix=%s",
            run_id,
            len(pending_ids),
            effective_dry_run,
            effective_limit,
            self.settings.include_id_type_list,
            self.settings.partner_unique_id_prefix,
        )

        sent_to_nidp = 0
        nidp_chunks = 0
        nidp_errors = 0
        processed = 0
        failed = 0
        transformed = 0
        updated = 0
        status = "dry_run_complete" if effective_dry_run else "db_update_complete"

        try:
            for chunk_index, pending_chunk in enumerate(
                chunked(pending_ids, self.settings.chunk_limit),
                start=1,
            ):
                lookup_values = [pending_id.value for pending_id in pending_chunk]
                pending_by_value = {pending_id.value: pending_id for pending_id in pending_chunk}
                nidp_chunks += 1
                sent_to_nidp += len(lookup_values)
                _logger.info(
                    "Farmer dedup run %s sending chunk %s with %s IDs to NIDP.",
                    run_id,
                    chunk_index,
                    len(lookup_values),
                )
                chunk_id = await self._create_log_chunk(
                    run_id=run_id,
                    chunk_index=chunk_index,
                    requested_count=len(lookup_values),
                )

                result = await self.nidp_client.call_get_data_by_id(lookup_values)
                if not result.ok:
                    nidp_errors += 1
                    await self._log_nidp_error_chunk(
                        run_id=run_id,
                        chunk_id=chunk_id,
                        pending_chunk=pending_chunk,
                        error_message=result.error,
                    )
                    continue

                id_type_by_value = {
                    pending_id.value: pending_id.id_type for pending_id in pending_chunk
                }
                chunk_updates = self.response_transformer.transform_get_data_by_id_response(
                    result.response,
                    id_type_by_value=id_type_by_value,
                )
                self._log_transformed_updates(
                    run_id=run_id,
                    chunk_index=chunk_index,
                    pending_by_value=pending_by_value,
                    chunk_updates=chunk_updates,
                )
                chunk_transformed = len(chunk_updates)
                chunk_processed = sum(
                    1 for update in chunk_updates if update.is_valid_complete_update
                )
                chunk_failed = sum(
                    1
                    for update in chunk_updates
                    if any(
                        id_update.status == "invalid"
                        for id_update in update.id_updates
                    )
                )
                chunk_updated = 0

                transformed += chunk_transformed
                processed += chunk_processed
                failed += chunk_failed

                if not effective_dry_run and chunk_updates:
                    async with get_session() as session:
                        chunk_updated = await self.farmer_update_repository.apply_updates(
                            session,
                            chunk_updates,
                        )
                        await session.commit()
                    updated += chunk_updated
                    _logger.info(
                        "Farmer dedup run %s chunk %s applied %s transformed updates.",
                        run_id,
                        chunk_index,
                        chunk_updated,
                    )

                await self._log_successful_chunk(
                    run_id=run_id,
                    chunk_id=chunk_id,
                    pending_by_value=pending_by_value,
                    chunk_updates=chunk_updates,
                    update_status="dry_run" if effective_dry_run else "updated",
                    transformed=chunk_transformed,
                    processed=chunk_processed,
                    failed=chunk_failed,
                    updated=chunk_updated,
                )
        except Exception as error:
            status = "error"
            await self._finish_log_run(
                run_id=run_id,
                status=status,
                fetched=len(pending_ids),
                sent_to_nidp=sent_to_nidp,
                nidp_chunks=nidp_chunks,
                nidp_errors=nidp_errors,
                processed=processed,
                failed=failed,
                transformed=transformed,
                updated=updated,
                skipped=0,
                error_message=str(error),
            )
            raise

        await self._finish_log_run(
            run_id=run_id,
            status=status,
            fetched=len(pending_ids),
            sent_to_nidp=sent_to_nidp,
            nidp_chunks=nidp_chunks,
            nidp_errors=nidp_errors,
            processed=processed,
            failed=failed,
            transformed=transformed,
            updated=updated,
            skipped=0,
        )

        return DedupRunResponse(
            run_id=run_id,
            fetched=len(pending_ids),
            sent_to_nidp=sent_to_nidp,
            nidp_chunks=nidp_chunks,
            nidp_errors=nidp_errors,
            processed=processed,
            failed=failed,
            transformed=transformed,
            updated=updated,
            dry_run=effective_dry_run,
            status=status,
        )

    def _log_transformed_updates(
        self,
        *,
        run_id: int,
        chunk_index: int,
        pending_by_value: dict,
        chunk_updates: list,
    ) -> None:
        if not chunk_updates:
            _logger.info(
                "Farmer dedup run %s chunk %s produced no transformed updates.",
                run_id,
                chunk_index,
            )
            return

        for update in chunk_updates:
            pending_id = pending_by_value.get(update.requested_id)
            partner_values = self._summarize_partner_values(update.partner_values)
            id_updates = [
                {
                    "id_type": id_update.id_type,
                    "value": id_update.value,
                    "status": id_update.status,
                    "description": id_update.description,
                    "fayda_processed": id_update.fayda_processed,
                    "fayda_response_status": id_update.fayda_response_status,
                }
                for id_update in update.id_updates
            ]
            _logger.info(
                "Transformed Fayda update run_id=%s chunk=%s partner_id=%s "
                "requested_id_type=%s requested_id=%s complete=%s "
                "partner_values=%s id_updates=%s",
                run_id,
                chunk_index,
                pending_id.partner_id if pending_id else None,
                update.requested_id_type,
                update.requested_id,
                update.is_valid_complete_update,
                partner_values,
                id_updates,
            )

    @staticmethod
    def _summarize_partner_values(partner_values: dict[str, Any]) -> dict[str, Any]:
        summarized = {}
        for key, value in partner_values.items():
            if key == "image_1920":
                summarized[key] = "<image data present>" if value else ""
            else:
                summarized[key] = value
        return summarized

    async def migrate_service_db(self) -> None:
        async with get_service_session() as session:
            await self.log_repository.migrate(session)
            await session.commit()

    async def get_latest_persisted_run(self) -> dict | None:
        async with get_service_session() as session:
            return await self.log_repository.get_latest_run(session)

    async def _create_log_run(self, *, dry_run: bool, fetch_limit: int) -> int:
        async with get_service_session() as session:
            run_id = await self.log_repository.create_run(
                session,
                dry_run=dry_run,
                fetch_limit=fetch_limit,
                chunk_limit=self.settings.chunk_limit,
                include_id_types=self.settings.include_id_type_list,
            )
            await session.commit()
            return run_id

    async def _finish_log_run(
        self,
        *,
        run_id: int,
        status: str,
        fetched: int,
        sent_to_nidp: int,
        nidp_chunks: int,
        nidp_errors: int,
        processed: int,
        failed: int,
        transformed: int,
        updated: int,
        skipped: int,
        error_message: str | None = None,
    ) -> None:
        async with get_service_session() as session:
            await self.log_repository.finish_run(
                session,
                run_id,
                status=status,
                counts={
                    "fetched": fetched,
                    "sent_to_nidp": sent_to_nidp,
                    "nidp_chunks": nidp_chunks,
                    "nidp_errors": nidp_errors,
                    "processed": processed,
                    "failed": failed,
                    "transformed": transformed,
                    "updated": updated,
                    "skipped": skipped,
                },
                error_message=error_message,
            )
            await session.commit()

    async def _create_log_chunk(
        self,
        *,
        run_id: int,
        chunk_index: int,
        requested_count: int,
    ) -> int:
        async with get_service_session() as session:
            chunk_id = await self.log_repository.create_chunk(
                session,
                run_id=run_id,
                chunk_index=chunk_index,
                requested_count=requested_count,
            )
            await session.commit()
            return chunk_id

    async def _log_nidp_error_chunk(
        self,
        *,
        run_id: int,
        chunk_id: int,
        pending_chunk,
        error_message: str | None,
    ) -> None:
        async with get_service_session() as session:
            await self.log_repository.log_pending_items(
                session,
                run_id=run_id,
                chunk_id=chunk_id,
                pending_ids=list(pending_chunk),
                status="nidp_error",
                error_message=error_message,
            )
            await self.log_repository.finish_chunk(
                session,
                chunk_id,
                status="nidp_error",
                error_message=error_message,
            )
            await session.commit()

    async def _log_successful_chunk(
        self,
        *,
        run_id: int,
        chunk_id: int,
        pending_by_value,
        chunk_updates,
        update_status: str,
        transformed: int,
        processed: int,
        failed: int,
        updated: int,
    ) -> None:
        async with get_service_session() as session:
            await self.log_repository.log_updates(
                session,
                run_id=run_id,
                chunk_id=chunk_id,
                pending_by_value=pending_by_value,
                updates=chunk_updates,
                update_status=update_status,
            )
            await self.log_repository.finish_chunk(
                session,
                chunk_id,
                status=update_status,
                transformed=transformed,
                processed=processed,
                failed=failed,
                updated=updated,
            )
            await session.commit()

    def get_status(self) -> DedupStatusResponse:
        return DedupStatusResponse(
            background_enabled=self.settings.background_enabled,
            lock_enabled=self.settings.lock_enabled,
            dry_run=self.settings.dry_run,
            chunk_limit=self.settings.chunk_limit,
            fetch_limit=self.settings.fetch_limit,
            include_id_types=self.settings.include_id_type_list,
            partner_unique_id_prefix=self.settings.partner_unique_id_prefix,
            processed_flag_value=self.settings.processed_flag_value,
            response_id_type=self.settings.response_id_type,
            response_id_field=self.settings.response_id_field,
            service_db_auto_migrate=self.settings.service_db_auto_migrate,
        )
