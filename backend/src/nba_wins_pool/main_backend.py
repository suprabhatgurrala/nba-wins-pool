import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router as api_router

app = FastAPI()


app.include_router(api_router, prefix="/api")

if os.getenv("SERVE_STATIC_FILES") == "true":
    # This should be done after all routes
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

if os.getenv("CORS_ALLOW_ALL") == "true":
    app.add_middleware(CORSMiddleware, allow_origins=["*"])
