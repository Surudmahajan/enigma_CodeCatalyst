"""SYMBIO API entry point."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import jobs
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import RequestContextMiddleware, configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    yield
    jobs.shutdown()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "SYMBIO — turning industrial by-products into industrial resources. "
        "Authenticate with `POST /api/v1/auth/login` and send `Authorization: Bearer <token>`. "
        "Send `X-Organization-Id` to act as a specific organization when a user belongs to several. "
        "All errors use the shape `{\"error\": {\"code\", \"message\", \"details\"?}}`."
    ),
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)

api = APIRouter(prefix=settings.api_prefix)


@api.get("/health", tags=["system"], summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api)
