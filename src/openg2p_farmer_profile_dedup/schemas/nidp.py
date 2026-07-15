from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class NidpGetDataByIdItem(BaseModel):
    id: str


class NidpGetDataByIdRequest(BaseModel):
    id: str
    version: str
    request_time: str = Field(alias="requestTime")
    request: list[NidpGetDataByIdItem]


class NidpChunkResult(BaseModel):
    requested_ids: list[str]
    response: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.response is not None


def utc_request_time() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
