from collections import defaultdict
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import FarmerApprovalCandidate
from ..utils.farmer_approval_validator import (
    build_duplicate_national_id_partners,
    m2o_id,
    to_text,
)


class FarmerApprovalRepository:
    """Direct DB access for post-dedup farmer approval processing."""

    async def fetch_successfully_deduped_draft_farmers(
        self,
        session: AsyncSession,
        *,
        valid_id_types: list[str],
        response_status: str,
        state: str,
        limit: int,
        partner_unique_id_prefix: str = "",
    ) -> list[FarmerApprovalCandidate]:
        if not valid_id_types:
            return []

        query = (
            text(
                """
                SELECT DISTINCT ON (rp.id)
                    rp.id AS partner_id,
                    t.name AS dedup_id_type,
                    gid.value AS dedup_id_value
                FROM res_partner rp
                JOIN g2p_reg_id gid ON gid.partner_id = rp.id
                JOIN g2p_id_type t ON t.id = gid.id_type
                WHERE rp.is_farmer = 'yes'
                  AND rp.is_registrant = TRUE
                  AND rp.is_group = FALSE
                  AND rp.active = TRUE
                  AND rp.state = :state
                  AND (
                      :partner_unique_id_prefix = ''
                      OR rp.unique_id LIKE :partner_unique_id_pattern
                  )
                  AND t.name IN :valid_id_types
                  AND gid.value IS NOT NULL
                  AND BTRIM(gid.value) <> ''
                  AND gid.fayda_processed = 'true'
                  AND UPPER(COALESCE(gid.fayda_response_status, '')) = UPPER(:response_status)
                ORDER BY rp.id ASC, t.name ASC, gid.id ASC
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
                "state": state,
                "limit": limit,
                "partner_unique_id_prefix": partner_unique_id_prefix,
                "partner_unique_id_pattern": f"{partner_unique_id_prefix}%",
            },
        )
        return [
            FarmerApprovalCandidate.model_validate(row)
            for row in result.mappings().all()
        ]

    async def load_partners(
        self,
        session: AsyncSession,
        partner_ids: list[int],
    ) -> list[dict[str, Any]]:
        if not partner_ids:
            return []

        result = await session.execute(
            text(
                """
                SELECT
                    rp.id,
                    rp.name,
                    rp.state,
                    rp.is_group,
                    rp.is_farmer,
                    rp.unique_id,
                    rp.farmer_id,
                    rp.given_name,
                    rp.family_name,
                    rp.gf_name_eng,
                    rp.first_name_amh,
                    rp.family_name_amh,
                    rp.gf_name_amh,
                    rp.first_name_other,
                    rp.family_name_other,
                    rp.gf_name_other,
                    rp.gender,
                    rp.birthdate,
                    rp.birthdate_ec,
                    NULL::text AS age,
                    rp.age_int,
                    rp."primary_Language" AS primary_language_id,
                    lang.name AS primary_language_name,
                    rp.registration_date,
                    rp.rec_import_source AS rec_import_source_id,
                    src.name AS rec_import_source_name,
                    rp.region AS region_id,
                    region.name AS region_name,
                    rp.zone AS zone_id,
                    zone.name AS zone_name,
                    rp.woreda AS woreda_id,
                    woreda.name AS woreda_name,
                    rp.kebele AS kebele_id,
                    kebele.name AS kebele_name,
                    rp.hh_is_household_head,
                    rp.size_of_family,
                    rp.number_of_children_in_family,
                    rp.number_of_males_in_family,
                    rp.number_of_females_in_family,
                    rp.education,
                    rp.martial_status,
                    rp.is_psnp_user,
                    rp.farming_type,
                    rp.total_land_area,
                    rp.total_land_owned_area,
                    rp.total_land_rent_area,
                    rp.total_land_crop_sharing_area,
                    rp.land_ownership,
                    rp.enumerator_id AS enumerator_id,
                    enum.name AS enumerator_name
                FROM res_partner rp
                LEFT JOIN g2p_import_source src ON src.id = rp.rec_import_source
                LEFT JOIN g2p_lang lang ON lang.id = rp."primary_Language"
                LEFT JOIN g2p_region region ON region.id = rp.region
                LEFT JOIN g2p_zone zone ON zone.id = rp.zone
                LEFT JOIN g2p_woreda woreda ON woreda.id = rp.woreda
                LEFT JOIN g2p_kebele kebele ON kebele.id = rp.kebele
                LEFT JOIN g2p_enumerator enum ON enum.id = rp.enumerator_id
                WHERE rp.id = ANY(:partner_ids)
                ORDER BY rp.id ASC
                """
            ),
            {"partner_ids": partner_ids},
        )
        partners: list[dict[str, Any]] = []
        for row in result.mappings().all():
            partner = dict(row)
            partner["primary_Language"] = self.as_m2o(
                row.get("primary_language_id"),
                row.get("primary_language_name"),
            )
            partner["rec_import_source"] = self.as_m2o(
                row.get("rec_import_source_id"),
                row.get("rec_import_source_name"),
            )
            partner["region"] = self.as_m2o(row.get("region_id"), row.get("region_name"))
            partner["zone"] = self.as_m2o(row.get("zone_id"), row.get("zone_name"))
            partner["woreda"] = self.as_m2o(row.get("woreda_id"), row.get("woreda_name"))
            partner["kebele"] = self.as_m2o(row.get("kebele_id"), row.get("kebele_name"))
            partner["enumerator_id"] = self.as_m2o(
                row.get("enumerator_id"),
                row.get("enumerator_name"),
            )
            partners.append(partner)
        return partners

    async def load_related(
        self,
        session: AsyncSession,
        partner_ids: list[int],
        check_global_land_duplicates: bool,
    ) -> dict[str, Any]:
        if not partner_ids:
            return self.empty_related()

        reg_rows = await self.fetch_all(
            session,
            """
            SELECT
                gid.id,
                gid.partner_id,
                gid.id_type,
                t.name AS id_type_name,
                gid.value,
                gid.status,
                gid.description
            FROM g2p_reg_id gid
            LEFT JOIN g2p_id_type t ON t.id = gid.id_type
            WHERE gid.partner_id = ANY(:partner_ids)
            """,
            {"partner_ids": partner_ids},
        )
        for row in reg_rows:
            row["partner_id"] = self.as_m2o(row.get("partner_id"), "")
            row["id_type"] = self.as_m2o(row.get("id_type"), row.get("id_type_name"))

        phone_rows = await self.fetch_all(
            session,
            """
            SELECT id, partner_id, phone_no, phone_type, disabled
            FROM g2p_phone_number
            WHERE partner_id = ANY(:partner_ids)
            """,
            {"partner_ids": partner_ids},
        )
        for row in phone_rows:
            row["partner_id"] = self.as_m2o(row.get("partner_id"), "")

        land_rows = await self.fetch_all(
            session,
            """
            SELECT
                li.id,
                li.partner_id,
                li.land_id,
                li.land_kebele,
                k.name AS land_kebele_name,
                li.ownership_type,
                li.total_land_area,
                li.land_certificate,
                sf.name AS land_certificate_name
            FROM g2p_land_information li
            LEFT JOIN g2p_kebele k ON k.id = li.land_kebele
            LEFT JOIN storage_file sf ON sf.id = li.land_certificate
            WHERE li.partner_id = ANY(:partner_ids)
            """,
            {"partner_ids": partner_ids},
        )
        for row in land_rows:
            row["partner_id"] = self.as_m2o(row.get("partner_id"), "")
            row["land_kebele"] = self.as_m2o(
                row.get("land_kebele"),
                row.get("land_kebele_name"),
            )
            row["land_certificate"] = self.as_m2o(
                row.get("land_certificate"),
                row.get("land_certificate_name"),
            )

        membership_rows = await self.fetch_all(
            session,
            """
            SELECT
                gm.id,
                gm.individual,
                individual.name AS individual_name,
                gm."group",
                grp.name AS group_name
            FROM g2p_group_membership gm
            LEFT JOIN res_partner individual ON individual.id = gm.individual
            LEFT JOIN res_partner grp ON grp.id = gm."group"
            WHERE gm.individual = ANY(:partner_ids)
              AND COALESCE(gm.is_ended, FALSE) = FALSE
            """,
            {"partner_ids": partner_ids},
        )
        membership_ids = [
            int(row["id"])
            for row in membership_rows
            if row.get("id") is not None
        ]
        kind_rel_rows = []
        if membership_ids:
            kind_rel_rows = await self.fetch_all(
                session,
                """
                SELECT
                    rel.g2p_group_membership_id AS membership_id,
                    rel.g2p_group_membership_kind_id AS kind_id,
                    kind.name AS kind_name
                FROM g2p_group_membership_g2p_group_membership_kind_rel rel
                LEFT JOIN g2p_group_membership_kind kind
                    ON kind.id = rel.g2p_group_membership_kind_id
                WHERE rel.g2p_group_membership_id = ANY(:membership_ids)
                """,
                {"membership_ids": membership_ids},
            )
        kind_by_membership: dict[int, list[int]] = defaultdict(list)
        membership_kind_names: dict[int, str] = {}
        for row in kind_rel_rows:
            membership_id = int(row["membership_id"])
            kind_id = int(row["kind_id"])
            kind_by_membership[membership_id].append(kind_id)
            membership_kind_names[kind_id] = to_text(row.get("kind_name"))

        for row in membership_rows:
            row["individual"] = self.as_m2o(
                row.get("individual"),
                row.get("individual_name"),
            )
            row["group"] = self.as_m2o(row.get("group"), row.get("group_name"))
            row["kind"] = kind_by_membership.get(int(row["id"]), [])

        income_rows = await self.fetch_all(
            session,
            """
            SELECT res_partner_id, g2p_hh_income_id
            FROM g2p_hh_income_res_partner_rel
            WHERE res_partner_id = ANY(:partner_ids)
            """,
            {"partner_ids": partner_ids},
        )
        hh_income_by_partner: dict[int, list[int]] = defaultdict(list)
        for row in income_rows:
            hh_income_by_partner[int(row["res_partner_id"])].append(
                int(row["g2p_hh_income_id"])
            )

        related_ids = await self.fetch_all(
            session,
            """
            SELECT
                rp.id AS partner_id,
                rp.region,
                rp.zone,
                rp.woreda,
                rp.kebele,
                rp.enumerator_id
            FROM res_partner rp
            WHERE rp.id = ANY(:partner_ids)
            """,
            {"partner_ids": partner_ids},
        )
        region_ids = sorted({row["region"] for row in related_ids if row.get("region")})
        zone_ids = sorted({row["zone"] for row in related_ids if row.get("zone")})
        woreda_ids = sorted({row["woreda"] for row in related_ids if row.get("woreda")})
        kebele_ids = sorted(
            {row["kebele"] for row in related_ids if row.get("kebele")}
            | {row["land_kebele"][0] for row in land_rows if row.get("land_kebele")}
        )
        enumerator_ids = sorted(
            {row["enumerator_id"] for row in related_ids if row.get("enumerator_id")}
        )

        regions = await self.read_locations(
            session,
            "g2p_region",
            region_ids,
            ["id", "name", "code", "iso_code"],
        )
        zones = await self.read_locations(
            session,
            "g2p_zone",
            zone_ids,
            ["id", "name", "code", "region"],
        )
        for row in zones.values():
            row["region"] = self.as_m2o(row.get("region"), "")
        woredas = await self.read_locations(
            session,
            "g2p_woreda",
            woreda_ids,
            ["id", "name", "code", "zone"],
        )
        for row in woredas.values():
            row["zone"] = self.as_m2o(row.get("zone"), "")
        kebeles = await self.read_locations(
            session,
            "g2p_kebele",
            kebele_ids,
            ["id", "name", "code", "woreda"],
        )
        for row in kebeles.values():
            row["woreda"] = self.as_m2o(row.get("woreda"), "")
        enumerators = await self.read_locations(
            session,
            "g2p_enumerator",
            enumerator_ids,
            ["id", "name", "enumerator_user_id", "data_collection_date"],
        )

        duplicate_land_ids: set[str] = set()
        if check_global_land_duplicates:
            land_ids = sorted(
                {to_text(row.get("land_id")) for row in land_rows if to_text(row.get("land_id"))}
            )
            if land_ids:
                duplicate_rows = await self.fetch_all(
                    session,
                    """
                    SELECT land_id
                    FROM g2p_land_information
                    WHERE land_id = ANY(:land_ids)
                    GROUP BY land_id
                    HAVING COUNT(*) > 1
                    """,
                    {"land_ids": land_ids},
                )
                duplicate_land_ids = {
                    to_text(row.get("land_id"))
                    for row in duplicate_rows
                }

        duplicate_national_id_partners = await self.load_duplicate_national_id_partners(
            session,
            reg_rows,
        )

        return {
            "reg_by_partner": self.group_by_m2o(reg_rows, "partner_id"),
            "phones_by_partner": self.group_by_m2o(phone_rows, "partner_id"),
            "lands_by_partner": self.group_by_m2o(land_rows, "partner_id"),
            "memberships_by_partner": self.group_by_m2o(
                membership_rows,
                "individual",
            ),
            "regions": regions,
            "zones": zones,
            "woredas": woredas,
            "kebeles": kebeles,
            "enumerators": enumerators,
            "membership_kind_names": membership_kind_names,
            "duplicate_land_ids": duplicate_land_ids,
            "duplicate_national_id_partners": duplicate_national_id_partners,
            "hh_income_by_partner": hh_income_by_partner,
        }

    async def load_duplicate_national_id_partners(
        self,
        session: AsyncSession,
        reg_rows: list[dict[str, Any]],
    ) -> dict[tuple[str, str], set[int]]:
        values = sorted(
            {
                to_text(row.get("value"))
                for row in reg_rows
                if to_text(row.get("id_type_name")).upper() in {"UID", "FAN"}
                and to_text(row.get("value"))
            }
        )
        if not values:
            return {}

        rows = await self.fetch_all(
            session,
            """
            SELECT
                gid.partner_id,
                gid.id_type,
                t.name AS id_type_name,
                gid.value
            FROM g2p_reg_id gid
            JOIN g2p_id_type t ON t.id = gid.id_type
            WHERE t.name IN ('UID', 'FAN')
              AND BTRIM(gid.value) = ANY(:values)
              AND gid.partner_id IS NOT NULL
              AND gid.value IS NOT NULL
              AND BTRIM(gid.value) <> ''
            """,
            {"values": values},
        )
        for row in rows:
            row["partner_id"] = self.as_m2o(row.get("partner_id"), "")
            row["id_type"] = self.as_m2o(row.get("id_type"), row.get("id_type_name"))
        return build_duplicate_national_id_partners(rows)

    async def approve_farmer(
        self,
        session: AsyncSession,
        *,
        partner_id: int,
        farmer_id: str,
        write_uid: int | None = None,
    ) -> int:
        if write_uid:
            result = await session.execute(
                text(
                    """
                    UPDATE res_partner
                    SET state = 'approved',
                        farmer_id = :farmer_id,
                        write_date = NOW(),
                        write_uid = :write_uid
                    WHERE id = :partner_id
                      AND state = 'draft'
                    """
                ),
                {
                    "partner_id": partner_id,
                    "farmer_id": farmer_id,
                    "write_uid": write_uid,
                },
            )
        else:
            result = await session.execute(
                text(
                    """
                    UPDATE res_partner
                    SET state = 'approved',
                        farmer_id = :farmer_id,
                        write_date = NOW()
                    WHERE id = :partner_id
                      AND state = 'draft'
                    """
                ),
                {"partner_id": partner_id, "farmer_id": farmer_id},
            )
        return int(result.rowcount or 0)

    async def fetch_all(
        self,
        session: AsyncSession,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = await session.execute(text(query), params or {})
        return [dict(row) for row in result.mappings().all()]

    async def read_locations(
        self,
        session: AsyncSession,
        table: str,
        ids: list[int],
        fields: list[str],
    ) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        field_sql = ", ".join(fields)
        rows = await self.fetch_all(
            session,
            f"SELECT {field_sql} FROM {table} WHERE id = ANY(:ids)",
            {"ids": ids},
        )
        return {int(row["id"]): row for row in rows if row.get("id") is not None}

    @staticmethod
    def as_m2o(record_id: Any, name: Any) -> list[Any] | bool:
        if record_id in (None, False, ""):
            return False
        return [int(record_id), to_text(name)]

    @staticmethod
    def group_by_m2o(
        rows: list[dict[str, Any]],
        field_name: str,
    ) -> dict[int, list[dict[str, Any]]]:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            record_id = m2o_id(row.get(field_name))
            if record_id:
                grouped[record_id].append(row)
        return grouped

    @staticmethod
    def empty_related() -> dict[str, Any]:
        return {
            "reg_by_partner": {},
            "phones_by_partner": {},
            "lands_by_partner": {},
            "memberships_by_partner": {},
            "regions": {},
            "zones": {},
            "woredas": {},
            "kebeles": {},
            "enumerators": {},
            "membership_kind_names": {},
            "duplicate_land_ids": set(),
            "duplicate_national_id_partners": {},
            "hh_income_by_partner": {},
        }
