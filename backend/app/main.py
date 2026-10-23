"""FastAPI application factory."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import __version__
from .api import router
from .config import Settings, get_settings
from .store import DataStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None, store: DataStore | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or DataStore(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.start()  # background load; the port binds immediately
        yield
        store.stop()

    app = FastAPI(
        title="WindDesk API",
        version=__version__,
        description="GB national wind generation forecasts vs actuals (Elexon BMRS) for day-ahead purchasing.",
        lifespan=lifespan,
    )
    app.state.store = store
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root():
        return {"name": "WindDesk API", "version": __version__, "docs": "/docs", "health": "/api/health"}

    return app


app = create_app()
