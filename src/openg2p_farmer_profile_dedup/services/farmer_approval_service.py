import logging

from ..config import get_settings
from ..engine import get_service_session, get_session
from ..repositories import DedupLogRepository, FarmerApprovalRepository
from ..schemas import (
    FarmerApprovalItemResult,
    FarmerApprovalRunResponse,
    FarmerApprovalStatusResponse,
)
from ..utils.farmer_approval_validator import FarmerApprovalValidator, to_text

_logger = logging.getLogger(__name__)


class FarmerApprovalService:
    """Approves successfully deduplicated farmers after DB validation."""

    def __init__(self):
        self.settings = get_settings()
        self.repository = FarmerApprovalRepository()
        self.log_repository = DedupLogRepository()
        self.validator = FarmerApprovalValidator()

    async def run_once(
        self,
        limit: int | None = None,
        dry_run: bool | None = None,
    ) -> FarmerApprovalRunResponse:
        effective_limit = limit or self.settings.approval_fetch_limit
        effective_dry_run = (
            self.settings.approval_dry_run if dry_run is None else dry_run
        )
        run_id = await self._create_log_run(
            dry_run=effective_dry_run,
            fetch_limit=effective_limit,
        )
        _logger.info(
            "Farmer approval run %s started. dry_run=%s limit=%s state=%s "
            "valid_id_types=%s response_status=%s unique_id_prefix=%s",
            run_id,
            effective_dry_run,
            effective_limit,
            self.settings.approval_state,
            self.settings.approval_valid_id_type_list,
            self.settings.approval_response_status,
            self.settings.partner_unique_id_prefix,
        )

        fetched = 0
        ready = 0
        approved = 0
        blocked = 0
        errors = 0
        skipped = 0
        status = "dry_run_complete" if effective_dry_run else "db_update_complete"

        try:
            async with get_session() as session:
                candidates = await self.repository.fetch_successfully_deduped_draft_farmers(
                    session,
                    valid_id_types=self.settings.approval_valid_id_type_list,
                    response_status=self.settings.approval_response_status,
                    state=self.settings.approval_state,
                    limit=effective_limit,
                    partner_unique_id_prefix=self.settings.partner_unique_id_prefix,
                )
                fetched = len(candidates)
                _logger.info(
                    "Farmer approval run %s fetched %s successfully deduped draft candidates.",
                    run_id,
                    fetched,
                )
                partner_ids = [candidate.partner_id for candidate in candidates]
                partners = await self.repository.load_partners(session, partner_ids)
                _logger.info(
                    "Farmer approval run %s loaded %s partner records for validation.",
                    run_id,
                    len(partners),
                )
                related = await self.repository.load_related(
                    session,
                    partner_ids,
                    self.settings.approval_check_global_land_duplicates,
                )
                candidates_by_partner = {
                    candidate.partner_id: candidate
                    for candidate in candidates
                }

                for partner in partners:
                    candidate = candidates_by_partner.get(int(partner["id"]))
                    item = self._build_item_result(partner, candidate)
                    try:
                        validation = self.validator.validate_partner(
                            partner,
                            related,
                            require_fan=self.settings.approval_require_fan,
                            require_valid_fan=self.settings.approval_require_valid_fan,
                            check_global_land_duplicates=(
                                self.settings.approval_check_global_land_duplicates
                            ),
                        )
                        item.ready = validation.approvable
                        item.critical = validation.critical
                        item.warnings = validation.warnings
                        item.details = validation.details

                        if validation.approvable:
                            ready += 1
                            item.new_farmer_id = self.compute_farmer_id(partner)
                            item.new_state = "approved"
                            _logger.info(
                                "Farmer approval candidate ready partner_id=%s name=%s "
                                "dedup_id_type=%s dedup_id_value=%s farmer_id=%s",
                                partner["id"],
                                partner.get("name") or "",
                                item.dedup_id_type,
                                item.dedup_id_value,
                                item.new_farmer_id,
                            )
                            if effective_dry_run:
                                item.approved = False
                            else:
                                updated = await self.repository.approve_farmer(
                                    session,
                                    partner_id=int(partner["id"]),
                                    farmer_id=item.new_farmer_id,
                                    write_uid=self.settings.approval_write_uid,
                                )
                                item.approved = bool(updated)
                                approved += updated
                                if updated:
                                    _logger.info(
                                        "Approved farmer partner_id=%s farmer_id=%s",
                                        partner["id"],
                                        item.new_farmer_id,
                                    )
                                if not updated:
                                    skipped += 1
                                    _logger.info(
                                        "Skipped approval update partner_id=%s. "
                                        "Record may no longer be in draft state.",
                                        partner["id"],
                                    )
                        else:
                            blocked += 1
                            _logger.info(
                                "Farmer approval candidate blocked partner_id=%s name=%s "
                                "dedup_id_type=%s dedup_id_value=%s critical=%s warnings=%s",
                                partner["id"],
                                partner.get("name") or "",
                                item.dedup_id_type,
                                item.dedup_id_value,
                                validation.critical,
                                validation.warnings,
                            )
                    except Exception as error:
                        errors += 1
                        item.error_message = str(error)
                        _logger.exception(
                            "Farmer approval candidate errored partner_id=%s name=%s",
                            partner.get("id"),
                            partner.get("name") or "",
                        )
                    await self._log_item(run_id, item)

                if effective_dry_run:
                    await session.rollback()
                else:
                    await session.commit()
        except Exception as error:
            status = "error"
            await self._finish_log_run(
                run_id=run_id,
                status=status,
                fetched=fetched,
                ready=ready,
                approved=approved,
                blocked=blocked,
                errors=errors,
                skipped=skipped,
                error_message=str(error),
            )
            raise

        await self._finish_log_run(
            run_id=run_id,
            status=status,
            fetched=fetched,
            ready=ready,
            approved=approved,
            blocked=blocked,
            errors=errors,
            skipped=skipped,
        )
        _logger.info(
            "Farmer approval run %s finished. status=%s fetched=%s ready=%s "
            "approved=%s blocked=%s errors=%s skipped=%s dry_run=%s",
            run_id,
            status,
            fetched,
            ready,
            approved,
            blocked,
            errors,
            skipped,
            effective_dry_run,
        )
        return FarmerApprovalRunResponse(
            run_id=run_id,
            fetched=fetched,
            ready=ready,
            approved=approved,
            blocked=blocked,
            errors=errors,
            skipped=skipped,
            dry_run=effective_dry_run,
            status=status,
        )

    @staticmethod
    def compute_farmer_id(partner: dict) -> str:
        return f"FR-{to_text(partner.get('unique_id'))}"

    def get_status(self) -> FarmerApprovalStatusResponse:
        return FarmerApprovalStatusResponse(
            background_enabled=self.settings.approval_background_enabled,
            lock_enabled=self.settings.approval_lock_enabled,
            dry_run=self.settings.approval_dry_run,
            fetch_limit=self.settings.approval_fetch_limit,
            valid_id_types=self.settings.approval_valid_id_type_list,
            partner_unique_id_prefix=self.settings.partner_unique_id_prefix,
            response_status=self.settings.approval_response_status,
        )

    async def get_latest_persisted_run(self) -> dict | None:
        async with get_service_session() as session:
            return await self.log_repository.get_latest_approval_run(session)

    def _build_item_result(
        self,
        partner: dict,
        candidate,
    ) -> FarmerApprovalItemResult:
        return FarmerApprovalItemResult(
            partner_id=int(partner["id"]),
            farmer_name=to_text(partner.get("name")),
            dedup_id_type=candidate.dedup_id_type if candidate else None,
            dedup_id_value=candidate.dedup_id_value if candidate else None,
            old_state=to_text(partner.get("state")),
            new_state=to_text(partner.get("state")),
            old_farmer_id=to_text(partner.get("farmer_id")),
            new_farmer_id=to_text(partner.get("farmer_id")),
        )

    async def _create_log_run(self, *, dry_run: bool, fetch_limit: int) -> int:
        async with get_service_session() as session:
            run_id = await self.log_repository.create_approval_run(
                session,
                dry_run=dry_run,
                fetch_limit=fetch_limit,
                valid_id_types=self.settings.approval_valid_id_type_list,
                response_status=self.settings.approval_response_status,
            )
            await session.commit()
            return run_id

    async def _finish_log_run(
        self,
        *,
        run_id: int,
        status: str,
        fetched: int,
        ready: int,
        approved: int,
        blocked: int,
        errors: int,
        skipped: int,
        error_message: str | None = None,
    ) -> None:
        async with get_service_session() as session:
            await self.log_repository.finish_approval_run(
                session,
                run_id,
                status=status,
                fetched=fetched,
                ready=ready,
                approved=approved,
                blocked=blocked,
                errors=errors,
                skipped=skipped,
                error_message=error_message,
            )
            await session.commit()

    async def _log_item(
        self,
        run_id: int,
        item: FarmerApprovalItemResult,
    ) -> None:
        async with get_service_session() as session:
            await self.log_repository.log_approval_item(
                session,
                run_id=run_id,
                item=item,
            )
            await session.commit()
