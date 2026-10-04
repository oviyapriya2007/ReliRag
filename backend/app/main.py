from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import models  # noqa: F401  (registers tables on Base.metadata)
from app.config import settings
from app.db import Base, engine
from app.routers import analytics, compare, documents, evaluations, query
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


app.include_router(documents.router)
app.include_router(query.router)
app.include_router(compare.router)
app.include_router(evaluations.router)
app.include_router(analytics.router)
