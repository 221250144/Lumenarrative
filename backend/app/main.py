from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from app.models import SessionLocal, Job, uid
from app.config import settings
from app.api.routes import router
from app.api.generation import router as generation_router
from app.auth import router as auth_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    # Schema is managed by Alembic before startup.
    if settings.queue_mode == "local":
        with SessionLocal() as db:
            pending = db.scalars(
                select(Job).where(Job.status.in_(["running", "queued"]))
            ).all()
            for job in pending:
                job.status = "failed"
                job.error_code = "INTERRUPTED"
                job.error_message = "本地服务上次处理中断，可点击重试恢复"
            db.commit()
    yield


app = FastAPI(title="叙光集 API", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(generation_router)
app.include_router(auth_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uid()
    if (request.url.path.startswith("/api/v1/")
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("X-Requested-With") != "XMLHttpRequest"):
        return error(request, "CSRF_REJECTED", "请从当前页面发起操作", 403)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/v1/"):
        response.headers["Cache-Control"] = "private, no-store"
    return response


def error(request, code, message, status, details=None):
    return JSONResponse(
        {
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request.state, "request_id", uid()),
        },
        status_code=status,
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error(request, f"HTTP_{exc.status_code}", str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(
        request,
        "VALIDATION_ERROR",
        "输入参数不符合要求",
        422,
        [{"location": e["loc"], "message": e["msg"]} for e in exc.errors()],
    )


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return error(request, "INVALID_OPERATION", str(exc), 422)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logging.getLogger("xuguangji").exception(
        "request failed: %s", request.state.request_id
    )
    return error(
        request, "INTERNAL_ERROR", "处理遇到异常，请通过请求编号查看本地服务日志", 500
    )
