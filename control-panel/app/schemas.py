from __future__ import annotations

from pydantic import BaseModel, Field


class InitDataRequest(BaseModel):
    init_data: str = Field(..., min_length=10)


class CredentialPayload(InitDataRequest):
    render_api_key: str = Field(..., min_length=10)
    api_id: int = Field(..., gt=0)
    api_hash: str = Field(..., min_length=10)
    session_string: str = Field(..., min_length=20)
    mongodb_uri: str | None = None
    cmd_prefix: str = Field(default=".", min_length=1, max_length=3)
    app_base_url: str | None = None


class DeployRequest(InitDataRequest):
    service_name: str | None = None


class ProfileResponse(BaseModel):
    telegram_id: int
    first_name: str = ""
    username: str = ""
    has_credentials: bool
    service_id: str = ""
    service_name: str = ""
    service_url: str = ""
    deploy_status: str = "idle"
