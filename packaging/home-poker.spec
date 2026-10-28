# -*- mode: python -*-
# Сборка «Домашний покер.app» PyInstaller-ом: ./build_app.command делает всё сам.
#   pyinstaller packaging/home-poker.spec --noconfirm --clean
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from app import __version__  # noqa: E402

ICON = ROOT / "packaging" / "icons" / "AppIcon.icns"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "app" / "static"), "app/static"),
        (str(ROOT / "app" / "templates"), "app/templates"),
        # Миграции читаются Alembic с диска; папка названа иначе, чтобы не совпадать с пакетом alembic.
        (str(ROOT / "alembic"), "migrations"),
        (str(ROOT / "desktop" / "window"), "desktop/window"),
    ],
    # uvicorn и alembic подключают части себя по имени, анализатор их не видит.
    hiddenimports=collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("alembic"),
    excludes=["tkinter", "pytest", "ruff", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HomePoker",
    console=False,
    icon=str(ICON),
)
coll = COLLECT(exe, a.binaries, a.datas, name="HomePoker")
app = BUNDLE(
    coll,
    name="Домашний покер.app",
    icon=str(ICON),
    bundle_identifier="io.github.everlng26.home-poker",
    version=__version__,
    info_plist={
        "CFBundleName": "Домашний покер",
        "CFBundleDisplayName": "Домашний покер",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSApplicationCategoryType": "public.app-category.games",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "NSLocalNetworkUsageDescription": "Телефон в той же Wi-Fi открывает админку турнира.",
    },
)
