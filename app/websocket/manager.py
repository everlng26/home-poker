from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

from app.database import SessionLocal
from app.services.errors import DomainError
from app.services.state_service import tournament_state

logger = logging.getLogger(__name__)


class TournamentConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, tournament_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[tournament_id].add(websocket)
        await self.send_snapshot(tournament_id, websocket)

    def disconnect(self, tournament_id: int, websocket: WebSocket) -> None:
        self._connections[tournament_id].discard(websocket)
        if not self._connections[tournament_id]:
            self._connections.pop(tournament_id, None)

    async def send_snapshot(self, tournament_id: int, websocket: WebSocket) -> None:
        try:
            with SessionLocal() as session:
                payload = tournament_state(session, tournament_id)
            await websocket.send_json({
                "protocol_version": 1, "type": "state_snapshot", "tournament_id": tournament_id,
                "event_id": payload["state_version"], "payload": payload,
            })
        except DomainError:
            await websocket.send_json({"protocol_version": 1, "type": "error", "tournament_id": tournament_id, "payload": {"message": "Турнир не найден."}})

    async def broadcast_state(self, tournament_id: int) -> None:
        recipients = list(self._connections.get(tournament_id, set()))
        if not recipients:
            return
        try:
            with SessionLocal() as session:
                payload = tournament_state(session, tournament_id)
        except DomainError:
            return
        message = {
            "protocol_version": 1, "type": "tournament_updated", "tournament_id": tournament_id,
            "event_id": payload["state_version"], "payload": payload,
        }
        for websocket in recipients:
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(tournament_id, websocket)

    def schedule_broadcast(self, tournament_id: int) -> None:
        asyncio.create_task(self.broadcast_state(tournament_id))

