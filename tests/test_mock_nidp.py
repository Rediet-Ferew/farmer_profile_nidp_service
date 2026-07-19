import unittest

from openg2p_farmer_profile_dedup.controllers.mock_nidp import MockNidpController


class TestMockNidpController(unittest.IsolatedAsyncioTestCase):
    async def test_returns_success_for_seed_uid(self):
        response = await MockNidpController().get_data_by_id(
            {
                "id": "openg2p",
                "version": "v1",
                "request": [{"id": "1000 0000 0001"}],
            }
        )

        item = response["response"][0]
        self.assertEqual(item["status"], "PROCESSED")
        self.assertEqual(
            item["message"],
            "Registration has processed successfully.",
        )
        self.assertEqual(item["data"]["fan"], "1000000000011234")
        self.assertIn("Abebe", item["data"]["fullName"][0]["value"])

    async def test_returns_invalid_for_bad_id_format(self):
        response = await MockNidpController().get_data_by_id(
            {
                "id": "openg2p",
                "version": "v1",
                "request": [{"id": "bad-id"}],
            }
        )

        item = response["response"][0]
        self.assertIsNone(item["status"])
        self.assertEqual(item["message"], "Invalid registration id format.")
        self.assertIsNone(item["data"])


if __name__ == "__main__":
    unittest.main()
