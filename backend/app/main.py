import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.api.v1.router import api_router
from app.middleware.security import CSRFMiddleware, SecurityHeadersMiddleware
from app.middleware.tenant import TenantMiddleware
from app.services.token_store import close_redis, get_redis

if settings.LOG_FORMAT == "json":
    import json as _json

    class _JsonFormatter(logging.Formatter):
        def format(self, record):
            return _json.dumps({
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                **({"exc": self.formatException(record.exc_info)} if record.exc_info else {}),
            })

    _handler = logging.StreamHandler()
    _handler.setFormatter(_JsonFormatter())
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        handlers=[_handler],
    )
else:
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
logger = logging.getLogger(__name__)


async def _scheduler_loop():
    """Background loop that runs every 60 seconds: due scheduled exports plus
    the JobRun-ledgered daily/yearly jobs (leave carry-over, expiry, cash
    conversion). Each job is idempotent, so running the loop on every process
    is safe."""
    from app.services.job_service import JobService
    from app.services.scheduled_export_service import ScheduledExportService

    while True:
        await asyncio.sleep(60)
        try:
            async with AsyncSessionLocal() as db:
                await ScheduledExportService.check_and_run_due(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled export check failed")

        try:
            await JobService.run_due_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled jobs check failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s (environment=%s, debug=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
        settings.DEBUG,
    )
    try:
        from app.services.smtp_bootstrap import bootstrap_smtp_from_env
        from app.services.email_service import EmailService
        async with AsyncSessionLocal() as db:
            await bootstrap_smtp_from_env(db)
            # Warn loudly, once, if email cannot be sent. Self-hosters routinely
            # start with no SMTP; without this the failure is invisible (sends are
            # best-effort and drop silently), so invited users never get their
            # activation link and password resets go nowhere. Uses the same config
            # source the send path checks, so the warning can't disagree with it.
            if await EmailService._get_smtp_config(db) is None:
                logger.warning(
                    "Email (SMTP) is not configured — invitations, password resets "
                    "and notification emails will NOT be sent. Configure SMTP via the "
                    "SMTP_* env vars or in-app under Settings -> Email, or add users "
                    "with the 'Set Password Manually' option instead of an emailed invite."
                )
    except Exception:
        logger.exception("SMTP env bootstrap failed")

    task = asyncio.create_task(_scheduler_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await close_redis()
    await engine.dispose()


# Interactive docs describe every endpoint and schema. Off by default; opt in
# explicitly via EXPOSE_API_DOCS for non-production environments.
_docs_enabled = settings.EXPOSE_API_DOCS and not settings.is_production

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# Middleware runs in reverse registration order, so the last one added is the
# outermost. Security headers must wrap everything, including error responses.
app.add_middleware(TenantMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    CORSMiddleware,
    # Never wildcard: allow_credentials=True with a reflected origin would let
    # any site issue authenticated cross-origin requests with our cookies.
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", settings.CSRF_HEADER_NAME],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Always log the full traceback server-side; never send it to the client.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    detail = str(exc) if settings.DEBUG else "Internal server error"
    return JSONResponse(status_code=500, content={"detail": detail})


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/health")
async def health_check():
    """Liveness + dependency readiness, for container healthchecks and LBs."""
    checks = {"database": "unknown", "redis": "unknown"}

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("Health check: database unreachable")
        checks["database"] = "error"

    try:
        client = get_redis()
        if client is None:
            checks["redis"] = "error"
        else:
            await client.ping()
            checks["redis"] = "ok"
    except Exception:
        logger.exception("Health check: redis unreachable")
        checks["redis"] = "error"

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "healthy" if healthy else "degraded", "checks": checks},
    )


app.include_router(api_router, prefix="/api/v1")
