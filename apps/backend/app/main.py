"""SYMBIO API entry point."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models as _models  # noqa: F401  (registers every ORM model)
from app.admin.router import router as admin_router
from app.ai.router import router as ai_router
from app.analytics.router import router as analytics_router
from app.auth.router import router as auth_router
from app.connections.router import router as connections_router
from app.core import jobs
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.documents.router import router as documents_router
from app.exchanges.router import router as exchanges_router
from app.impact import handlers as impact_handlers
from app.materials.router import router as materials_router
from app.matching import handlers as matching_handlers
from app.matching.router import router as matching_router
from app.messaging.router import router as messaging_router
from app.notifications import handlers as notification_handlers
from app.notifications.router import router as notifications_router
from app.pathways.router import router as pathways_router
from app.organizations.router import facilities_router
from app.organizations.router import router as organizations_router
from app.requirements.router import router as requirements_router
from app.resources.router import router as resources_router
from app.users.router import router as users_router

settings = get_settings()
matching_handlers.register()
notification_handlers.register()
impact_handlers.register()


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


for router in (auth_router, users_router, organizations_router, facilities_router, materials_router,
               resources_router, requirements_router, matching_router, connections_router, messaging_router,
               documents_router, exchanges_router, notifications_router, analytics_router, admin_router,
               ai_router, pathways_router):
    api.include_router(router)

app.include_router(api)
