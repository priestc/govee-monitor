from __future__ import annotations
import asyncio
from bleak import BleakClient, BleakError

BATTERY_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


async def read_battery(address: str, timeout: float = 10.0) -> int | None:
    """Connect to a device and read its battery level (0-100). Returns None on failure."""
    try:
        async with BleakClient(address, timeout=timeout) as client:
            data = await client.read_gatt_char(BATTERY_CHAR_UUID)
            return data[0]
    except (BleakError, asyncio.TimeoutError, Exception):
        return None


async def read_batteries(addresses: list[str]) -> dict[str, int | None]:
    """Read battery for multiple devices concurrently."""
    results = await asyncio.gather(*[read_battery(a) for a in addresses])
    return dict(zip(addresses, results))
