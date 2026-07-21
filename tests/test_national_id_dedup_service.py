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
    partner_unique_id_prefix = ""
    rerun_invalid_records = True
    background_enabled = False
    lock_enabled = True
    response_id_type = "FAN"
    response_id_field = "fan"
    service_db_auto_migrate = True


class FakeFarmerIdRepository:
    def __init__(self, pending_ids):
        self.pending_ids = pending_ids

    async def fetch_pending_ids(
        self,
        session,
        include_id_types,
        limit,
        partner_unique_id_prefix="",
        rerun_invalid_records=True,
    ):
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


class FakeLogRepository:
    def __init__(self):
        self.runs = []
        self.finished_runs = []
        self.chunks = []
        self.finished_chunks = []
        self.pending_items = []
        self.update_items = []
        self.next_run_id = 1
        self.next_chunk_id = 10

    async def create_run(self, session, **kwargs):
        self.runs.append(kwargs)
        run_id = self.next_run_id
        self.next_run_id += 1
        return run_id

    async def finish_run(self, session, run_id, **kwargs):
        self.finished_runs.append((run_id, kwargs))

    async def create_chunk(self, session, **kwargs):
        self.chunks.append(kwargs)
        chunk_id = self.next_chunk_id
        self.next_chunk_id += 1
        return chunk_id

    async def finish_chunk(self, session, chunk_id, **kwargs):
        self.finished_chunks.append((chunk_id, kwargs))

    async def log_pending_items(self, session, **kwargs):
        self.pending_items.append(kwargs)

    async def log_updates(self, session, **kwargs):
        self.update_items.append(kwargs)


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
        service.log_repository = FakeLogRepository()
        return service

    async def test_dry_run_does_not_write(self):
        service = self.build_service(
            [PendingId(partner_id=1, reg_id=10, id_type="UID", value="102783059500")],
            processed_response(),
        )

        with patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_session",
            fake_get_session,
        ), patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_service_session",
            fake_get_session,
        ):
            result = await service.run_once(dry_run=True)

        self.assertEqual(result.run_id, 1)
        self.assertEqual(result.fetched, 1)
        self.assertEqual(result.sent_to_nidp, 1)
        self.assertEqual(result.transformed, 1)
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.updated, 0)
        self.assertEqual(service.farmer_update_repository.calls, [])
        self.assertEqual(result.status, "dry_run_complete")
        self.assertEqual(service.log_repository.finished_runs[0][1]["status"], "dry_run_complete")
        self.assertEqual(service.log_repository.update_items[0]["update_status"], "dry_run")

    async def test_successful_run_marks_ids_processed_and_writes(self):
        service = self.build_service(
            [PendingId(partner_id=1, reg_id=10, id_type="UID", value="102783059500")],
            processed_response(),
        )

        with patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_session",
            fake_get_session,
        ), patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_service_session",
            fake_get_session,
        ):
            result = await service.run_once(dry_run=False)

        self.assertEqual(result.updated, 1)
        updates = service.farmer_update_repository.calls[0]
        id_updates = {id_update.id_type: id_update for id_update in updates[0].id_updates}
        self.assertTrue(id_updates["FAN"].fayda_processed)
        self.assertTrue(id_updates["UID"].fayda_processed)
        self.assertEqual(result.status, "db_update_complete")
        self.assertEqual(service.log_repository.update_items[0]["update_status"], "updated")

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
        ), patch(
            "openg2p_farmer_profile_dedup.services.national_id_dedup_service.get_service_session",
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
