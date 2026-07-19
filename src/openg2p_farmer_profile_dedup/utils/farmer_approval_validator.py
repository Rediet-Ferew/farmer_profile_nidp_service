import re
from collections import defaultdict
from typing import Any

from ..schemas import ApprovalValidationResult

SUCCESS_DESCRIPTION = "Registration has processed successfully."
NATIONAL_ID_TYPES = {"FAN", "UID", "FIN", "RID"}
SOURCE_ODK = "odk"
SOURCE_PULA = "pula"


def to_text(value: Any) -> str:
    if value in (None, False):
        return ""
    text = str(value).strip()
    if text.casefold() in {"none", "null", "nan", "false"}:
        return ""
    return text


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", to_text(value)).casefold()


def m2o_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, int):
        return value
    return None


def m2o_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) > 1:
        return to_text(value[1])
    return ""


def is_blank(value: Any) -> bool:
    return to_text(value) == ""


def parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = to_text(value)
    if not text:
        return None
    match = re.search(r"-?\d+", text)
    if not match:
        return None
    return int(match.group(0))


def is_valid_name_part(value: Any) -> bool:
    text = to_text(value)
    if not text:
        return False
    return all(char.isalpha() or char in {" ", "-", "'", "’"} for char in text)


def has_successful_description(value: Any) -> bool:
    return SUCCESS_DESCRIPTION.casefold() in to_text(value).casefold()


def is_active_phone(phone: dict[str, Any]) -> bool:
    return phone.get("disabled") in (False, None, "")


def phone_has_valid_format(phone_no: Any) -> bool:
    return bool(re.fullmatch(r"\+251\d{9}", to_text(phone_no)))


def get_id_type_name(reg_id: dict[str, Any]) -> str:
    return m2o_name(reg_id.get("id_type"))


def build_duplicate_national_id_partners(
    reg_ids: list[dict[str, Any]],
) -> dict[tuple[str, str], set[int]]:
    partners_by_id_value: dict[tuple[str, str], set[int]] = defaultdict(set)
    for reg_id in reg_ids:
        id_type = get_id_type_name(reg_id).upper()
        if id_type not in {"UID", "FAN"}:
            continue
        value = to_text(reg_id.get("value"))
        partner_id = m2o_id(reg_id.get("partner_id"))
        if value and partner_id:
            partners_by_id_value[(id_type, value)].add(partner_id)
    return {
        key: partner_ids
        for key, partner_ids in partners_by_id_value.items()
        if len(partner_ids) > 1
    }


class FarmerApprovalValidator:
    """Farmer approval checks mirrored from approve_farmer_records_validation_db.py."""

    def validate_partner(
        self,
        partner: dict[str, Any],
        related: dict[str, Any],
        require_fan: bool,
        require_valid_fan: bool,
        check_global_land_duplicates: bool,
    ) -> ApprovalValidationResult:
        partner_id = int(partner["id"])
        partner["hh_income_type"] = related["hh_income_by_partner"].get(partner_id, [])
        result = ApprovalValidationResult()
        self.validate_personal_identity(partner, result)
        self.validate_national_ids(
            partner,
            related["reg_by_partner"].get(partner_id, []),
            result,
            require_fan=require_fan,
            require_valid_fan=require_valid_fan,
            duplicate_national_id_partners=related["duplicate_national_id_partners"],
        )
        self.validate_phones(related["phones_by_partner"].get(partner_id, []), result)
        self.validate_location(
            partner,
            result,
            related["regions"],
            related["zones"],
            related["woredas"],
            related["kebeles"],
        )
        self.validate_household(
            partner,
            related["memberships_by_partner"].get(partner_id, []),
            related["membership_kind_names"],
            result,
        )
        self.validate_socioeconomic(partner, result)
        self.validate_farming(partner, result)
        self.validate_land(
            partner,
            related["lands_by_partner"].get(partner_id, []),
            result,
            related["kebeles"],
            check_global_land_duplicates=check_global_land_duplicates,
            duplicate_land_ids=related["duplicate_land_ids"],
        )
        self.validate_enumerator(partner, related["enumerators"], result)
        return result

    def validate_personal_identity(
        self,
        partner: dict[str, Any],
        result: ApprovalValidationResult,
    ) -> None:
        self.validate_names(partner, result)
        if is_blank(partner.get("gender")):
            result.fail("missing_gender")
        if is_blank(partner.get("birthdate")) and is_blank(partner.get("birthdate_ec")):
            result.fail("missing_birthdate_gc_and_ec")
        age = parse_int(partner.get("age_int"))
        if age is None:
            age = parse_int(partner.get("age"))
        if age is None:
            result.fail("missing_age")
        else:
            result.details["age"] = str(age)
            if age < 15:
                result.fail("age_below_15")
            if age > 100:
                result.fail("age_above_100")
        if is_blank(partner.get("registration_date")):
            result.fail("missing_registration_date")

    def validate_names(
        self,
        partner: dict[str, Any],
        result: ApprovalValidationResult,
    ) -> None:
        english_parts = [
            ("given_name", "missing_given_name", "short_given_name", "invalid_given_name_characters"),
            ("family_name", "missing_family_name", "short_family_name", "invalid_family_name_characters"),
            ("gf_name_eng", "missing_grandfather_name", "short_grandfather_name", "invalid_grandfather_name_characters"),
        ]
        for field_name, missing_code, short_code, invalid_code in english_parts:
            value = partner.get(field_name)
            if is_blank(value):
                result.fail(missing_code)
                continue
            if len(to_text(value)) <= 1:
                result.fail(short_code)
            if not is_valid_name_part(value):
                result.fail(invalid_code)

        language = norm(m2o_name(partner.get("primary_Language")))
        if not language:
            result.fail("missing_primary_language")
            return

        if "amharic" in language or "አማ" in language:
            local_fields = ("first_name_amh", "family_name_amh", "gf_name_amh")
        elif "english" in language:
            local_fields = ()
        else:
            local_fields = ("first_name_other", "family_name_other", "gf_name_other")

        local_codes = [
            ("missing_local_given_name", "short_local_given_name"),
            ("missing_local_family_name", "short_local_family_name"),
            ("missing_local_grandfather_name", "short_local_grandfather_name"),
        ]
        for field_name, (_missing_code, short_code) in zip(local_fields, local_codes):
            value = partner.get(field_name)
            if is_blank(value):
                continue
            if len(to_text(value)) <= 1:
                result.fail(short_code)

    def validate_national_ids(
        self,
        partner: dict[str, Any],
        reg_ids: list[dict[str, Any]],
        result: ApprovalValidationResult,
        require_fan: bool,
        require_valid_fan: bool,
        duplicate_national_id_partners: dict[tuple[str, str], set[int]] | None = None,
    ) -> None:
        duplicate_national_id_partners = duplicate_national_id_partners or {}
        ids_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for reg_id in reg_ids:
            ids_by_type[get_id_type_name(reg_id).upper()].append(reg_id)

        national_ids = [reg_id for id_type in NATIONAL_ID_TYPES for reg_id in ids_by_type.get(id_type, [])]
        valued_national_ids = [reg_id for reg_id in national_ids if not is_blank(reg_id.get("value"))]
        if not valued_national_ids:
            result.fail("missing_national_id")
        successful_ids = [
            reg_id
            for reg_id in valued_national_ids
            if norm(reg_id.get("status")) == "valid" and has_successful_description(reg_id.get("description"))
        ]
        if not successful_ids:
            result.fail("no_valid_successful_national_id")

        fan_ids = [reg_id for reg_id in ids_by_type.get("FAN", []) if not is_blank(reg_id.get("value"))]
        valid_fan_ids = [
            reg_id
            for reg_id in fan_ids
            if norm(reg_id.get("status")) == "valid" and has_successful_description(reg_id.get("description"))
        ]
        if require_fan and not fan_ids:
            result.fail("missing_fan")
        elif not fan_ids:
            result.fail("missing_fan", severity="warning")
        if require_valid_fan and not valid_fan_ids:
            result.fail("fan_not_valid_successful")

        duplicate_summaries = []
        for id_type in ("UID", "FAN"):
            for reg_id in ids_by_type.get(id_type, []):
                value = to_text(reg_id.get("value"))
                if not value:
                    continue
                duplicate_partner_ids = duplicate_national_id_partners.get((id_type, value), set())
                if duplicate_partner_ids:
                    result.fail(f"duplicate_{id_type.lower()}_value")
                    duplicate_summaries.append(
                        f"{id_type}:{value}:partners={','.join(str(partner_id) for partner_id in sorted(duplicate_partner_ids))}"
                    )
        if duplicate_summaries:
            result.details["duplicate_national_ids"] = "; ".join(duplicate_summaries)

        for id_type in ("FAN", "UID", "FIN", "RID"):
            candidates = [reg_id for reg_id in ids_by_type.get(id_type, []) if not is_blank(reg_id.get("value"))]
            if candidates:
                preferred = candidates[0]
                result.details["national_id_type_used"] = id_type
                result.details["national_id_value_used"] = to_text(preferred.get("value"))
                result.details["national_id_status"] = to_text(preferred.get("status"))
                result.details["national_id_description"] = to_text(preferred.get("description"))
                break

        source = norm(m2o_name(partner.get("rec_import_source")))
        if SOURCE_ODK in source and not any(
            not is_blank(reg_id.get("value"))
            for reg_id in ids_by_type.get("FARMER ODK ACK ID", [])
        ):
            result.fail("missing_farmer_odk_ack_id")
        if SOURCE_PULA in source:
            mavuno_values = ids_by_type.get("MAVUNO FARMER ID", []) + ids_by_type.get("MAVUNO_FARMER_ID", [])
            if not any(not is_blank(reg_id.get("value")) for reg_id in mavuno_values):
                result.fail("missing_mavuno_farmer_id")

    def validate_phones(
        self,
        phones: list[dict[str, Any]],
        result: ApprovalValidationResult,
    ) -> None:
        active = [phone for phone in phones if is_active_phone(phone) and not is_blank(phone.get("phone_no"))]
        if not active:
            result.fail("missing_phone_number")
            return
        primary_or_other = [phone for phone in active if phone.get("phone_type") in {"primary", "other"}]
        if not primary_or_other:
            if any(phone.get("phone_type") == "secondary" for phone in active):
                result.fail("only_secondary_phone_present")
            else:
                result.fail("missing_primary_or_other_phone")
        if any(is_blank(phone.get("phone_type")) for phone in active):
            result.fail("phone_missing_type")
        if any(not to_text(phone.get("phone_no")).startswith("+251") for phone in active):
            result.fail("phone_invalid_prefix")
        if any(not phone_has_valid_format(phone.get("phone_no")) for phone in active):
            result.fail("phone_invalid_length")
        result.details["phone_summary"] = ", ".join(
            f"{to_text(phone.get('phone_type'))}:{to_text(phone.get('phone_no'))}"
            for phone in active
        )

    def validate_location(
        self,
        partner: dict[str, Any],
        result: ApprovalValidationResult,
        regions: dict[int, dict[str, Any]],
        zones: dict[int, dict[str, Any]],
        woredas: dict[int, dict[str, Any]],
        kebeles: dict[int, dict[str, Any]],
    ) -> None:
        region_id = m2o_id(partner.get("region"))
        zone_id = m2o_id(partner.get("zone"))
        woreda_id = m2o_id(partner.get("woreda"))
        kebele_id = m2o_id(partner.get("kebele"))

        if not region_id:
            result.fail("missing_region")
        elif is_blank(regions.get(region_id, {}).get("code")):
            result.fail("missing_region_code")
        if not zone_id:
            result.fail("missing_zone")
        elif is_blank(zones.get(zone_id, {}).get("code")):
            result.fail("missing_zone_code")
        if not woreda_id:
            result.fail("missing_woreda")
        elif is_blank(woredas.get(woreda_id, {}).get("code")):
            result.fail("missing_woreda_code")
        if not kebele_id:
            result.fail("missing_kebele")
        elif is_blank(kebeles.get(kebele_id, {}).get("code")):
            result.fail("missing_kebele_code")

        if region_id and zone_id:
            actual_region_id = m2o_id(zones.get(zone_id, {}).get("region"))
            if actual_region_id and actual_region_id != region_id:
                result.fail("zone_not_under_region")
        if zone_id and woreda_id:
            actual_zone_id = m2o_id(woredas.get(woreda_id, {}).get("zone"))
            if actual_zone_id and actual_zone_id != zone_id:
                result.fail("woreda_not_under_zone")
        if woreda_id and kebele_id:
            actual_woreda_id = m2o_id(kebeles.get(kebele_id, {}).get("woreda"))
            if actual_woreda_id and actual_woreda_id != woreda_id:
                result.fail("kebele_not_under_woreda")

        result.details["location_summary"] = " / ".join(
            [
                m2o_name(partner.get("region")),
                m2o_name(partner.get("zone")),
                m2o_name(partner.get("woreda")),
                m2o_name(partner.get("kebele")),
            ]
        )

    def validate_household(
        self,
        partner: dict[str, Any],
        memberships: list[dict[str, Any]],
        membership_kind_names: dict[int, str],
        result: ApprovalValidationResult,
    ) -> None:
        if is_blank(partner.get("hh_is_household_head")):
            result.fail("missing_household_head_flag")
        if not memberships:
            return

        has_head_kind = False
        missing_kind = False
        membership_summaries = []
        for membership in memberships:
            kind_ids = membership.get("kind") or []
            kind_names = [membership_kind_names.get(int(kind_id), "") for kind_id in kind_ids]
            if not kind_names:
                missing_kind = True
            if any(norm(name) == "head" for name in kind_names):
                has_head_kind = True
            membership_summaries.append(f"{m2o_name(membership.get('group'))}:{','.join(kind_names)}")
        if missing_kind:
            result.fail("household_membership_missing_kind")
        if partner.get("hh_is_household_head") == "yes" and not has_head_kind:
            result.fail("household_head_missing_head_kind")
        result.details["household_summary"] = "; ".join(membership_summaries)

    def validate_socioeconomic(
        self,
        partner: dict[str, Any],
        result: ApprovalValidationResult,
    ) -> None:
        if not partner.get("hh_income_type"):
            result.fail("missing_household_income_type")
        if is_blank(partner.get("education")):
            result.fail("missing_education")
        if is_blank(partner.get("martial_status")):
            result.fail("missing_marital_status")
        if "is_psnp_user" not in partner:
            result.fail("missing_psnp_user")

    def validate_farming(
        self,
        partner: dict[str, Any],
        result: ApprovalValidationResult,
    ) -> None:
        if partner.get("is_farmer") != "yes":
            result.fail("not_marked_as_farmer")
        if is_blank(partner.get("farming_type")):
            result.fail("missing_farming_type")

    def validate_land(
        self,
        partner: dict[str, Any],
        lands: list[dict[str, Any]],
        result: ApprovalValidationResult,
        kebeles: dict[int, dict[str, Any]],
        check_global_land_duplicates: bool,
        duplicate_land_ids: set[str],
    ) -> None:
        if not lands:
            result.fail("missing_land_information")
            return

        farmer_woreda_id = m2o_id(partner.get("woreda"))
        seen_land_ids: set[str] = set()
        has_owner = False
        has_tenant = False
        has_crop_share = False
        land_summaries = []

        for land in lands:
            ownership = to_text(land.get("ownership_type"))
            land_id = to_text(land.get("land_id"))
            area = land.get("total_land_area")
            land_kebele_id = m2o_id(land.get("land_kebele"))

            if not ownership:
                result.fail("missing_ownership_type")
            if ownership in {"owner", "family_gift"}:
                has_owner = True
            if ownership == "tenant":
                has_tenant = True
            if ownership == "crop_share":
                has_crop_share = True

            if ownership not in {"tenant", "crop_share"} and not land_id:
                result.fail("land_id_missing")
            if land_id:
                seen_land_ids.add(land_id)
                if check_global_land_duplicates and land_id in duplicate_land_ids:
                    result.fail("duplicate_land_id_across_farmers", severity="warning")

            if land_kebele_id and farmer_woreda_id:
                land_kebele_woreda = m2o_id(kebeles.get(land_kebele_id, {}).get("woreda"))
                if land_kebele_woreda and land_kebele_woreda != farmer_woreda_id:
                    result.fail("land_kebele_not_under_farmer_woreda")

            if area in (None, False, "") or float(area or 0.0) <= 0.0:
                if ownership == "crop_share":
                    result.fail("crop_share_land_area_missing_or_zero", severity="warning")
                else:
                    result.fail("land_area_missing_or_zero")
            if not m2o_id(land.get("land_certificate")):
                result.fail("missing_land_certificate")
            land_summaries.append(f"{land_id or '-'}:{ownership or '-'}:{area or 0}")

        if has_owner and float(partner.get("total_land_owned_area") or 0.0) <= 0.0:
            result.fail("owned_land_area_missing_or_zero")
        if has_tenant and float(partner.get("total_land_rent_area") or 0.0) <= 0.0:
            result.fail("rented_land_area_missing_or_zero")
        if has_crop_share and float(partner.get("total_land_crop_sharing_area") or 0.0) <= 0.0:
            result.fail("crop_share_land_area_missing_or_zero", severity="warning")
        result.details["land_summary"] = "; ".join(land_summaries)

    def validate_enumerator(
        self,
        partner: dict[str, Any],
        enumerators: dict[int, dict[str, Any]],
        result: ApprovalValidationResult,
    ) -> None:
        enumerator_id = m2o_id(partner.get("enumerator_id"))
        if not enumerator_id:
            result.fail("missing_enumerator")
            return
        enumerator = enumerators.get(enumerator_id, {})
        if is_blank(enumerator.get("name")):
            result.fail("missing_enumerator_name")
        if is_blank(enumerator.get("enumerator_user_id")):
            result.fail("missing_enumerator_user_id")
        if is_blank(enumerator.get("data_collection_date")):
            result.fail("missing_data_collection_date")
        result.details["enumerator_summary"] = (
            f"{to_text(enumerator.get('name'))} / "
            f"{to_text(enumerator.get('enumerator_user_id'))} / "
            f"{to_text(enumerator.get('data_collection_date'))}"
        )
