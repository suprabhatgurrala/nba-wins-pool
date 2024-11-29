import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router as api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()


app.include_router(api_router, prefix="/api")

SERVE_STATIC_FILES = os.getenv("SERVE_STATIC_FILES")
CORS_ALLOW_ALL = os.getenv("CORS_ALLOW_ALL")

logger.info("SERVE_STATIC_FILES=%s", SERVE_STATIC_FILES)
logger.info("CORS_ALLOW_ALL=%s", CORS_ALLOW_ALL)

if SERVE_STATIC_FILES == "true":
    # This should be done after all routes
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if CORS_ALLOW_ALL == "true":
    app.add_middleware(CORSMiddleware, allow_origins=["*"])
