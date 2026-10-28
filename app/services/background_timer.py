from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.database import SessionLocal
from app.models.enums import TimerStatus
from app.models.tournament import Tournament
from app.services.timer_service import TimerService, tournament_locks
from sqlalchemy import select

logger = logging.getLogger(__name__)


class BackgroundTimer:
    def __init__(self, on_change: Callable[[int], None] | None = None) -> None:
        self._task: asyncio.Task[None] | None = None
        self._on_change = on_change

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="poker-timer")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                changed_ids = await asyncio.to_thread(self._tick)
                if self._on_change:
                    for tournament_id in changed_ids:
                        self._on_change(tournament_id)
            except Exception:
                logger.exception("Ошибка фонового таймера")
            await asyncio.sleep(1)

    @staticmethod
    def _tick() -> list[int]:
        with SessionLocal() as session:
            ids = list(session.scalars(select(Tournament.id).where(Tournament.timer_status == TimerStatus.RUNNING)))
        changed: list[int] = []
        for tournament_id in ids:
            with tournament_locks.lock_for(tournament_id), SessionLocal() as session:
                with session.begin():
                    if TimerService.reconcile(session, tournament_id):
                        changed.append(tournament_id)
        return changed

