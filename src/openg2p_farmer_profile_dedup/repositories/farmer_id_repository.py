from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import PendingId


class FarmerIdRepository:
    """Direct database access for farmer ID fetch operations."""

    async def fetch_pending_ids(
        self,
        session: AsyncSession,
        include_id_types: list[str],
        limit: int,
    ) -> list[PendingId]:
        if not include_id_types:
            return []

        query = (
            text(
                """
                SELECT
                    rp.id AS partner_id,
                    gid.id AS reg_id,
                    t.name AS id_type,
                    gid.value AS value
                FROM g2p_reg_id gid
                JOIN g2p_id_type t
                    ON t.id = gid.id_type
                JOIN res_partner rp
                    ON rp.id = gid.partner_id
                WHERE rp.is_farmer = 'yes'
                  AND rp.is_registrant = TRUE
                  AND rp.is_group = FALSE
                  AND rp.active = TRUE
                  AND t.name IN :include_id_types
                  AND gid.value IS NOT NULL
                  AND BTRIM(gid.value) <> ''
                  AND (
                      gid.fayda_processed = 'false'
                      OR gid.fayda_processed IS NULL
                      OR gid.fayda_processed = ''
                  )
                ORDER BY
                    rp.id ASC,
                    t.name ASC,
                    gid.id ASC
                LIMIT :limit
                """
            )
            .bindparams(bindparam("include_id_types", expanding=True))
            .bindparams(bindparam("limit"))
        )

        result = await session.execute(
            query,
            {
                "include_id_types": include_id_types,
                "limit": limit,
            },
        )
        return [PendingId.model_validate(row) for row in result.mappings().all()]
