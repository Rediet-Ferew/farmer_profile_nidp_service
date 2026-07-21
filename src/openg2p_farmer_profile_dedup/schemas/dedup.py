from pydantic import BaseModel, Field


class PendingId(BaseModel):
    partner_id: int
    reg_id: int | None = None
    id_type: str
    value: str


class IdUpdate(BaseModel):
    id_type: str
    value: str
    status: str
    description: str | None = None
    expiry_date: str | None = None
    fayda_processed: bool | None = None
    fayda_response_status: str | None = None


class FarmerDedupUpdate(BaseModel):
    requested_id: str
    requested_id_type: str
    partner_values: dict = Field(default_factory=dict)
    id_updates: list[IdUpdate]
    response_status: str | None = None
    is_valid_complete_update: bool = False


class DedupRunRequest(BaseModel):
    limit: int | None = None
    dry_run: bool | None = None


class DedupRunResponse(BaseModel):
    run_id: int | None = None
    fetched: int = 0
    sent_to_nidp: int = 0
    nidp_chunks: int = 0
    nidp_errors: int = 0
    processed: int = 0
    failed: int = 0
    transformed: int = 0
    updated: int = 0
    skipped: int = 0
    dry_run: bool = True
    status: str = "not_started"


class DedupStatusResponse(BaseModel):
    background_enabled: bool
    lock_enabled: bool
    worker_running: bool = False
    dry_run: bool
    chunk_limit: int
    fetch_limit: int
    include_id_types: list[str]
    partner_unique_id_prefix: str = ""
    response_id_type: str
    response_id_field: str
    service_db_auto_migrate: bool = True
    latest_persisted_run: dict | None = None
    last_run_started_at: str | None = None
    last_run_finished_at: str | None = None
    last_run_status: str | None = None
    last_run_result: DedupRunResponse | None = None
    last_error: str | None = None
