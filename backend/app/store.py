"""Process-lifetime holder for the loaded data.

The data is historical and immutable (decisions made in January 2026), so an
in-memory cache for the life of the process is the simplest correct design:
~25k rows, a few MB. Loading runs in the background so the web server binds its
port immediately (Heroku kills dynos that do not bind within 60 s).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .config import Settings
from .dataset import Dataset, load_dataset
from .service import AnalysisService

logger = logging.getLogger(__name__)


class DataNotReady(Exception):
    pass


class DataStore:
    """Owns the background load and hands out the analysis service once ready."""

    def __init__(self, settings: Settings, loader: Callable[[], Awaitable[Dataset]] | None = None):
        self.settings = settings
        self._loader = loader or (lambda: load_dataset(settings))
        self._task: asyncio.Task | None = None
        self.service: AnalysisService | None = None
        self.error: str | None = None

    @classmethod
    def from_dataset(cls, dataset: Dataset, settings: Settings) -> "DataStore":
        store = cls(settings)
        store.service = AnalysisService(dataset, settings)
        return store

    @property
    def status(self) -> str:
        if self.service is not None:
            return "ready"
        if self._task is not None and not self._task.done():
            return "loading"
        return "error" if self.error else "idle"

    def start(self) -> None:
        """Start loading unless a load is running or has succeeded (a failed load is retried)."""
        if self.service is None and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._load())

    def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _load(self) -> None:
        try:
            self.error = None
            dataset = await self._loader()
            service = AnalysisService(dataset, self.settings)
            # Pre-compute the default views so the first visitor gets an instant page.
            await asyncio.to_thread(service.warm_up)
            self.service = service
            logger.info("Data ready (source=%s)", dataset.source)
        except Exception as exc:
            logger.exception("Data load failed")
            self.error = f"{type(exc).__name__}: {exc}"

    async def get_service(self, timeout_s: float) -> AnalysisService:
        if self.service is not None:
            return self.service
        self.start()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout_s)
        except TimeoutError as exc:
            raise DataNotReady("Data is still loading from Elexon - retry in a few seconds.") from exc
        if self.service is None:
            raise DataNotReady(f"Data could not be loaded: {self.error}")
        return self.service
