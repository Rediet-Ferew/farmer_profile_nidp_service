import logging

import httpx

from ..config import get_settings
from ..schemas import NidpChunkResult, NidpGetDataByIdItem, NidpGetDataByIdRequest
from ..schemas.nidp import utc_request_time

_logger = logging.getLogger(__name__)


class NidpClient:
    """Client wrapper for the NIDP/Fayda getDataById API."""

    def __init__(self):
        self.settings = get_settings()

    def build_get_data_by_id_payload(self, ids: list[str]) -> dict:
        payload = NidpGetDataByIdRequest(
            id=self.settings.nidp_caller_id,
            version=self.settings.nidp_api_version,
            requestTime=utc_request_time(),
            request=[NidpGetDataByIdItem(id=value) for value in ids],
        )
        return payload.model_dump(by_alias=True)

    async def call_get_data_by_id(self, ids: list[str]) -> NidpChunkResult:
        payload = self.build_get_data_by_id_payload(ids)

        try:
            async with httpx.AsyncClient(
                timeout=self.settings.nidp_timeout_seconds,
            ) as client:
                response = await client.post(
                    self.settings.nidp_get_data_by_id_url,
                    json=payload,
                )
                response.raise_for_status()
                return NidpChunkResult(requested_ids=ids, response=response.json())
        except httpx.TimeoutException as error:
            _logger.exception("NIDP getDataById timed out for %s IDs", len(ids))
            return NidpChunkResult(requested_ids=ids, error=f"timeout: {error}")
        except httpx.HTTPStatusError as error:
            _logger.exception(
                "NIDP getDataById returned HTTP %s for %s IDs",
                error.response.status_code,
                len(ids),
            )
            return NidpChunkResult(
                requested_ids=ids,
                error=f"http_status_{error.response.status_code}: {error}",
            )
        except httpx.HTTPError as error:
            _logger.exception("NIDP getDataById HTTP error for %s IDs", len(ids))
            return NidpChunkResult(requested_ids=ids, error=f"http_error: {error}")
        except ValueError as error:
            _logger.exception("NIDP getDataById returned invalid JSON")
            return NidpChunkResult(requested_ids=ids, error=f"invalid_json: {error}")
