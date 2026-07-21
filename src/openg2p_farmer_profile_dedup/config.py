from functools import lru_cache

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import __version__


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="farmer_dedup_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openapi_title: str = "OpenG2P Farmer Profile Dedup Service"
    openapi_description: str = "Standalone national ID deduplication service for farmer profile data"
    openapi_version: str = __version__

    db_driver: str = Field(default="postgresql+asyncpg")
    db_username: str = Field(default="")
    db_password: str = Field(default="")
    db_hostname: str = Field(default="")
    db_port: int = Field(default=5432)
    db_name: str = Field(default="")
    db_datasource: str | None = None

    service_db_driver: str = Field(default="postgresql+asyncpg")
    service_db_username: str = Field(default="")
    service_db_password: str = Field(default="")
    service_db_hostname: str = Field(default="")
    service_db_port: int = Field(default=5432)
    service_db_name: str = Field(default="")
    service_db_datasource: str | None = None
    service_db_auto_migrate: bool = True

    nidp_get_data_by_id_url: str = "http://localhost:8000/getDataById"
    nidp_caller_id: str = "openg2p"
    nidp_api_version: str = "v1"
    nidp_timeout_seconds: float = 1000.0
    mock_nidp_enabled: bool = False

    include_id_types: str = "UID,FAN,RID"
    response_id_field: str = "fan"
    response_id_type: str = "FAN"
    partner_unique_id_prefix: str = ""
    odoo_filestore_dir: str = Field(default="")
    rerun_invalid_records: bool = Field(default=True)
    required_update_fields: str = (
        "name,given_name,family_name,gender,birthdate,image_1920,"
        "first_name_amh,family_name_amh,gf_name_amh,gf_name_eng"
    )

    chunk_limit: int = 10
    fetch_limit: int = 1000
    interval_seconds: int = 300
    initial_delay_seconds: int = 5
    dry_run: bool = True
    background_enabled: bool = False
    lock_enabled: bool = True
    lock_id: int = 914202607

    approval_background_enabled: bool = False
    approval_interval_seconds: int = 300
    approval_initial_delay_seconds: int = 15
    approval_fetch_limit: int = 1000
    approval_dry_run: bool = True
    approval_lock_enabled: bool = True
    approval_lock_id: int = 914202608
    approval_valid_id_types: str = "UID,FIN,FAN,RID"
    approval_response_status: str = "PROCESSED"
    approval_state: str = "draft"
    approval_write_uid: int | None = None
    approval_require_fan: bool = False
    approval_require_valid_fan: bool = False
    approval_check_global_land_duplicates: bool = False

    log_level: str = "INFO"

    @field_validator("approval_write_uid", mode="before")
    @classmethod
    def empty_string_as_none(cls, value):
        if value == "":
            return None
        return value

    @computed_field
    @property
    def include_id_type_list(self) -> list[str]:
        return [
            value.strip()
            for value in self.include_id_types.split(",")
            if value.strip()
        ]

    @computed_field
    @property
    def required_update_field_list(self) -> list[str]:
        return [
            value.strip()
            for value in self.required_update_fields.split(",")
            if value.strip()
        ]

    @computed_field
    @property
    def approval_valid_id_type_list(self) -> list[str]:
        return [
            value.strip()
            for value in self.approval_valid_id_types.split(",")
            if value.strip()
        ]

    @computed_field
    @property
    def resolved_db_datasource(self) -> str:
        if self.db_datasource:
            return self.db_datasource
        return (
            f"{self.db_driver}://{self.db_username}:{self.db_password}"
            f"@{self.db_hostname}:{self.db_port}/{self.db_name}"
        )

    @computed_field
    @property
    def resolved_service_db_datasource(self) -> str:
        if self.service_db_datasource:
            return self.service_db_datasource
        if self.service_db_name:
            return (
                f"{self.service_db_driver}://{self.service_db_username}:{self.service_db_password}"
                f"@{self.service_db_hostname}:{self.service_db_port}/{self.service_db_name}"
            )
        return self.resolved_db_datasource


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
