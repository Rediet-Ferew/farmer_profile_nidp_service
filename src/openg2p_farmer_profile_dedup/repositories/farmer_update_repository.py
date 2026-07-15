from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import FarmerDedupUpdate, IdUpdate


class FarmerUpdateRepository:
    """Direct database writes for farmer profile and registration ID updates."""

    PARTNER_UPDATE_COLUMNS = {
        "name",
        "given_name",
        "family_name",
        "addl_name",
        "gf_name_eng",
        "first_name_amh",
        "family_name_amh",
        "gf_name_amh",
        "gender",
        "birthdate",
        "birth_place",
        "image_1920",
        "registration_date",
    }

    async def apply_updates(
        self,
        session: AsyncSession,
        updates: list[FarmerDedupUpdate],
    ) -> int:
        updated = 0
        for update in updates:
            partner_id = await self.find_partner_id_for_requested_id(session, update)
            if not partner_id:
                continue

            if update.is_valid_complete_update and update.partner_values:
                await self.update_partner_fields(
                    session,
                    partner_id,
                    update.partner_values,
                )

            for id_update in update.id_updates:
                await self.upsert_reg_id(session, partner_id, id_update)

            updated += 1

        return updated

    async def find_partner_id_for_requested_id(
        self,
        session: AsyncSession,
        update: FarmerDedupUpdate,
    ) -> int | None:
        result = await session.execute(
            text(
                """
                SELECT rp.id
                FROM res_partner rp
                JOIN g2p_reg_id gid
                    ON gid.partner_id = rp.id
                JOIN g2p_id_type t
                    ON t.id = gid.id_type
                WHERE rp.is_farmer = 'yes'
                  AND rp.is_registrant = TRUE
                  AND rp.is_group = FALSE
                  AND rp.active = TRUE
                  AND t.name = :id_type
                  AND gid.value = :value
                ORDER BY rp.id ASC
                LIMIT 1
                """
            ),
            {
                "id_type": update.requested_id_type,
                "value": update.requested_id,
            },
        )
        row = result.mappings().first()
        return row["id"] if row else None

    async def update_partner_fields(
        self,
        session: AsyncSession,
        partner_id: int,
        partner_values: dict[str, Any],
    ) -> None:
        values = {
            key: self.prepare_partner_value(key, value)
            for key, value in partner_values.items()
            if key in self.PARTNER_UPDATE_COLUMNS and value not in (None, "")
        }
        if not values:
            return

        set_clause = ", ".join(f"{column} = :{column}" for column in values)
        values["partner_id"] = partner_id
        await session.execute(
            text(
                f"""
                UPDATE res_partner
                SET {set_clause},
                    write_date = NOW()
                WHERE id = :partner_id
                """
            ),
            values,
        )

    @staticmethod
    def prepare_partner_value(key: str, value: Any) -> Any:
        if key == "image_1920" and isinstance(value, str):
            return value.encode()
        return value

    async def upsert_reg_id(
        self,
        session: AsyncSession,
        partner_id: int,
        id_update: IdUpdate,
    ) -> None:
        id_type_id = await self.get_id_type_id(session, id_update.id_type)
        if not id_type_id:
            return

        existing_id = await self.find_existing_reg_id(
            session=session,
            partner_id=partner_id,
            id_type_id=id_type_id,
            value=id_update.value,
        )

        values = self.build_reg_id_values(
            partner_id=partner_id,
            id_type_id=id_type_id,
            id_update=id_update,
        )

        if existing_id:
            values["id"] = existing_id
            await self.update_reg_id(session, values)
        else:
            await self.insert_reg_id(session, values)

    async def get_id_type_id(self, session: AsyncSession, id_type: str) -> int | None:
        result = await session.execute(
            text(
                """
                SELECT id
                FROM g2p_id_type
                WHERE name = :name
                LIMIT 1
                """
            ),
            {"name": id_type},
        )
        row = result.mappings().first()
        return row["id"] if row else None

    async def find_existing_reg_id(
        self,
        session: AsyncSession,
        partner_id: int,
        id_type_id: int,
        value: str,
    ) -> int | None:
        exact = await session.execute(
            text(
                """
                SELECT id
                FROM g2p_reg_id
                WHERE partner_id = :partner_id
                  AND id_type = :id_type_id
                  AND value = :value
                ORDER BY id ASC
                LIMIT 1
                """
            ),
            {
                "partner_id": partner_id,
                "id_type_id": id_type_id,
                "value": value,
            },
        )
        exact_row = exact.mappings().first()
        if exact_row:
            return exact_row["id"]

        fallback = await session.execute(
            text(
                """
                SELECT id
                FROM g2p_reg_id
                WHERE partner_id = :partner_id
                  AND id_type = :id_type_id
                ORDER BY id ASC
                LIMIT 1
                """
            ),
            {
                "partner_id": partner_id,
                "id_type_id": id_type_id,
            },
        )
        fallback_row = fallback.mappings().first()
        return fallback_row["id"] if fallback_row else None

    def build_reg_id_values(
        self,
        partner_id: int,
        id_type_id: int,
        id_update: IdUpdate,
    ) -> dict[str, Any]:
        values = {
            "partner_id": partner_id,
            "id_type_id": id_type_id,
            "value": id_update.value,
            "status": id_update.status,
            "description": id_update.description,
            "expiry_date": id_update.expiry_date,
            "fayda_response_status": id_update.fayda_response_status,
        }
        if id_update.fayda_processed is not None:
            values["fayda_processed"] = (
                "true" if id_update.fayda_processed else "false"
            )
        return values

    async def update_reg_id(self, session: AsyncSession, values: dict[str, Any]) -> None:
        set_fields = [
            "value = :value",
            "status = :status",
            "description = :description",
            "expiry_date = :expiry_date",
            "fayda_response_status = :fayda_response_status",
            "write_date = NOW()",
        ]
        if "fayda_processed" in values:
            set_fields.append("fayda_processed = :fayda_processed")

        await session.execute(
            text(
                f"""
                UPDATE g2p_reg_id
                SET {", ".join(set_fields)}
                WHERE id = :id
                """
            ),
            values,
        )

    async def insert_reg_id(self, session: AsyncSession, values: dict[str, Any]) -> None:
        columns = [
            "partner_id",
            "id_type",
            "value",
            "status",
            "description",
            "expiry_date",
            "fayda_response_status",
            "create_date",
            "write_date",
        ]
        params = [
            ":partner_id",
            ":id_type_id",
            ":value",
            ":status",
            ":description",
            ":expiry_date",
            ":fayda_response_status",
            "NOW()",
            "NOW()",
        ]
        if "fayda_processed" in values:
            columns.append("fayda_processed")
            params.append(":fayda_processed")

        await session.execute(
            text(
                f"""
                INSERT INTO g2p_reg_id ({", ".join(columns)})
                VALUES ({", ".join(params)})
                """
            ),
            values,
        )
