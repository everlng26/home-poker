"""Точка входа FastAPI-приложения."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import PROJECT_DIR, get_settings
from app.database import check_database_connection, ensure_local_directories
from app.routers.pages import router as pages_router, templates
from app.routers.api import router as api_router
from app.security import load_or_create_app_secret
from app.services.background_timer import BackgroundTimer
from app.websocket import TournamentConnectionManager

logging.basicConfig(level=get_settings().log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    active_settings = get_settings()
    ensure_local_directories(active_settings)
    app_secret = load_or_create_app_secret(active_settings.app_secret_path)
    app.state.app_secret = app_secret
    check_database_connection()
    app.state.ws_manager = TournamentConnectionManager()
    timer = BackgroundTimer(app.state.ws_manager.schedule_broadcast)
    await timer.start()
    logger.info("Приложение запущено")
    try:
        yield
    finally:
        await timer.stop()
        logger.info("Приложение остановлено")


app = FastAPI(title="Домашний покер", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(PROJECT_DIR / "app" / "static")), name="static")
app.include_router(pages_router)
app.include_router(api_router)


@app.websocket("/ws/tournaments/{tournament_id}")
async def tournament_websocket(websocket: WebSocket, tournament_id: int) -> None:
    manager: TournamentConnectionManager = app.state.ws_manager
    await manager.connect(tournament_id, websocket)
    try:
        while True:
            await websocket.receive_text()
            await manager.send_snapshot(tournament_id, websocket)
    except WebSocketDisconnect:
        manager.disconnect(tournament_id, websocket)


@app.get("/health")
def health() -> dict[str, str]:
    check_database_connection()
    return {"status": "ok"}


@app.exception_handler(404)
async def not_found(request: Request, _: Exception) -> HTMLResponse | JSONResponse:
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={
                "detail": {
                    "code": "route_not_found",
                    "message": "API endpoint не найден. Перезапустите Home Poker после обновления.",
                }
            },
        )
    return templates.TemplateResponse(request, "errors/404.html", {"page_title": "Не найдено"}, status_code=404)


@app.exception_handler(500)
async def internal_error(request: Request, _: Exception) -> HTMLResponse:
    logger.exception("Необработанная ошибка на %s", request.url.path)
    return templates.TemplateResponse(request, "errors/500.html", {"page_title": "Ошибка"}, status_code=500)


if __name__ == "__main__":
    # Этот режим удобен разработчику. Для реального турнира используйте start.command:
    # он также предотвращает сон компьютера и открывает браузер.
    import uvicorn

    logger.warning("Прямой запуск предназначен для проверки. Для турнира запускайте start.command.")
    uvicorn.run(app, host="0.0.0.0", port=8000)
