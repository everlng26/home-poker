"""Безопасное обнаружение LAN-адресов macOS для QR-кодов."""

from __future__ import annotations

import ipaddress
import re
import subprocess
from dataclasses import dataclass


EXCLUDED_INTERFACE_PREFIXES = ("lo", "utun", "awdl", "llw", "bridge", "vmnet", "gif", "stf", "anpi", "ap")


@dataclass(frozen=True, slots=True)
class LanAddress:
    interface: str
    address: str

    def url(self, port: int = 8000) -> str:
        return f"http://{self.address}:{port}"


def find_lan_addresses() -> list[LanAddress]:
    completed = subprocess.run(["/sbin/ifconfig"], capture_output=True, text=True, check=False)
    blocks = re.split(r"(?m)^(?=\S+:)", completed.stdout)
    found: set[LanAddress] = set()
    for block in blocks:
        header = block.splitlines()[0] if block.splitlines() else ""
        interface = header.split(":", 1)[0]
        if not interface or interface.startswith(EXCLUDED_INTERFACE_PREFIXES) or "status: active" not in block:
            continue
        for raw_address in re.findall(r"(?m)^\s*inet (\d+\.\d+\.\d+\.\d+)\s", block):
            candidate = ipaddress.ip_address(raw_address)
            if candidate.is_private and not candidate.is_loopback and not candidate.is_link_local:
                found.add(LanAddress(interface=interface, address=str(candidate)))
    return sorted(found, key=lambda item: (item.interface, item.address))


def local_hostname_url(port: int = 8000) -> str | None:
    completed = subprocess.run(
        ["/usr/sbin/scutil", "--get", "LocalHostName"], capture_output=True, text=True, check=False
    )
    hostname = completed.stdout.strip()
    return f"http://{hostname}.local:{port}" if completed.returncode == 0 and hostname else None

