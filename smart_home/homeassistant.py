from __future__ import annotations
import json
import os
from pathlib import Path

import httpx

from smart_home.decoder import Reading

CONFIG_PATH = Path(os.path.expanduser("~/.config/smart-home/homeassistant.json"))


def load_config() -> dict | None:
    if not CONFIG_PATH.exists():
        return None
    return json.loads(CONFIG_PATH.read_text())


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['token']}"}


def test_connection(cfg: dict) -> None:
    """Raise if the URL or token is invalid."""
    resp = httpx.get(f"{cfg['url'].rstrip('/')}/api/", headers=_headers(cfg))
    resp.raise_for_status()


def get_climate_entities(cfg: dict) -> list[dict]:
    """Return all climate entities that expose current_temperature."""
    resp = httpx.get(f"{cfg['url'].rstrip('/')}/api/states", headers=_headers(cfg))
    resp.raise_for_status()
    entities = []
    for state in resp.json():
        entity_id = state["entity_id"]
        attrs = state.get("attributes", {})
        if entity_id.startswith("climate.") and "current_temperature" in attrs:
            entities.append({
                "entity_id": entity_id,
                "name": attrs.get("friendly_name", entity_id),
                "current_temperature": attrs["current_temperature"],
                "current_humidity": attrs.get("current_humidity"),
            })
    return entities


def fetch_reading(cfg: dict) -> Reading:
    """Fetch the current temperature/humidity for the configured entity."""
    resp = httpx.get(
        f"{cfg['url'].rstrip('/')}/api/states/{cfg['entity_id']}",
        headers=_headers(cfg),
    )
    resp.raise_for_status()
    state = resp.json()
    attrs = state.get("attributes", {})

    temp = attrs.get("current_temperature")
    humidity = attrs.get("current_humidity")
    if temp is None:
        raise ValueError(f"Entity {cfg['entity_id']} has no current_temperature attribute")

    temp_f = float(temp)
    temp_c = (temp_f - 32) * 5 / 9

    return Reading(
        address=f"ha:{cfg['entity_id']}",
        name="Home Assistant",
        temp_c=temp_c,
        humidity=float(humidity) if humidity is not None else 0.0,
        battery=None,
        rssi=None,
        label=cfg["label"],
    )
