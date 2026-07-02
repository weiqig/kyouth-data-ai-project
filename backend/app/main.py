from __future__ import annotations

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.ai import router as ai_router
from .api.dashboard import router as dashboard_router
from .api.documents import router as documents_router
from .api.extractions import router as extractions_router
from .api.jobs import router as jobs_router
from .api.system import router as system_router
from .api.templates import router as templates_router
from .services.startup_service import seed_startup_data

seed_startup_data()

app = FastAPI(title="Audit-Ready AI Document Processing Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(templates_router)
app.include_router(documents_router)
app.include_router(extractions_router)
app.include_router(jobs_router)
app.include_router(ai_router)
app.include_router(dashboard_router)
