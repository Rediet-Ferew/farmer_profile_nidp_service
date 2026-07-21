import unittest

from openg2p_farmer_profile_dedup.repositories import FarmerIdRepository


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return FakeMappings(self.rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.executed_query = None
        self.executed_params = None

    async def execute(self, query, params):
        self.executed_query = str(query)
        self.executed_params = params
        return FakeResult(self.rows)


class TestFarmerIdRepository(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_pending_ids_filters_farmers_without_profile_image(self):
        session = FakeSession(
            [
                {
                    "partner_id": 1,
                    "reg_id": 10,
                    "id_type": "RID",
                    "value": "12345678901234567890123456789",
                }
            ]
        )

        result = await FarmerIdRepository().fetch_pending_ids(
            session=session,
            include_id_types=["UID", "FAN", "RID"],
            limit=100,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].partner_id, 1)
        self.assertEqual(result[0].reg_id, 10)
        self.assertEqual(result[0].id_type, "RID")
        self.assertEqual(result[0].value, "12345678901234567890123456789")
        self.assertEqual(session.executed_params["include_id_types"], ["UID", "FAN", "RID"])
        self.assertEqual(session.executed_params["limit"], 100)
        self.assertEqual(session.executed_params["partner_unique_id_prefix"], "")
        self.assertEqual(session.executed_params["partner_unique_id_pattern"], "%")

        query = session.executed_query
        self.assertIn("rp.is_farmer = 'yes'", query)
        self.assertIn("rp.is_registrant = TRUE", query)
        self.assertIn("rp.is_group = FALSE", query)
        self.assertIn("rp.active = TRUE", query)
        self.assertIn("t.name IN", query)
        self.assertIn("NOT EXISTS", query)
        self.assertIn("ir_attachment att", query)
        self.assertIn("att.res_model = 'res.partner'", query)
        self.assertIn("att.res_field = 'image_1920'", query)
        self.assertIn("gid.status IS DISTINCT FROM 'invalid'", query)
        self.assertIn("rp.unique_id LIKE :partner_unique_id_pattern", query)
        self.assertIn("LIMIT", query)
        self.assertEqual(session.executed_params["rerun_invalid_records"], True)

    async def test_fetch_pending_ids_rerun_invalid_records_false_is_passed_through(self):
        session = FakeSession([])

        await FarmerIdRepository().fetch_pending_ids(
            session=session,
            include_id_types=["UID"],
            limit=10,
            rerun_invalid_records=False,
        )

        self.assertEqual(session.executed_params["rerun_invalid_records"], False)

    async def test_fetch_pending_ids_can_filter_by_unique_id_prefix(self):
        session = FakeSession([])

        await FarmerIdRepository().fetch_pending_ids(
            session=session,
            include_id_types=["UID"],
            limit=10,
            partner_unique_id_prefix="LOCAL-FAYDA-PIPELINE",
        )

        self.assertEqual(
            session.executed_params["partner_unique_id_prefix"],
            "LOCAL-FAYDA-PIPELINE",
        )
        self.assertEqual(
            session.executed_params["partner_unique_id_pattern"],
            "LOCAL-FAYDA-PIPELINE%",
        )

    async def test_fetch_pending_ids_does_not_depend_on_farmer_record_fayda_flags(self):
        session = FakeSession([])

        result = await FarmerIdRepository().fetch_pending_ids(
            session=session,
            include_id_types=["FAN"],
            limit=50,
        )

        self.assertEqual(result, [])
        self.assertNotIn("gid.fayda_processed", session.executed_query)
        self.assertNotIn("gid.fayda_processed = 'true'", session.executed_query)

    async def test_fetch_pending_ids_returns_empty_for_no_configured_types(self):
        session = FakeSession([])

        result = await FarmerIdRepository().fetch_pending_ids(
            session=session,
            include_id_types=[],
            limit=50,
        )

        self.assertEqual(result, [])
        self.assertIsNone(session.executed_query)


if __name__ == "__main__":
    unittest.main()
