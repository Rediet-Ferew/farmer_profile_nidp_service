import unittest

from openg2p_farmer_profile_dedup.services import FarmerApprovalService
from openg2p_farmer_profile_dedup.utils.farmer_approval_validator import (
    FarmerApprovalValidator,
)


def complete_partner():
    return {
        "id": 1,
        "name": "Abebe Kebede Bekele",
        "state": "draft",
        "is_farmer": "yes",
        "unique_id": "100000000001",
        "farmer_id": "",
        "given_name": "Abebe",
        "family_name": "Kebede",
        "gf_name_eng": "Bekele",
        "gender": "Male",
        "birthdate": "1990-01-01",
        "birthdate_ec": "",
        "age": "",
        "age_int": 36,
        "primary_Language": [1, "English"],
        "registration_date": "2026-07-19",
        "rec_import_source": [1, "Pula"],
        "region": [1, "Oromiya"],
        "zone": [2, "Jimma"],
        "woreda": [3, "Mana"],
        "kebele": [4, "Kela Guda"],
        "hh_is_household_head": "yes",
        "education": "primary",
        "martial_status": "married",
        "is_psnp_user": False,
        "farming_type": "crop",
        "total_land_owned_area": 1.0,
        "total_land_rent_area": 0.0,
        "total_land_crop_sharing_area": 0.0,
        "enumerator_id": [5, "Enumerator One"],
    }


def complete_related():
    return {
        "reg_by_partner": {
            1: [
                {
                    "partner_id": [1, ""],
                    "id_type": [1, "FAN"],
                    "value": "FAN0001",
                    "status": "valid",
                    "description": "Registration has processed successfully.",
                },
                {
                    "partner_id": [1, ""],
                    "id_type": [2, "Mavuno Farmer ID"],
                    "value": "MAV-0001",
                    "status": "valid",
                    "description": "",
                },
            ]
        },
        "phones_by_partner": {
            1: [
                {
                    "phone_no": "+251911111111",
                    "phone_type": "primary",
                    "disabled": False,
                }
            ]
        },
        "lands_by_partner": {
            1: [
                {
                    "land_id": "OR/01/01/001",
                    "land_kebele": [4, "Kela Guda"],
                    "ownership_type": "owner",
                    "total_land_area": 1.0,
                    "land_certificate": [6, "certificate.jpg"],
                }
            ]
        },
        "memberships_by_partner": {
            1: [
                {
                    "group": [7, "Household One"],
                    "kind": [8],
                }
            ]
        },
        "regions": {1: {"id": 1, "code": "ET04"}},
        "zones": {2: {"id": 2, "code": "ET0401", "region": [1, ""]}},
        "woredas": {3: {"id": 3, "code": "ET040101", "zone": [2, ""]}},
        "kebeles": {4: {"id": 4, "code": "ET04010101", "woreda": [3, ""]}},
        "enumerators": {
            5: {
                "id": 5,
                "name": "Enumerator One",
                "enumerator_user_id": "ENUM-1",
                "data_collection_date": "2026-07-19",
            }
        },
        "membership_kind_names": {8: "Head"},
        "duplicate_land_ids": set(),
        "duplicate_national_id_partners": {},
        "hh_income_by_partner": {1: [9]},
    }


class TestFarmerApprovalValidator(unittest.TestCase):
    def test_complete_partner_is_approvable(self):
        result = FarmerApprovalValidator().validate_partner(
            complete_partner(),
            complete_related(),
            require_fan=False,
            require_valid_fan=False,
            check_global_land_duplicates=False,
        )

        self.assertTrue(result.approvable)

    def test_missing_phone_blocks_approval(self):
        related = complete_related()
        related["phones_by_partner"] = {}

        result = FarmerApprovalValidator().validate_partner(
            complete_partner(),
            related,
            require_fan=False,
            require_valid_fan=False,
            check_global_land_duplicates=False,
        )

        self.assertFalse(result.approvable)
        self.assertIn("missing_phone_number", result.critical)

    def test_farmer_id_is_computed_from_unique_id(self):
        self.assertEqual(
            FarmerApprovalService.compute_farmer_id({"unique_id": "100000000001"}),
            "FR-100000000001",
        )


if __name__ == "__main__":
    unittest.main()
