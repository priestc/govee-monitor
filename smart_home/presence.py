from __future__ import annotations
import json
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "smart-home"
_DATA_DIR = Path.home() / ".local" / "share" / "smart-home"
_DEVICES_FILE = _CONFIG_DIR / "presence_devices.json"
_STATE_FILE = _CONFIG_DIR / "presence_state.json"
_HISTORY_FILE = _DATA_DIR / "presence_history.jsonl"


def load_devices() -> dict[str, str]:
    """Return {address: name} of registered presence devices."""
    if _DEVICES_FILE.exists():
        try:
            with open(_DEVICES_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def save_devices(devices: dict[str, str]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_DEVICES_FILE, "w") as f:
        json.dump(devices, f, indent=2)


def load_state() -> dict:
    """Return {address: {name, status, last_seen}} presence state."""
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def save_state(state: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def append_history(entry: dict) -> None:
    """Append a single {ts, ble_name, label, status} record to the history log."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def load_history() -> list[dict]:
    """Return all history records, oldest first."""
    if not _HISTORY_FILE.exists():
        return []
    entries = []
    with open(_HISTORY_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries
