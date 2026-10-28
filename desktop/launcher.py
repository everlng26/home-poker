"""«Домашний покер» как приложение macOS: сервер турнира и маленькое окно управления.

Окно только сообщает, что сервер работает, и открывает турнир в браузере: табло
надёжнее всего работает в обычном Safari или Chrome (полный экран, звук, QR-коды).
Закрыли окно — сервер остановился, и Mac снова может засыпать. Бизнес-правил здесь
нет: это тот же сервер, что запускает start.command.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

APP_NAME = "Домашний покер"
PORT = 8000
FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
WINDOW_DIR = BUNDLE_DIR / "desktop" / "window"
BACKGROUND = "#0f2f22"

CLOSE_QUESTION = (
    "Остановить турнирный сервер? Табло и админка перестанут обновляться, "
    "пока вы снова не откроете приложение. Таймер и игроки сохранятся."
)

log = logging.getLogger("home_poker.desktop")


def default_data_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / APP_NAME


def configure_environment(data_dir: Path) -> None:
    """Вызывается до импорта app.*: база, ключ и резервные копии живут вне приложения."""
    os.environ.setdefault("POKER_DATA_DIR", str(data_dir))
    os.environ.setdefault("POKER_BACKUPS_DIR", str(data_dir / "backups"))


def migrations_dir() -> Path:
    # В собранном приложении миграции лежат в «migrations», чтобы папка не совпадала с пакетом alembic.
    return BUNDLE_DIR / ("migrations" if FROZEN else "alembic")


def setup_logging(data_dir: Path, to_console: bool) -> None:
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [RotatingFileHandler(logs / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")]
    if to_console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def port_is_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def server_answers(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            return response.status == 200
    except (URLError, OSError):
        return False


def has_active_tournament(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/v1/tournaments", timeout=1) as response:
            tournaments = json.load(response)
    except (URLError, OSError, ValueError):
        return False
    return any(item.get("status") in {"running", "paused"} for item in tournaments)


def run_migrations() -> None:
    """То же, что `alembic upgrade head` в start.command, но без alembic.ini и консоли."""
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(migrations_dir()))
    command.upgrade(config, "head")


def keep_awake() -> subprocess.Popen[bytes] | None:
    """Как в start.command: caffeinate держит Mac бодрым, пока жив процесс приложения."""
    try:
        return subprocess.Popen(["/usr/bin/caffeinate", "-dims", "-w", str(os.getpid())])
    except OSError:
        log.warning("caffeinate недоступен: Mac может уснуть во время турнира")
        return None


class TournamentServer:
    """uvicorn в отдельном потоке: главный поток нужен окну."""

    def __init__(self, port: int) -> None:
        import uvicorn
        from fastapi.staticfiles import StaticFiles

        from app.main import app

        # Страница окна управления подключается только в приложении, у start.command её нет.
        app.mount("/desktop", StaticFiles(directory=str(WINDOW_DIR), html=True), name="desktop")
        self.server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_config=None))
        self.thread = threading.Thread(target=self.server.run, name="uvicorn", daemon=True)

    def start(self, timeout: float = 30) -> bool:
        self.thread.start()
        waited = 0.0
        while waited < timeout and self.thread.is_alive() and not self.server.started:
            threading.Event().wait(0.1)
            waited += 0.1
        return self.server.started

    def stop(self) -> None:
        if not self.thread.is_alive():
            return
        self.server.should_exit = True
        self.thread.join(timeout=10)
        log.info("%s остановлен", APP_NAME)


_quit_observer = None


def stop_on_quit(stop: Callable[[], None]) -> None:
    """⌘Q завершает процесс сразу после проверки окон, минуя код после webview.start().

    Уведомление о выходе приходит раньше: в нём сервер успевает штатно закрыть базу и таймер.
    """
    global _quit_observer
    from AppKit import NSApplicationWillTerminateNotification
    from Foundation import NSNotificationCenter, NSObject

    class QuitObserver(NSObject):
        def applicationWillTerminate_(self, _notification: object) -> None:
            stop()

    _quit_observer = QuitObserver.alloc().init()
    NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        _quit_observer, "applicationWillTerminate:", NSApplicationWillTerminateNotification, None
    )


class WindowApi:
    """Методы, которые страница окна вызывает через window.pywebview.api."""

    def __init__(self, port: int, data_dir: Path) -> None:
        self._port = port
        self._data_dir = data_dir

    def open_in_browser(self, path: str = "/") -> None:
        webbrowser.open(f"http://localhost:{self._port}{path if path.startswith('/') else '/'}")

    def open_data_folder(self) -> None:
        subprocess.run(["/usr/bin/open", str(self._data_dir)], check=False)

    def data_folder(self) -> str:
        return str(self._data_dir).replace(str(Path.home()), "~", 1)


def message_page(title: str, text: str) -> str:
    return (
        "<!doctype html><meta charset='utf-8'><body style=\"margin:0;padding:32px;background:#0f2f22;color:#eef2ea;"
        "font:16px/1.5 -apple-system,sans-serif\"><h1 style='font-size:22px;margin:0 0 12px'>"
        f"{title}</h1><p style='margin:0;color:#bdcbc0'>{text}</p></body>"
    )


def show_message(title: str, text: str) -> None:
    import webview

    webview.create_window(APP_NAME, html=message_page(title, text), width=460, height=260, background_color=BACKGROUND)
    webview.start()


def wait_for_signal() -> None:
    stop = threading.Event()
    for handled in (signal.SIGINT, signal.SIGTERM):
        signal.signal(handled, lambda *_: stop.set())
    while not stop.wait(1):
        pass


def run_window(port: int, data_dir: Path, on_quit: Callable[[], None]) -> None:
    import webview

    window = webview.create_window(
        APP_NAME,
        f"http://127.0.0.1:{port}/desktop/",
        js_api=WindowApi(port, data_dir),
        width=440,
        height=580,
        min_size=(380, 520),
        background_color=BACKGROUND,
    )

    def on_closing() -> None:
        # Спрашиваем только когда турнир идёт или на паузе: подготовленные и завершённые не страдают.
        window.confirm_close = has_active_tournament(port)

    window.events.closing += on_closing
    stop_on_quit(on_quit)
    localization = {"global.quitConfirmation": CLOSE_QUESTION, "global.quit": "Остановить", "global.cancel": "Отмена"}
    webview.start(localization=localization)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="home-poker", description=f"{APP_NAME}: сервер турнира с окном управления")
    parser.add_argument("--headless", action="store_true", help="только сервер, без окна: для проверки сборки")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер после запуска")
    parser.add_argument("--port", type=int, default=PORT, help=f"порт сервера (по умолчанию {PORT})")
    parser.add_argument("--data-dir", type=Path, help="папка с базой и резервными копиями")
    args = parser.parse_args(argv)

    data_dir = args.data_dir or Path(os.environ.get("POKER_DATA_DIR") or default_data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    configure_environment(data_dir)
    setup_logging(data_dir, to_console=args.headless)
    local_url = f"http://localhost:{args.port}/"

    if port_is_busy(args.port):
        if server_answers(args.port):
            # Сервер уже работает (второе окно приложения или start.command): просто показываем турнир.
            log.info("сервер уже запущен на порту %s", args.port)
            if not args.no_browser:
                webbrowser.open(local_url)
            return 0
        log.error("порт %s занят другой программой", args.port)
        if not args.headless:
            show_message("Порт занят", f"Порт {args.port} занят другой программой. Закройте её и откройте приложение снова.")
        return 1

    try:
        from app.database import create_backup

        backup = create_backup()
        if backup:
            log.info("резервная копия: %s", backup)
        run_migrations()
        server = TournamentServer(args.port)
        started = server.start()
    except Exception:
        log.exception("сервер не запустился")
        started = False
    if not started:
        if not args.headless:
            show_message("Не удалось запустить", f"Подробности в журнале: {data_dir / 'logs' / 'app.log'}")
        return 1

    keep_awake()
    log.info("%s запущен: %s, данные в %s", APP_NAME, local_url, data_dir)
    if not args.no_browser:
        webbrowser.open(local_url)
    try:
        if args.headless:
            print(local_url, flush=True)
            wait_for_signal()
        else:
            run_window(args.port, data_dir, on_quit=server.stop)
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
