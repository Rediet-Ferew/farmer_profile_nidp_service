import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from ..config import get_settings
from ..schemas import FarmerDedupUpdate, IdUpdate

_logger = logging.getLogger(__name__)


class ResponseTransformer:
    """Transforms NIDP getDataById responses into farmer/profile DB updates."""

    def __init__(self):
        self.settings = get_settings()

    def transform_get_data_by_id_response(
        self,
        response: dict[str, Any] | None,
        id_type_by_value: dict[str, str],
    ) -> list[FarmerDedupUpdate]:
        transformed_updates: list[FarmerDedupUpdate] = []

        if not response:
            return transformed_updates

        if response.get("error"):
            _logger.error("getDataById returned top-level error: %s", response["error"])
            return transformed_updates

        for entry in response.get("response", []) or []:
            requested_id = entry.get("id")
            if not requested_id:
                _logger.info("Skipping NIDP response entry without id: %s", entry)
                continue

            requested_id_type = id_type_by_value.get(str(requested_id))
            if not requested_id_type:
                _logger.info("Skipping NIDP response for unknown id: %s", requested_id)
                continue

            status = entry.get("status")
            data = entry.get("data")

            if status == "PROCESSED" and data:
                transformed_updates.append(
                    self.build_processed_update(
                        data=data,
                        requested_id=str(requested_id),
                        requested_id_type=requested_id_type,
                        message=entry.get("message"),
                        response_status=status,
                    )
                )
            elif status in ["FAILED", "REJECTED", None] or (
                status == "PROCESSED" and not data
            ):
                transformed_updates.append(
                    self.build_invalid_update(
                        requested_id=str(requested_id),
                        requested_id_type=requested_id_type,
                        message=entry.get("message"),
                        response_status=status,
                    )
                )
            else:
                _logger.info(
                    "Skipping NIDP response with status %s for id %s",
                    status,
                    requested_id,
                )

        return transformed_updates

    def build_processed_update(
        self,
        data: dict[str, Any],
        requested_id: str,
        requested_id_type: str,
        message: str | None,
        response_status: str | None,
    ) -> FarmerDedupUpdate:
        response_id_type = self.settings.response_id_type
        response_id_value = self.get_response_id_value(data)
        response_id_status, response_id_description = self.get_response_id_status(
            response_id_value,
            message or "No description provided",
            response_id_type,
        )

        partner_values = self.map_partner_values(data)
        id_updates = [
            IdUpdate(
                id_type=response_id_type,
                value=response_id_value,
                expiry_date=self.default_expiry_date(),
                status=response_id_status,
                description=response_id_description,
                fayda_response_status=response_status,
                fayda_processed=False if response_id_status == "invalid" else None,
            )
        ]

        is_same_requested_id = (
            requested_id_type == response_id_type
            and str(requested_id) == str(response_id_value)
        )
        if (
            requested_id_type
            and response_id_status == "valid"
            and not is_same_requested_id
        ):
            id_updates.append(
                IdUpdate(
                    id_type=requested_id_type,
                    value=requested_id,
                    status="valid",
                    fayda_response_status=response_status,
                )
            )

        update = FarmerDedupUpdate(
            requested_id=requested_id,
            requested_id_type=requested_id_type,
            partner_values=partner_values,
            id_updates=id_updates,
            response_status=response_status,
        )

        if self.is_complete_valid_update(update):
            update.is_valid_complete_update = True
            self.mark_processed_id_flags(
                update=update,
                requested_id=requested_id,
                requested_id_type=requested_id_type,
                received_id=response_id_value,
                received_id_type=response_id_type,
            )

        return update

    def build_invalid_update(
        self,
        requested_id: str,
        requested_id_type: str,
        message: str | None,
        response_status: str | None,
    ) -> FarmerDedupUpdate:
        return FarmerDedupUpdate(
            requested_id=requested_id,
            requested_id_type=requested_id_type,
            partner_values={},
            id_updates=[
                IdUpdate(
                    id_type=requested_id_type,
                    value=requested_id,
                    expiry_date=self.default_expiry_date(),
                    status="invalid",
                    description=message or "No description provided",
                    fayda_response_status=response_status,
                    fayda_processed=False,
                )
            ],
            response_status=response_status,
            is_valid_complete_update=False,
        )

    def map_partner_values(self, data: dict[str, Any]) -> dict:
        full_name_eng = self.get_localized_value(data.get("fullName", []), "eng")
        given_name, family_name, gf_name_eng = self.get_name_parts(data, "eng")
        first_name_amh, family_name_amh, gf_name_amh = self.get_name_parts(data, "amh")

        return {
            "name": full_name_eng,
            "given_name": given_name,
            "family_name": family_name,
            "addl_name": gf_name_eng,
            "gf_name_eng": gf_name_eng,
            "first_name_amh": first_name_amh,
            "family_name_amh": family_name_amh,
            "gf_name_amh": gf_name_amh,
            "gender": self.get_localized_value(data.get("gender", []), "eng"),
            "birthdate": self.parse_birthdate(data.get("dateOfBirth")),
            "birth_place": data.get("birth_place") or "",
            "image_1920": data.get("photo") or "",
            "registration_date": datetime.now(UTC).date().isoformat(),
        }

    def get_response_id_value(self, data: dict[str, Any]) -> str:
        value = data.get(self.settings.response_id_field)
        if value is None:
            value = data.get("fin")
        return str(value or "").strip()

    def get_response_id_status(
        self,
        value: str,
        message: str,
        id_type: str,
    ) -> tuple[str, str]:
        clean_value = str(value or "").replace(" ", "")
        if id_type == "FAN":
            if len(clean_value) != 16:
                return "invalid", "FAN has invalid format - length"
            return "valid", message

        if len(clean_value) > 15:
            return "invalid", "FIN has invalid format - length"
        return "valid", message

    def is_complete_valid_update(self, update: FarmerDedupUpdate) -> bool:
        for field in self.settings.required_update_field_list:
            if not update.partner_values.get(field):
                _logger.info(
                    "Not marking %s as Fayda-updated because field %s is empty.",
                    update.requested_id,
                    field,
                )
                return False

        return any(id_update.status == "valid" for id_update in update.id_updates)

    def mark_processed_id_flags(
        self,
        update: FarmerDedupUpdate,
        requested_id: str,
        requested_id_type: str,
        received_id: str,
        received_id_type: str,
    ) -> None:
        for id_update in update.id_updates:
            if id_update.status != "valid":
                continue

            is_sent_id = (
                id_update.id_type == requested_id_type
                and str(id_update.value) == str(requested_id)
            )
            is_received_id = (
                id_update.id_type == received_id_type
                and str(id_update.value) == str(received_id)
            )
            if is_sent_id or is_received_id:
                id_update.fayda_processed = True

    def get_name_parts(self, data: dict[str, Any], language: str) -> tuple[str, str, str]:
        full_name = self.get_localized_value(data.get("fullName", []), language)
        parts = full_name.split()
        first_name = parts[0] if len(parts) > 0 else ""
        family_name = parts[1] if len(parts) > 1 else ""
        gf_name = parts[2] if len(parts) > 2 else ""
        return first_name, family_name, gf_name

    @staticmethod
    def get_localized_value(values: list[dict[str, Any]], language: str) -> str:
        for value in values or []:
            if value.get("language") == language:
                return value.get("value") or ""
        return ""

    @staticmethod
    def parse_birthdate(value: str | None) -> str:
        if not value:
            return ""
        try:
            return datetime.strptime(value, "%Y/%m/%d").date().isoformat()
        except ValueError:
            _logger.info("Could not parse NIDP birthdate value: %s", value)
            return ""

    @staticmethod
    def default_expiry_date() -> str:
        return (datetime.now(UTC) + timedelta(days=365)).date().isoformat()
