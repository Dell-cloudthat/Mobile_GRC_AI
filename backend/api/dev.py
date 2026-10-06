"""
Local-development sign-in — ENV=dev ONLY.

POST /api/v1/securityos/dev/token issues a short-lived token signed with the
local dev key, so the web app can be used without an identity provider.

This router is only mounted when ENV=dev AND AUTH_DEV_PRIVATE_KEY_PATH is set
(see securityos_main.py).  ENV=prod refuses to start with a dev key at all, so
this endpoint cannot exist in production.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.jwt import sign_dev_token

router = APIRouter(prefix="/api/v1/securityos/dev", tags=["Dev only"])


class DevTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._@-]+$")
    name: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=320)
    msp_id: Optional[str] = Field(None, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")


@router.post("/token", summary="Issue a local dev token (ENV=dev only)")
def issue_dev_token(payload: DevTokenRequest):
    claims = {
        "sub": payload.user_id,
        "name": payload.name or payload.user_id,
        "email": payload.email or f"{payload.user_id}@dev.local",
    }
    if payload.msp_id:
        claims["msp_id"] = payload.msp_id
    return {"access_token": sign_dev_token(claims, expires_in=8 * 3600), "token_type": "Bearer",
            "expires_in": 8 * 3600}
