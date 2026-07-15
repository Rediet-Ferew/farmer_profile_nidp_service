import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from openg2p_farmer_profile_dedup.schemas import NidpChunkResult, PendingId
from openg2p_farmer_profile_dedup.services import NationalIdDedupService


class FakeSettings:
    dry_run = True
    fetch_limit = 100
    chunk_limit = 10
    include_id_type_list = ["UID", "FAN", "RID"]
    background_enabled = False
    lock_enabled = True
    processed_flag_value = "false"
    response_id_type = "FAN"
    response_id_field = "fan"


class FakeFarmerIdRepository:
    def __init__(self, pending_ids):
        self.pending_ids = pending_ids

    async def fetch_pending_ids(self, session, include_id_types, limit):
        return self.pending_ids[:limit]


class FakeNidpClient:
    def __init__(self, response):
        self.response = response
        self.called_ids = []

    async def call_get_data_by_id(self, ids):
        self.called_ids.append(ids)
        return NidpChunkResult(requested_ids=ids, response=self.response)


class FakeUpdateRepository:
    def __init__(self):
        self.calls = []

    async def apply_updates(self, session, updates):
        self.calls.append(updates)
        return len(updates)


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@asynccontextmanager
async def fake_get_session():
    yield FakeSession()


def processed_response():
    return {
        "error": None,
        "response": [
            {
                "id": "102783059500",
                "status": "PROCESSED",
                "message": "Data retrieved successfully.",
                "data": {
                    "fan": "1027830595001234",
                    "fullName": [
                        {"language": "eng", "value": "Abebe Kebede Bekele"},
                        {"language": "amh", "value": "አበበ ከበደ በቀለ"},
                    ],
                    "gender": [{"language": "eng", "value": "Male"}],
                    "dateOfBirth": "1990/01/01",
                    "photo": "/9j/test",
                    "birth_place": "Addis Ababa",
                },
            }
        ],
    }


def failed_response():
    return {
        "error": None,
        "response": [
            {
                "id": "12345678901234567890123456789",
                "status": "FAILED",
                "message": "Invalid ID format.",
                "data": None,
            }
        ],
    }


class TestNationalIdDedupService(unittest.IsolatedAsyncioTestCase):
    def build_service(self, pending_ids, response):
        service = NationalIdDedupService()
        service.settings = FakeSettings()
        service.farmer_id_repository = FakeFarmerIdRepository(pending_ids)
        service.nidp_client = FakeNidpClient(response)
        service.farmer_update_repository = FakeUpdateRepository()
        return service

    async def test_dry_run_does_not_write(self):
        service = self.build_service(
            [PendingId(partner_id=1, reg_id=10, id_type="UID", value="102783059500")],
            processed_response(),
        )

        with patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_session",
            fake_get_session,
        ):
            result = await service.run_once(dry_run=True)

        self.assertEqual(result.fetched, 1)
        self.assertEqual(result.sent_to_nidp, 1)
        self.assertEqual(result.transformed, 1)
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.updated, 0)
        self.assertEqual(service.farmer_update_repository.calls, [])
        self.assertEqual(result.status, "dry_run_complete")

    async def test_successful_run_marks_ids_processed_and_writes(self):
        service = self.build_service(
            [PendingId(partner_id=1, reg_id=10, id_type="UID", value="102783059500")],
            processed_response(),
        )

        with patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_session",
            fake_get_session,
        ):
            result = await service.run_once(dry_run=False)

        self.assertEqual(result.updated, 1)
        updates = service.farmer_update_repository.calls[0]
        id_updates = {id_update.id_type: id_update for id_update in updates[0].id_updates}
        self.assertTrue(id_updates["FAN"].fayda_processed)
        self.assertTrue(id_updates["UID"].fayda_processed)
        self.assertEqual(result.status, "db_update_complete")

    async def test_failed_run_keeps_id_unprocessed_and_writes_invalid_status(self):
        service = self.build_service(
            [
                PendingId(
                    partner_id=1,
                    reg_id=10,
                    id_type="RID",
                    value="12345678901234567890123456789",
                )
            ],
            failed_response(),
        )

        with patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_session",
            fake_get_session,
        ):
            result = await service.run_once(dry_run=False)

        self.assertEqual(result.failed, 1)
        self.assertEqual(result.updated, 1)
        updates = service.farmer_update_repository.calls[0]
        id_update = updates[0].id_updates[0]
        self.assertEqual(id_update.status, "invalid")
        self.assertFalse(id_update.fayda_processed)
        self.assertEqual(result.status, "db_update_complete")


if __name__ == "__main__":
    unittest.main()

