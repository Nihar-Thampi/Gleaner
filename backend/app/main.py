import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db import Base, engine
from app.routers import activity, ai, auth, dashboard, domains, integrations, public, public_api, runs, scrapers, team
from app.worker import worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()

# Creates any missing tables. Fine for this project; a production deployment would run
# versioned migrations (e.g. Alembic) instead.
Base.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.run_worker:
        worker.start_in_thread()
    yield
    worker.stop()


app = FastAPI(title=f"{settings.app_name} API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.exception_handler(RequestValidationError)
async def readable_validation_errors(_request: Request, exc: RequestValidationError):
    """Pydantic messages, without the 'Value error, ' prefix and with the field path."""
    errors = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"] if p not in ("body",))
        msg = str(e["msg"]).removeprefix("Value error, ")
        errors.append({"loc": e["loc"], "msg": f"{loc}: {msg}" if loc and not msg.startswith(loc) else msg})
    return JSONResponse(status_code=422, content={"detail": errors})


for module in (auth, team, domains, scrapers, runs, activity, integrations, ai, dashboard, public_api):
    app.include_router(module.router, prefix="/api")
app.include_router(public.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
