"""Vendor Onboarding & Risk Orchestrator - Main Application"""
import asyncio
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.database import engine, Base
from app.api import router
from app.utils.logging import setup_logging, get_logger

logger = get_logger(__name__)

# Postgres runs in Docker, so it is routinely still booting at the moment the
# backend starts: after `docker compose up`, after a Docker Desktop restart,
# or when uvicorn's reloader relaunches the app because a file changed.
DB_STARTUP_ATTEMPTS = 15
DB_STARTUP_DELAY_SECONDS = 2.0


async def initialise_database(
    attempts: int = DB_STARTUP_ATTEMPTS,
    delay: float = DB_STARTUP_DELAY_SECONDS,
) -> None:
    """Create the tables, waiting for Postgres to become reachable.

    One failed connect used to abort startup for good -- uvicorn printed
    "Application startup failed. Exiting." and the window closed, which looks
    exactly like "the app is broken" when the real cause is only that the
    database container was not up yet. Retry instead, and say so in the log.
    """
    last_error: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return
        except Exception as exc:  # noqa: BLE001 - any driver error means "not ready yet"
            last_error = exc
            logger.warning(
                "database_not_ready",
                extra={
                    "attempt": attempt,
                    "of_attempts": attempts,
                    "retry_in_seconds": delay,
                    "error": str(exc)[:200],
                },
            )
            await asyncio.sleep(delay)

    raise RuntimeError(
        f"Database unreachable after {attempts} attempts over "
        f"{attempts * delay:.0f}s. Is the Postgres container running? "
        f"Last error: {last_error}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    setup_logging()

    # Create database tables (waits for Postgres if it is still starting)
    await initialise_database()

    yield

    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="Vendor Onboarding & Risk Orchestrator",
    description="AI-powered vendor onboarding, document processing, and risk management system",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "error": str(exc),
            "timestamp": datetime.utcnow().isoformat()
        }
    )


# Health check
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "vendor-onboarding-api",
        "timestamp": datetime.utcnow().isoformat()
    }


# Include API routes
app.include_router(router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)