from __future__ import annotations
import asyncio
import json
import socket
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "smart-home"
_GARAGES_FILE = _CONFIG_DIR / "garages.json"


def load_config() -> list[dict]:
    if _GARAGES_FILE.exists():
        try:
            with open(_GARAGES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def save_config(garages: list[dict]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_GARAGES_FILE, "w") as f:
        json.dump(garages, f, indent=2)


def local_subnet() -> str:
    """Return the /24 subnet of the primary outbound interface, e.g. '192.168.1'."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ".".join(ip.split(".")[:3])


async def _probe(client, ip: str) -> dict | None:
    """Return Shelly device info dict if ip is a Shelly, else None."""
    try:
        r = await client.get(f"http://{ip}/shelly", timeout=1.5)
        if r.status_code == 200:
            data = r.json()
            if "gen" in data or "mac" in data:
                data["ip"] = ip
                return data
    except Exception:
        pass
    return None


async def _scan(subnet: str) -> list[dict]:
    import httpx
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[
            _probe(client, f"{subnet}.{i}") for i in range(1, 255)
        ])
    return [r for r in results if r is not None]


def discover(subnet: str | None = None) -> list[dict]:
    """Scan the local /24 subnet and return info dicts for every Shelly found."""
    if subnet is None:
        subnet = local_subnet()
    return asyncio.run(_scan(subnet))


def get_status(ip: str) -> dict:
    """Return Shelly Gen3 Switch.GetStatus dict, e.g. {'output': False, 'apower': 0.0, ...}"""
    import httpx
    resp = httpx.get(f"http://{ip}/rpc/Switch.GetStatus?id=0", timeout=5)
    resp.raise_for_status()
    return resp.json()


def trigger(ip: str, pulse_seconds: float = 0.5) -> None:
    """Momentarily close the switch to press the garage door button.

    Uses Shelly's built-in toggle_after parameter so the switch turns itself
    back off automatically — no second HTTP call needed.
    """
    import httpx
    resp = httpx.get(
        f"http://{ip}/rpc/Switch.Set",
        params={"id": 0, "on": "true", "toggle_after": pulse_seconds},
        timeout=5,
    )
    resp.raise_for_status()
