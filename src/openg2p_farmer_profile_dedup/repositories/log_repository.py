from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import FarmerApprovalItemResult, FarmerDedupUpdate, PendingId


class DedupLogRepository:
    """Persistent service-owned logs for dedup runs, chunks, and items."""

    async def migrate(self, session: AsyncSession) -> None:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS farmer_dedup_run (
                    id BIGSERIAL PRIMARY KEY,
                    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(64) NOT NULL DEFAULT 'running',
                    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
                    fetch_limit INTEGER,
                    chunk_limit INTEGER,
                    include_id_types TEXT,
                    fetched_count INTEGER NOT NULL DEFAULT 0,
                    sent_to_nidp_count INTEGER NOT NULL DEFAULT 0,
                    nidp_chunk_count INTEGER NOT NULL DEFAULT 0,
                    nidp_error_count INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    transformed_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS farmer_dedup_chunk (
                    id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL REFERENCES farmer_dedup_run(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMP WITH TIME ZONE,
                    requested_count INTEGER NOT NULL DEFAULT 0,
                    transformed_count INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR(64) NOT NULL DEFAULT 'running',
                    error_message TEXT
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS farmer_dedup_item (
                    id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL REFERENCES farmer_dedup_run(id) ON DELETE CASCADE,
                    chunk_id BIGINT REFERENCES farmer_dedup_chunk(id) ON DELETE CASCADE,
                    partner_id INTEGER,
                    reg_id INTEGER,
                    id_type VARCHAR(64),
                    id_value VARCHAR(255),
                    nidp_response_status VARCHAR(64),
                    update_status VARCHAR(64),
                    fayda_processed BOOLEAN,
                    fayda_response_status TEXT,
                    id_status VARCHAR(64),
                    id_description TEXT,
                    updated_partner_fields TEXT,
                    id_update_summary TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                ALTER TABLE farmer_dedup_item
                ADD COLUMN IF NOT EXISTS id_status VARCHAR(64),
                ADD COLUMN IF NOT EXISTS id_description TEXT,
                ADD COLUMN IF NOT EXISTS updated_partner_fields TEXT,
                ADD COLUMN IF NOT EXISTS id_update_summary TEXT
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS farmer_dedup_run_started_at_idx
                    ON farmer_dedup_run(started_at DESC)
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS farmer_dedup_item_id_value_idx
                    ON farmer_dedup_item(id_value)
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS farmer_dedup_item_partner_id_idx
                    ON farmer_dedup_item(partner_id)
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS farmer_approval_run (
                    id BIGSERIAL PRIMARY KEY,
                    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                    finished_at TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(64) NOT NULL DEFAULT 'running',
                    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
                    fetch_limit INTEGER,
                    valid_id_types TEXT,
                    response_status VARCHAR(64),
                    fetched_count INTEGER NOT NULL DEFAULT 0,
                    ready_count INTEGER NOT NULL DEFAULT 0,
                    approved_count INTEGER NOT NULL DEFAULT 0,
                    blocked_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS farmer_approval_item (
                    id BIGSERIAL PRIMARY KEY,
                    run_id BIGINT NOT NULL REFERENCES farmer_approval_run(id) ON DELETE CASCADE,
                    partner_id INTEGER,
                    farmer_name TEXT,
                    dedup_id_type VARCHAR(64),
                    dedup_id_value VARCHAR(255),
                    old_state VARCHAR(64),
                    new_state VARCHAR(64),
                    old_farmer_id VARCHAR(255),
                    new_farmer_id VARCHAR(255),
                    ready BOOLEAN NOT NULL DEFAULT FALSE,
                    approved BOOLEAN NOT NULL DEFAULT FALSE,
                    issue_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    issue_codes TEXT,
                    warnings TEXT,
                    issue_details TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS farmer_approval_run_started_at_idx
                    ON farmer_approval_run(started_at DESC)
                """
            )
        )
        await session.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS farmer_approval_item_partner_id_idx
                    ON farmer_approval_item(partner_id)
                """
            )
        )

    async def create_run(
        self,
        session: AsyncSession,
        *,
        dry_run: bool,
        fetch_limit: int,
        chunk_limit: int,
        include_id_types: list[str],
    ) -> int:
        result = await session.execute(
            text(
                """
                INSERT INTO farmer_dedup_run (
                    dry_run,
                    fetch_limit,
                    chunk_limit,
                    include_id_types
                )
                VALUES (
                    :dry_run,
                    :fetch_limit,
                    :chunk_limit,
                    :include_id_types
                )
                RETURNING id
                """
            ),
            {
                "dry_run": dry_run,
                "fetch_limit": fetch_limit,
                "chunk_limit": chunk_limit,
                "include_id_types": ", ".join(include_id_types),
            },
        )
        return int(result.scalar_one())

    async def finish_run(
        self,
        session: AsyncSession,
        run_id: int,
        *,
        status: str,
        counts: dict[str, int],
        error_message: str | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE farmer_dedup_run
                SET finished_at = NOW(),
                    status = :status,
                    fetched_count = :fetched,
                    sent_to_nidp_count = :sent_to_nidp,
                    nidp_chunk_count = :nidp_chunks,
                    nidp_error_count = :nidp_errors,
                    processed_count = :processed,
                    failed_count = :failed,
                    transformed_count = :transformed,
                    updated_count = :updated,
                    skipped_count = :skipped,
                    error_message = :error_message
                WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "error_message": error_message,
                **counts,
            },
        )

    async def create_chunk(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        chunk_index: int,
        requested_count: int,
    ) -> int:
        result = await session.execute(
            text(
                """
                INSERT INTO farmer_dedup_chunk (
                    run_id,
                    chunk_index,
                    requested_count
                )
                VALUES (
                    :run_id,
                    :chunk_index,
                    :requested_count
                )
                RETURNING id
                """
            ),
            {
                "run_id": run_id,
                "chunk_index": chunk_index,
                "requested_count": requested_count,
            },
        )
        return int(result.scalar_one())

    async def finish_chunk(
        self,
        session: AsyncSession,
        chunk_id: int,
        *,
        status: str,
        transformed: int = 0,
        processed: int = 0,
        failed: int = 0,
        updated: int = 0,
        error_message: str | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE farmer_dedup_chunk
                SET finished_at = NOW(),
                    status = :status,
                    transformed_count = :transformed,
                    processed_count = :processed,
                    failed_count = :failed,
                    updated_count = :updated,
                    error_message = :error_message
                WHERE id = :chunk_id
                """
            ),
            {
                "chunk_id": chunk_id,
                "status": status,
                "transformed": transformed,
                "processed": processed,
                "failed": failed,
                "updated": updated,
                "error_message": error_message,
            },
        )

    async def log_pending_items(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        chunk_id: int,
        pending_ids: list[PendingId],
        status: str,
        error_message: str | None = None,
    ) -> None:
        for pending_id in pending_ids:
            await self.create_item(
                session,
                run_id=run_id,
                chunk_id=chunk_id,
                partner_id=pending_id.partner_id,
                reg_id=pending_id.reg_id,
                id_type=pending_id.id_type,
                id_value=pending_id.value,
                update_status=status,
                error_message=error_message,
            )

    async def log_updates(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        chunk_id: int,
        pending_by_value: dict[str, PendingId],
        updates: list[FarmerDedupUpdate],
        update_status: str,
    ) -> None:
        for update in updates:
            pending = pending_by_value.get(update.requested_id)
            await self.create_item(
                session,
                run_id=run_id,
                chunk_id=chunk_id,
                partner_id=pending.partner_id if pending else None,
                reg_id=pending.reg_id if pending else None,
                id_type=update.requested_id_type,
                id_value=update.requested_id,
                nidp_response_status=update.response_status,
                update_status=update_status,
                fayda_processed=self._first_fayda_processed(update),
                fayda_response_status=update.response_status,
                id_status=self._first_id_status(update),
                id_description=self._first_id_description(update),
                updated_partner_fields=", ".join(sorted(update.partner_values)),
                id_update_summary=self._id_update_summary(update),
            )

    async def create_item(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        chunk_id: int | None = None,
        partner_id: int | None = None,
        reg_id: int | None = None,
        id_type: str | None = None,
        id_value: str | None = None,
        nidp_response_status: str | None = None,
        update_status: str,
        fayda_processed: bool | None = None,
        fayda_response_status: str | None = None,
        id_status: str | None = None,
        id_description: str | None = None,
        updated_partner_fields: str | None = None,
        id_update_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO farmer_dedup_item (
                    run_id,
                    chunk_id,
                    partner_id,
                    reg_id,
                    id_type,
                    id_value,
                    nidp_response_status,
                    update_status,
                    fayda_processed,
                    fayda_response_status,
                    id_status,
                    id_description,
                    updated_partner_fields,
                    id_update_summary,
                    error_message
                )
                VALUES (
                    :run_id,
                    :chunk_id,
                    :partner_id,
                    :reg_id,
                    :id_type,
                    :id_value,
                    :nidp_response_status,
                    :update_status,
                    :fayda_processed,
                    :fayda_response_status,
                    :id_status,
                    :id_description,
                    :updated_partner_fields,
                    :id_update_summary,
                    :error_message
                )
                """
            ),
            {
                "run_id": run_id,
                "chunk_id": chunk_id,
                "partner_id": partner_id,
                "reg_id": reg_id,
                "id_type": id_type,
                "id_value": id_value,
                "nidp_response_status": nidp_response_status,
                "update_status": update_status,
                "fayda_processed": fayda_processed,
                "fayda_response_status": fayda_response_status,
                "id_status": id_status,
                "id_description": id_description,
                "updated_partner_fields": updated_partner_fields,
                "id_update_summary": id_update_summary,
                "error_message": error_message,
            },
        )

    async def fetch_successfully_processed_candidates(
        self,
        session: AsyncSession,
        *,
        valid_id_types: list[str],
        response_status: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not valid_id_types:
            return []
        query = (
            text(
                """
                SELECT DISTINCT ON (partner_id)
                    partner_id,
                    id_type AS dedup_id_type,
                    id_value AS dedup_id_value
                FROM farmer_dedup_item
                WHERE partner_id IS NOT NULL
                  AND id_type IN :valid_id_types
                  AND id_value IS NOT NULL
                  AND BTRIM(id_value) <> ''
                  AND fayda_processed IS TRUE
                  AND UPPER(COALESCE(fayda_response_status, '')) = UPPER(:response_status)
                ORDER BY partner_id ASC, created_at DESC, id DESC
                LIMIT :limit
                """
            )
            .bindparams(bindparam("valid_id_types", expanding=True))
            .bindparams(bindparam("limit"))
        )
        result = await session.execute(
            query,
            {
                "valid_id_types": valid_id_types,
                "response_status": response_status,
                "limit": limit,
            },
        )
        return [dict(row) for row in result.mappings().all()]

    async def get_latest_run(self, session: AsyncSession) -> dict[str, Any] | None:
        result = await session.execute(
            text(
                """
                SELECT *
                FROM farmer_dedup_run
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            )
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def create_approval_run(
        self,
        session: AsyncSession,
        *,
        dry_run: bool,
        fetch_limit: int,
        valid_id_types: list[str],
        response_status: str,
    ) -> int:
        result = await session.execute(
            text(
                """
                INSERT INTO farmer_approval_run (
                    dry_run,
                    fetch_limit,
                    valid_id_types,
                    response_status
                )
                VALUES (
                    :dry_run,
                    :fetch_limit,
                    :valid_id_types,
                    :response_status
                )
                RETURNING id
                """
            ),
            {
                "dry_run": dry_run,
                "fetch_limit": fetch_limit,
                "valid_id_types": ", ".join(valid_id_types),
                "response_status": response_status,
            },
        )
        return int(result.scalar_one())

    async def finish_approval_run(
        self,
        session: AsyncSession,
        run_id: int,
        *,
        status: str,
        fetched: int,
        ready: int,
        approved: int,
        blocked: int,
        errors: int,
        skipped: int,
        error_message: str | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE farmer_approval_run
                SET finished_at = NOW(),
                    status = :status,
                    fetched_count = :fetched,
                    ready_count = :ready,
                    approved_count = :approved,
                    blocked_count = :blocked,
                    error_count = :errors,
                    skipped_count = :skipped,
                    error_message = :error_message
                WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "status": status,
                "fetched": fetched,
                "ready": ready,
                "approved": approved,
                "blocked": blocked,
                "errors": errors,
                "skipped": skipped,
                "error_message": error_message,
            },
        )

    async def log_approval_item(
        self,
        session: AsyncSession,
        *,
        run_id: int,
        item: FarmerApprovalItemResult,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO farmer_approval_item (
                    run_id,
                    partner_id,
                    farmer_name,
                    dedup_id_type,
                    dedup_id_value,
                    old_state,
                    new_state,
                    old_farmer_id,
                    new_farmer_id,
                    ready,
                    approved,
                    issue_count,
                    warning_count,
                    issue_codes,
                    warnings,
                    issue_details,
                    error_message
                )
                VALUES (
                    :run_id,
                    :partner_id,
                    :farmer_name,
                    :dedup_id_type,
                    :dedup_id_value,
                    :old_state,
                    :new_state,
                    :old_farmer_id,
                    :new_farmer_id,
                    :ready,
                    :approved,
                    :issue_count,
                    :warning_count,
                    :issue_codes,
                    :warnings,
                    :issue_details,
                    :error_message
                )
                """
            ),
            {
                "run_id": run_id,
                "partner_id": item.partner_id,
                "farmer_name": item.farmer_name,
                "dedup_id_type": item.dedup_id_type,
                "dedup_id_value": item.dedup_id_value,
                "old_state": item.old_state,
                "new_state": item.new_state,
                "old_farmer_id": item.old_farmer_id,
                "new_farmer_id": item.new_farmer_id,
                "ready": item.ready,
                "approved": item.approved,
                "issue_count": len(item.critical),
                "warning_count": len(item.warnings),
                "issue_codes": "; ".join(item.critical),
                "warnings": "; ".join(item.warnings),
                "issue_details": "; ".join(
                    f"{key}={value}"
                    for key, value in sorted(item.details.items())
                    if value
                ),
                "error_message": item.error_message,
            },
        )

    async def get_latest_approval_run(
        self,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        result = await session.execute(
            text(
                """
                SELECT *
                FROM farmer_approval_run
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            )
        )
        row = result.mappings().first()
        return dict(row) if row else None

    @staticmethod
    def _first_fayda_processed(update: FarmerDedupUpdate) -> bool | None:
        for id_update in update.id_updates:
            if id_update.fayda_processed is not None:
                return id_update.fayda_processed
        return None

    @staticmethod
    def _first_id_status(update: FarmerDedupUpdate) -> str | None:
        for id_update in update.id_updates:
            if id_update.status:
                return id_update.status
        return None

    @staticmethod
    def _first_id_description(update: FarmerDedupUpdate) -> str | None:
        for id_update in update.id_updates:
            if id_update.description:
                return id_update.description
        return None

    @staticmethod
    def _id_update_summary(update: FarmerDedupUpdate) -> str:
        return "; ".join(
            f"{id_update.id_type}:{id_update.value}:{id_update.status}"
            for id_update in update.id_updates
        )
