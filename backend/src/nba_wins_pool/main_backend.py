import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import app_router
from .services.scheduler_service import get_scheduler
from .utils.error import detailed_error_handler
from .utils.spa_static_files import SinglePageApplication

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle events."""
    # Startup
    logger.info("Starting up application...")
    scheduler = get_scheduler()
    await scheduler.start()
    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    await scheduler.shutdown()
    logger.info("Application shutdown complete")


app = FastAPI(lifespan=lifespan)
app.include_router(app_router)

SERVE_STATIC_FILES = os.getenv("SERVE_STATIC_FILES")
CORS_ALLOW_ALL = os.getenv("CORS_ALLOW_ALL")
SERVE_DETAILED_ERRORS = os.getenv("SERVE_DETAILED_ERRORS")

logger.info("SERVE_STATIC_FILES=%s", SERVE_STATIC_FILES)
logger.info("CORS_ALLOW_ALL=%s", CORS_ALLOW_ALL)
logger.info("SERVE_DETAILED_ERRORS=%s", SERVE_DETAILED_ERRORS)

if SERVE_STATIC_FILES == "true":
    # This should be done after all routes
    app.mount("/", SinglePageApplication(directory="static"), name="static")

if CORS_ALLOW_ALL == "true":
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if SERVE_DETAILED_ERRORS == "true":
    app.add_exception_handler(Exception, detailed_error_handler)
