from contextlib import asynccontextmanager

import app.mcp.tools  # noqa: F401 — registers all MCP tools before FastAPI starts
from app.mcp.server import mcp

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings

from app.api.routes.auth import router as auth_router
from app.api.routes.us import router as us_router
from app.api.routes.assistant import router as assistant_router
from app.api.routes.screener import router as screener_router
from app.api.routes.watchlist import router as watchlist_router
from app.core.config import get_settings
from app.core.orm import create_orm_tables, dispose_engine
from app.core.tracking import RequestTrackingMiddleware

settings = get_settings()

# Build the MCP Streamable-HTTP ASGI app once at import time so that
# `mcp.session_manager` is available to the lifespan below. Stateless + JSON
# responses keep it proxy- and horizontal-scale friendly; DNS-rebinding
# protection is disabled because the public Host varies behind the platform proxy.
_mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_orm_tables()
    async with mcp.session_manager.run():
        yield
    await dispose_engine()


app = FastAPI(
    title=settings.app_name,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestTrackingMiddleware)


@app.get("/")
def read_root():
    return {"message": "Prismalis API is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api")
app.include_router(us_router, prefix="/api")
app.include_router(watchlist_router, prefix="/api")
app.include_router(assistant_router, prefix="/api")
app.include_router(screener_router, prefix="/api")

# Serve the MCP endpoint at exactly /mcp (no sub-mount, so no trailing-slash redirect).
for _mcp_route in _mcp_app.routes:
    app.router.routes.append(_mcp_route)
