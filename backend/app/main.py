import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import inspect

from .api import router
from .db import get_engine
from .keitaro import KeitaroError
from .services import AppError

log = logging.getLogger("keitaro_tools")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Подсказка, если забыли применить миграции
    try:
        if not inspect(get_engine()).has_table("campaigns"):
            log.warning("The database has no tables. Run migrations:  alembic upgrade head")
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not check the database: %s", exc)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Keitaro tools", version="1.0.0", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(AppError)
    async def _app_error(_req: Request, exc: AppError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(KeitaroError)
    async def _keitaro_error(_req: Request, exc: KeitaroError):
        return JSONResponse({"detail": exc.message, "keitaro_status": exc.status}, status_code=502)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError):
        parts = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
            parts.append(f"{field}: {err.get('msg')}" if field else str(err.get("msg")))
        return JSONResponse({"detail": "; ".join(parts) or "Invalid data"}, status_code=422)

    return app


app = create_app()
