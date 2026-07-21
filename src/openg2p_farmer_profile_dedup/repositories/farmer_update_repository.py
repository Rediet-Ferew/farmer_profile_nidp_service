import asyncio
import base64
import binascii
import hashlib
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..schemas import FarmerDedupUpdate, IdUpdate

_logger = logging.getLogger(__name__)

IMAGE_COLUMN = "image_1920"


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
        IMAGE_COLUMN,
        "registration_date",
    }

    def __init__(self):
        self._partner_table_columns: set[str] | None = None
        self.settings = get_settings()

    async def apply_updates(
        self,
        session: AsyncSession,
        updates: list[FarmerDedupUpdate],
    ) -> int:
        updated = 0
        for update in updates:
            partner_id = await self.find_partner_id_for_requested_id(session, update)
            if not partner_id:
                _logger.warning(
                    "Skipping Fayda update because requested ID was not found. "
                    "requested_id_type=%s requested_id=%s",
                    update.requested_id_type,
                    update.requested_id,
                )
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
            _logger.info(
                "Applied Fayda update partner_id=%s requested_id_type=%s requested_id=%s "
                "complete=%s id_update_count=%s",
                partner_id,
                update.requested_id_type,
                update.requested_id,
                update.is_valid_complete_update,
                len(update.id_updates),
            )

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
        image_value = partner_values.get(IMAGE_COLUMN)
        if image_value not in (None, ""):
            await self.write_image_attachment(session, partner_id, image_value)

        partner_table_columns = await self.get_partner_table_columns(session)
        skipped_columns = sorted(
            key
            for key, value in partner_values.items()
            if key in self.PARTNER_UPDATE_COLUMNS
            and key not in partner_table_columns
            and key != IMAGE_COLUMN
            and value not in (None, "")
        )
        if skipped_columns:
            _logger.info(
                "Skipping partner fields that are not physical res_partner columns "
                "partner_id=%s fields=%s",
                partner_id,
                skipped_columns,
            )
        values = {
            key: self.prepare_partner_value(key, value)
            for key, value in partner_values.items()
            if key in self.PARTNER_UPDATE_COLUMNS
            and key in partner_table_columns
            and value not in (None, "")
        }
        if not values:
            return

        _logger.info(
            "Updating partner fields from Fayda partner_id=%s fields=%s",
            partner_id,
            sorted(values),
        )
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

    async def get_partner_table_columns(self, session: AsyncSession) -> set[str]:
        if self._partner_table_columns is not None:
            return self._partner_table_columns

        result = await session.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'res_partner'
                """
            )
        )
        self._partner_table_columns = {
            row["column_name"] for row in result.mappings().all()
        }
        return self._partner_table_columns

    @staticmethod
    def prepare_partner_value(key: str, value: Any) -> Any:
        if key in {"birthdate", "registration_date"} and isinstance(value, str):
            return date.fromisoformat(value)
        return value

    async def write_image_attachment(
        self,
        session: AsyncSession,
        partner_id: int,
        raw_value: Any,
    ) -> None:
        """Persist image_1920 the way Odoo's ORM does: as a filestore blob plus an
        ir_attachment row, since it is an attachment-backed field, not a physical
        res_partner column.
        """
        if isinstance(raw_value, bytes):
            encoded = raw_value
        elif isinstance(raw_value, str):
            encoded = raw_value.encode()
        else:
            return

        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            _logger.warning(
                "Skipping %s attachment write for partner_id=%s: "
                "value is not valid base64 image data.",
                IMAGE_COLUMN,
                partner_id,
            )
            return
        if not decoded:
            return

        filestore_dir = self.settings.odoo_filestore_dir
        if not filestore_dir:
            _logger.warning(
                "Skipping %s attachment write for partner_id=%s: "
                "FARMER_DEDUP_ODOO_FILESTORE_DIR is not configured.",
                IMAGE_COLUMN,
                partner_id,
            )
            return

        checksum = hashlib.sha1(decoded).hexdigest()
        store_fname = f"{checksum[:2]}/{checksum}"
        await asyncio.to_thread(
            self._write_filestore_blob, filestore_dir, store_fname, decoded
        )
        mimetype = self._guess_image_mimetype(decoded)

        await self._upsert_image_attachment(
            session,
            partner_id=partner_id,
            store_fname=store_fname,
            checksum=checksum,
            mimetype=mimetype,
            file_size=len(decoded),
        )
        _logger.info(
            "Wrote %s attachment partner_id=%s checksum=%s bytes=%s",
            IMAGE_COLUMN,
            partner_id,
            checksum,
            len(decoded),
        )

    @staticmethod
    def _write_filestore_blob(filestore_dir: str, store_fname: str, data: bytes) -> None:
        path = Path(filestore_dir) / store_fname
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_bytes(data)
        tmp_path.replace(path)

    @staticmethod
    def _guess_image_mimetype(data: bytes) -> str:
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return "image/webp"
        if data.lstrip().startswith((b"<svg", b"<?xml")):
            return "image/svg+xml"
        return "application/octet-stream"

    async def _upsert_image_attachment(
        self,
        session: AsyncSession,
        *,
        partner_id: int,
        store_fname: str,
        checksum: str,
        mimetype: str,
        file_size: int,
    ) -> None:
        result = await session.execute(
            text(
                """
                SELECT id
                FROM ir_attachment
                WHERE res_model = 'res.partner'
                  AND res_field = :res_field
                  AND res_id = :partner_id
                LIMIT 1
                """
            ),
            {"res_field": IMAGE_COLUMN, "partner_id": partner_id},
        )
        existing = result.mappings().first()

        if existing:
            await session.execute(
                text(
                    """
                    UPDATE ir_attachment
                    SET store_fname = :store_fname,
                        checksum = :checksum,
                        mimetype = :mimetype,
                        file_size = :file_size,
                        db_datas = NULL,
                        write_date = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": existing["id"],
                    "store_fname": store_fname,
                    "checksum": checksum,
                    "mimetype": mimetype,
                    "file_size": file_size,
                },
            )
        else:
            await session.execute(
                text(
                    """
                    INSERT INTO ir_attachment (
                        name, res_model, res_field, res_id, type,
                        store_fname, checksum, mimetype, file_size,
                        public, create_date, write_date
                    ) VALUES (
                        :res_field, 'res.partner', :res_field, :partner_id, 'binary',
                        :store_fname, :checksum, :mimetype, :file_size,
                        FALSE, NOW(), NOW()
                    )
                    """
                ),
                {
                    "res_field": IMAGE_COLUMN,
                    "partner_id": partner_id,
                    "store_fname": store_fname,
                    "checksum": checksum,
                    "mimetype": mimetype,
                    "file_size": file_size,
                },
            )

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
            _logger.info(
                "Updated registrant ID from Fayda partner_id=%s id_type=%s value=%s "
                "status=%s",
                partner_id,
                id_update.id_type,
                id_update.value,
                id_update.status,
            )
        else:
            await self.insert_reg_id(session, values)
            _logger.info(
                "Inserted registrant ID from Fayda partner_id=%s id_type=%s value=%s "
                "status=%s",
                partner_id,
                id_update.id_type,
                id_update.value,
                id_update.status,
            )

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
            "expiry_date": self.prepare_date_value(id_update.expiry_date),
        }
        return values

    @staticmethod
    def prepare_date_value(value: Any) -> Any:
        if isinstance(value, str) and value:
            return date.fromisoformat(value)
        return value

    async def update_reg_id(self, session: AsyncSession, values: dict[str, Any]) -> None:
        set_fields = [
            "value = :value",
            "status = :status",
            "description = :description",
            "expiry_date = :expiry_date",
            "write_date = NOW()",
        ]

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
            "NOW()",
            "NOW()",
        ]

        await session.execute(
            text(
                f"""
                INSERT INTO g2p_reg_id ({", ".join(columns)})
                VALUES ({", ".join(params)})
                """
            ),
            values,
        )
