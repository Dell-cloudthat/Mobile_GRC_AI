"""
SecurityOS FastAPI Application

Standalone server for the SecurityOS product.
Runs independently of the legacy compliance platform (main.py).

Start:
    uvicorn backend.securityos_main:app --port 8001 --reload

Environment variables:
    DATABASE_URL        — PostgreSQL URL (falls back to in-memory if not set)
    CORS_ORIGINS        — comma-separated allowed origins (required in prod)
    OPENAI_API_KEY      — optional, enables real LLM copilot responses
    ENV                 — "dev" | "test" | "prod" (default: "dev")
    AUTH_ISSUER         — OIDC issuer URL
    AUTH_AUDIENCE       — JWT audience
    AUTH_JWKS_URL       — JWKS endpoint (optional; discovered from AUTH_ISSUER)
    AUTH_DEV_PRIVATE_KEY_PATH — local RSA key for dev/test tokens (never use in prod)
"""

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.api import router as securityos_router
from backend.api.tiers import router as tiers_router
from backend.api.msp import router as msp_router
from backend.api.attestations import router as attestations_router
from backend.api.members import router as members_router
from backend.api.findings import router as findings_router
from backend.api.orgs import router as orgs_router
from backend.auth.jwt import validate_prod_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("securityos")

ENV: str = os.environ.get("ENV", "prod").lower()

# ── Guard: fail fast in prod if dev auth key is present ───────────────────────
# The jwt module also does this check, but we repeat it here for a clear startup log.
if ENV == "prod" and os.environ.get("AUTH_DEV_PRIVATE_KEY_PATH"):
    raise RuntimeError(
        "FATAL: AUTH_DEV_PRIVATE_KEY_PATH must not be set when ENV=prod. "
        "Remove the env var or correct the ENV value."
    )

_docs_url = "/docs" if ENV != "prod" else None
_redoc_url = "/redoc" if ENV != "prod" else None

app = FastAPI(
    title="SecurityOS API",
    description="Security Readiness Platform for Small Businesses",
    version="0.3.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

# ── CORS ──────────────────────────────────────────────────────────────────────

_raw_origins = os.environ.get("CORS_ORIGINS", "")
if _raw_origins:
    allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
else:
    if ENV == "prod":
        logger.warning(
            "CORS_ORIGINS is not set in prod — CORS will be restricted to no origins. "
            "Set CORS_ORIGINS to your frontend domain."
        )
        allowed_origins = []
    else:
        # Development defaults
        allowed_origins = [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]

# Tighten allowed methods and headers in prod; keep permissive in dev for DX
if ENV == "prod":
    _allow_methods = ["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"]
    _allow_headers = ["Authorization", "Content-Type", "Accept"]
else:
    _allow_methods = ["*"]
    _allow_headers = ["*"]

# Optional regex for preview deployments, e.g. Vercel preview URLs:
#   CORS_ORIGIN_REGEX=^https://mobile-grc-[a-z0-9-]+-orculx\.vercel\.app$
_origin_regex = os.environ.get("CORS_ORIGIN_REGEX") or None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=False,  # bearer tokens, not cookies
    allow_methods=_allow_methods,
    allow_headers=_allow_headers,
)

# ── Routes ─────────────────────────────────────────────────────────────────────

app.include_router(securityos_router)
app.include_router(tiers_router)
app.include_router(msp_router)
app.include_router(attestations_router)
app.include_router(members_router)
app.include_router(findings_router)
app.include_router(orgs_router)

if ENV == "dev" and os.environ.get("AUTH_DEV_PRIVATE_KEY_PATH"):
    from backend.api.dev import router as dev_router

    app.include_router(dev_router)
    logger.warning("Dev sign-in endpoint enabled (/api/v1/securityos/dev/token). Never use ENV=dev in production.")


@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "service": "SecurityOS API",
        "version": "0.3.0",
        "env": ENV,
    }


@app.get("/health/ready", tags=["Health"])
def ready():
    """Readiness probe: verifies the database is reachable and fully migrated."""
    from fastapi.responses import JSONResponse
    from backend import db

    if not db.is_enabled():
        return {"status": "ok", "database": "in-memory"}
    try:
        from backend.db.migrate import pending
        if pending():
            return JSONResponse(status_code=503, content={"status": "error", "database": "migrations pending"})
    except Exception:
        logger.exception("Readiness check failed")
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
    return {"status": "ok", "database": "postgresql"}


def validate_runtime_config(env: str) -> None:
    """Refuse to serve production traffic without durable storage."""
    from backend import db

    if env == "prod" and not db.is_enabled():
        raise RuntimeError(
            "DATABASE_URL must be set when ENV=prod. In-memory storage loses all "
            "data on restart and is only allowed for ENV=dev or ENV=test."
        )


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "SecurityOS",
        "docs": "/docs" if ENV != "prod" else "disabled in prod",
        "health": "/health",
        "api": "/api/v1/securityos",
    }


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    # Fail fast if required prod config is missing
    validate_prod_config()
    validate_runtime_config(ENV)

    logger.info("SecurityOS API v0.3.0 starting (ENV=%s)", ENV)
    logger.info("  Routes: /api/v1/securityos · /api/v1/securityos/tiers · /api/v1/securityos/msp")

    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        logger.info("  Database: PostgreSQL (persistent)")
    else:
        logger.warning(
            "  DATABASE_URL not set — using in-memory storage. "
            "All data lost on restart."
        )

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        logger.info("  OpenAI: configured — real LLM copilot enabled")
    else:
        logger.info("  OpenAI: not configured — copilot uses rule-based responses")

    auth_issuer = os.environ.get("AUTH_ISSUER", "")
    auth_dev_key = os.environ.get("AUTH_DEV_PRIVATE_KEY_PATH", "")
    if auth_issuer:
        logger.info("  Auth: OIDC (issuer=%s)", auth_issuer)
    elif auth_dev_key:
        logger.info("  Auth: dev mode (local RSA key)")
    else:
        logger.warning(
            "  Auth: NO AUTH CONFIGURED — all protected routes will return 401. "
            "Set AUTH_ISSUER + AUTH_AUDIENCE or AUTH_DEV_PRIVATE_KEY_PATH for dev."
        )
