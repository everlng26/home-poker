"""Выводит LAN-адреса так же, как стартовая страница приложения."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app.services.network_service import find_lan_addresses, local_hostname_url  # noqa: E402


if __name__ == "__main__":
    for item in find_lan_addresses():
        print(f"{item.interface}: {item.url()}")
    hostname_url = local_hostname_url()
    if hostname_url:
        print(f"mDNS: {hostname_url}")
