from pydantic import BaseModel, Field


class FarmerApprovalCandidate(BaseModel):
    partner_id: int
    dedup_id_type: str | None = None
    dedup_id_value: str | None = None


class ApprovalValidationResult(BaseModel):
    critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)

    @property
    def approvable(self) -> bool:
        return not self.critical

    def fail(self, code: str, severity: str = "critical") -> None:
        if severity == "warning":
            self.warnings.append(code)
        else:
            self.critical.append(code)


class FarmerApprovalItemResult(BaseModel):
    partner_id: int
    farmer_name: str = ""
    dedup_id_type: str | None = None
    dedup_id_value: str | None = None
    old_state: str = ""
    new_state: str = ""
    old_farmer_id: str = ""
    new_farmer_id: str = ""
    ready: bool = False
    approved: bool = False
    critical: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)
    error_message: str | None = None


class FarmerApprovalRunRequest(BaseModel):
    limit: int | None = None
    dry_run: bool | None = None


class FarmerApprovalRunResponse(BaseModel):
    run_id: int | None = None
    fetched: int = 0
    ready: int = 0
    approved: int = 0
    blocked: int = 0
    errors: int = 0
    skipped: int = 0
    dry_run: bool = True
    status: str = "not_started"


class FarmerApprovalStatusResponse(BaseModel):
    background_enabled: bool
    lock_enabled: bool
    worker_running: bool = False
    dry_run: bool
    fetch_limit: int
    valid_id_types: list[str]
    partner_unique_id_prefix: str = ""
    response_status: str
    latest_persisted_run: dict | None = None
    last_run_started_at: str | None = None
    last_run_finished_at: str | None = None
    last_run_status: str | None = None
    last_run_result: FarmerApprovalRunResponse | None = None
    last_error: str | None = None
