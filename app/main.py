"""
NOM Python Prototype — Application entry point.

Run:
    uvicorn app.main:app --reload --port 8001
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.mcp import router as mcp_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("nom-py starting up")
    yield
    logger.info("nom-py shutting down")


app = FastAPI(
    title="nom-py",
    description="Policy-enforcing MCP proxy (Phase 2: core flow)",
    version="0.2.0",
    lifespan=lifespan,
    debug=True,
)

app.include_router(health_router)
app.include_router(mcp_router)