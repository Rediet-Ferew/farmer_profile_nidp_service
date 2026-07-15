import unittest

from openg2p_farmer_profile_dedup.services import ResponseTransformer


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


class TestResponseTransformer(unittest.TestCase):
    def test_transform_processed_response_marks_ids_processed(self):
        updates = ResponseTransformer().transform_get_data_by_id_response(
            processed_response(),
            {"102783059500": "UID"},
        )

        self.assertEqual(len(updates), 1)
        update = updates[0]
        self.assertTrue(update.is_valid_complete_update)
        self.assertEqual(update.partner_values["name"], "Abebe Kebede Bekele")
        self.assertEqual(update.partner_values["given_name"], "Abebe")
        self.assertEqual(update.partner_values["family_name"], "Kebede")
        self.assertEqual(update.partner_values["gf_name_eng"], "Bekele")
        self.assertEqual(update.partner_values["first_name_amh"], "አበበ")
        self.assertEqual(update.partner_values["family_name_amh"], "ከበደ")
        self.assertEqual(update.partner_values["gf_name_amh"], "በቀለ")
        self.assertEqual(update.partner_values["gender"], "Male")
        self.assertEqual(update.partner_values["birthdate"], "1990-01-01")
        self.assertEqual(update.partner_values["image_1920"], "/9j/test")

        id_updates = {id_update.id_type: id_update for id_update in update.id_updates}
        self.assertEqual(id_updates["FAN"].value, "1027830595001234")
        self.assertEqual(id_updates["FAN"].status, "valid")
        self.assertEqual(id_updates["FAN"].description, "Data retrieved successfully.")
        self.assertTrue(id_updates["FAN"].fayda_processed)
        self.assertEqual(id_updates["FAN"].fayda_response_status, "PROCESSED")

        self.assertEqual(id_updates["UID"].value, "102783059500")
        self.assertEqual(id_updates["UID"].status, "valid")
        self.assertTrue(id_updates["UID"].fayda_processed)
        self.assertEqual(id_updates["UID"].fayda_response_status, "PROCESSED")

    def test_transform_failed_response_keeps_id_unprocessed(self):
        updates = ResponseTransformer().transform_get_data_by_id_response(
            failed_response(),
            {"12345678901234567890123456789": "RID"},
        )

        self.assertEqual(len(updates), 1)
        update = updates[0]
        self.assertFalse(update.is_valid_complete_update)
        self.assertEqual(update.partner_values, {})
        self.assertEqual(len(update.id_updates), 1)
        id_update = update.id_updates[0]
        self.assertEqual(id_update.id_type, "RID")
        self.assertEqual(id_update.status, "invalid")
        self.assertEqual(id_update.description, "Invalid ID format.")
        self.assertFalse(id_update.fayda_processed)
        self.assertEqual(id_update.fayda_response_status, "FAILED")


if __name__ == "__main__":
    unittest.main()

