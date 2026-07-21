from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter


class MockNidpController:
    SUCCESS_MESSAGE = "Registration has processed successfully."

    TEST_FIRST_NAMES = [
        "Abebe",
        "Kebede",
        "Tadesse",
        "Mulu",
        "Aster",
        "Hana",
        "Tesfaye",
        "Bekele",
        "Dawit",
        "Meron",
    ]
    TEST_FAMILY_NAMES = [
        "Lemma",
        "Girma",
        "Alemu",
        "Haile",
        "Gemechu",
        "Negash",
        "Demissie",
        "Tola",
        "Fekadu",
        "Wolde",
    ]
    TEST_GRANDFATHER_NAMES = [
        "Bekele",
        "Tesema",
        "Kassa",
        "Dagne",
        "Robi",
        "Deressa",
        "Mengistu",
        "Abera",
        "Chala",
        "Biru",
    ]
    TEST_AMHARIC_NAMES = [
        "አበበ ከበደ በቀለ",
        "ከበደ ለማ ግርማ",
        "ታደሰ አለሙ ካሳ",
        "ሙሉ ኃይሌ ዳኘ",
        "አስቴር ገመቹ ሮቢ",
        "ሀና ነጋሽ ደሬሳ",
        "ተስፋዬ ደምሴ መንግስቱ",
        "በቀለ ቶላ አበራ",
        "ዳዊት ፈቃዱ ጫላ",
        "ሜሮን ወልዴ ብሩ",
    ]

    def __init__(self):
        self.router = APIRouter(prefix="/mock", tags=["mock-nidp"])
        self.router.add_api_route(
            "/getDataById",
            self.get_data_by_id,
            methods=["POST"],
        )

    async def get_data_by_id(self, request: dict[str, Any]):
        caller_id = request.get("id")
        version = request.get("version")
        if caller_id not in ["openg2p", "ati", "edrmc", "mowsa"]:
            return self._response(
                request,
                response=None,
                error="Request forbidden for caller id.",
            )

        if version != "v1":
            return self._response(
                request,
                response=None,
                error="Unsupported API version.",
            )

        response_data = []
        for item in request.get("request", []) or []:
            identity_id = item.get("id")
            clean_identity_id = self._normalize_identity_id(identity_id)
            if not self._is_valid_identity_id(identity_id):
                response_data.append(
                    {
                        "id": identity_id,
                        "status": None,
                        "message": "Invalid registration id format.",
                        "data": None,
                    }
                )
            elif clean_identity_id.endswith("999999000"):
                response_data.append(
                    {
                        "id": identity_id,
                        "status": "PROCESSING",
                        "message": "Registration is being processed.",
                        "data": None,
                    }
                )
            elif clean_identity_id.endswith("999999888"):
                response_data.append(
                    {
                        "id": identity_id,
                        "status": "REJECTED",
                        "message": "Registration has been rejected.",
                        "data": None,
                    }
                )
            elif clean_identity_id.endswith("999999777"):
                response_data.append(
                    {
                        "id": identity_id,
                        "status": "PROCESSED",
                        "message": "Registration processed, but no data available.",
                        "data": None,
                    }
                )
            elif clean_identity_id.endswith("999999666"):
                response_data.append(
                    {
                        "id": identity_id,
                        "status": "FAILED",
                        "message": "Registration failed.",
                        "data": None,
                    }
                )
            else:
                response_data.append(
                    {
                        "id": identity_id,
                        "status": "PROCESSED",
                        "message": self.SUCCESS_MESSAGE,
                        "data": self._test_data_for_identity_id(identity_id)
                        or self._successful_data(
                            fan=self._fan_for_identity_id(identity_id),
                        ),
                    }
                )

        return self._response(request, response=response_data, error=None)

    @classmethod
    def _response(
        cls,
        request: dict[str, Any],
        *,
        response: list[dict[str, Any]] | None,
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "id": request.get("id"),
            "responseTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "version": request.get("version"),
            "response": response,
            "error": error,
        }

    @classmethod
    def _successful_data(
        cls,
        fan: str = "1234123412341234",
        english_name: str = "Abebe Kebede Bekele",
        amharic_name: str = "አበበ ከበደ በቀለ",
        gender: str = "Male",
        date_of_birth: str = "1990/01/01",
    ) -> dict[str, Any]:
        return {
            "fullName": [
                {"language": "eng", "value": english_name},
                {"language": "amh", "value": amharic_name},
            ],
            "dateOfBirth": date_of_birth,
            "gender": [
                {"language": "eng", "value": gender},
                {"language": "amh", "value": "ሴት" if gender == "Female" else "ወንድ"},
            ],
            "residenceStatus": [
                {"language": "eng", "value": "Ethiopian"},
                {"language": "amh", "value": "ኢትዮጵያዊ"},
            ],
            "fan": fan,
            # Minimal valid 1x1 JPEG, base64-encoded, so downstream image
            # persistence can be exercised against real (if tiny) image bytes.
            "photo": (
                "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
                "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
                "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
                "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAU"
                "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAA"
                "AAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k="
            ),
        }

    @staticmethod
    def _normalize_identity_id(identity_id: str | None) -> str:
        return str(identity_id or "").replace(" ", "")

    @classmethod
    def _is_valid_identity_id(cls, identity_id: str | None) -> bool:
        identity_id = cls._normalize_identity_id(identity_id)
        return identity_id.isdigit() and len(identity_id) in [12, 16, 29]

    @classmethod
    def _fan_for_identity_id(cls, identity_id: str | None) -> str:
        identity_id = cls._normalize_identity_id(identity_id)
        if len(identity_id) == 12:
            return f"{identity_id}1234"
        if len(identity_id) == 29:
            return f"{identity_id[:12]}1234"
        return identity_id

    @classmethod
    def _test_data_for_identity_id(cls, identity_id: str | None) -> dict[str, Any] | None:
        identity_id = cls._normalize_identity_id(identity_id)
        if not (
            identity_id.isdigit()
            and len(identity_id) == 12
            and identity_id.startswith("100000000")
        ):
            return None

        sequence = int(identity_id[-3:])
        index = (sequence - 1) % len(cls.TEST_FIRST_NAMES)
        cycle = (sequence - 1) // len(cls.TEST_FIRST_NAMES)
        english_name = " ".join(
            [
                cls.TEST_FIRST_NAMES[index],
                cls.TEST_FAMILY_NAMES[(index + cycle) % len(cls.TEST_FAMILY_NAMES)],
                cls.TEST_GRANDFATHER_NAMES[
                    (index + (cycle * 2)) % len(cls.TEST_GRANDFATHER_NAMES)
                ],
            ]
        )
        amharic_name = cls.TEST_AMHARIC_NAMES[index]
        gender = "Female" if sequence % 2 == 0 else "Male"
        year = 1970 + (sequence % 25)
        month = ((sequence - 1) % 12) + 1
        day = ((sequence - 1) % 27) + 1

        return cls._successful_data(
            fan=cls._fan_for_identity_id(identity_id),
            english_name=english_name,
            amharic_name=amharic_name,
            gender=gender,
            date_of_birth=f"{year:04d}/{month:02d}/{day:02d}",
        )
