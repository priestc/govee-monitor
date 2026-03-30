from __future__ import annotations
import asyncio
import datetime
import json
import struct
import time
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "smart-home"
_PVVX_FILE  = _CONFIG_DIR / "pvvx_devices.json"

_PVVX_CHAR      = "00001f1f-0000-1000-8000-00805f9b34fb"  # PVVX control/history characteristic
_CMD_SYNC_TIME  = 0x23
_CMD_QUERY      = 0x33  # init/handshake — send [0x33, 0xC8] on connect
_CMD_GET_MEMO   = 0x35  # stream history — send [0x35, count_lo, count_hi, start_lo, start_hi]
_MEMO_BLOCK_ID  = 0x35  # block ID in every history notification


def load_addresses() -> set[str]:
    """Return the set of MAC addresses known to be running PVVX firmware."""
    if _PVVX_FILE.exists():
        try:
            with open(_PVVX_FILE) as f:
                return set(json.load(f))
        except (json.JSONDecodeError, ValueError):
            pass
    return set()


def mark_address(address: str) -> None:
    """Record a MAC address as having PVVX firmware installed."""
    addresses = load_addresses()
    addresses.add(address.upper())
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_PVVX_FILE, "w") as f:
        json.dump(sorted(addresses), f, indent=2)


async def read_pvvx_history(
    address: str,
    count: int = 255,
    timeout: float = 30.0,
    idle_timeout: float = 5.0,
    verbose: bool = False,
) -> list[dict]:
    """Connect to a PVVX sensor, sync its clock, and read stored history records.

    count: max records to fetch (1-255). Sensor returns newest-first.
    Returns a list of dicts: ts, temp_c, humidity, vbat_mv. Returns [] on error.
    """
    from bleak import BleakClient, BleakError, BleakScanner

    def _log(msg):
        if verbose:
            print(f"  [pvvx] {msg}")

    address = address.upper()
    records: list[dict] = []
    done = asyncio.Event()
    last_activity: list[float] = [0.0]
    raw_bytes_received: list[int] = [0]

    def handle_notification(sender, data: bytearray):
        last_activity[0] = time.monotonic()
        raw_bytes_received[0] += len(data)
        _log(f"notification {len(data)} bytes: {data.hex()}")
        if len(data) < 2 or data[0] != _MEMO_BLOCK_ID:
            return  # not a history notification
        if len(data) < 13:
            # End-of-memo signal (len < 12 data bytes after block ID)
            _log("End-of-memo signal received.")
            done.set()
            return
        # History record layout (all little-endian):
        #   0:     uint8  block ID (0x35)
        #   1-2:   uint16 record counter/index
        #   3-6:   uint32 unix timestamp
        #   7-8:   int16  temperature * 100 (°C)
        #   9-10:  uint16 humidity * 100 (%)
        #   11-12: uint16 battery voltage (mV)
        unix_ts  = struct.unpack_from("<I", data, 3)[0]
        raw_temp = struct.unpack_from("<h", data, 7)[0]
        raw_humi = struct.unpack_from("<H", data, 9)[0]
        vbat_mv  = struct.unpack_from("<H", data, 11)[0]
        if unix_ts == 0:
            return
        ts_str = datetime.datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S")
        records.append({"ts": ts_str, "temp_c": raw_temp / 100.0, "humidity": raw_humi / 100.0, "vbat_mv": vbat_mv})

    # Scan first so BlueZ caches the device
    device = None
    _log(f"Scanning for {address} (up to 15s)...")
    try:
        async with BleakScanner() as scanner:
            deadline = asyncio.get_running_loop().time() + 15.0
            while asyncio.get_running_loop().time() < deadline:
                for dev, _ in scanner.discovered_devices_and_advertisement_data.values():
                    if dev.address.upper() == address:
                        device = dev
                        break
                if device:
                    break
                await asyncio.sleep(0.5)
    except (BleakError, Exception) as e:
        _log(f"Scan error: {type(e).__name__}: {e}")
        return []

    if device is None:
        _log("Device not found during scan.")
        return []

    _log(f"Found: {device.name} — connecting...")
    try:
        async with BleakClient(device, timeout=timeout) as client:
            if verbose:
                _log("Connected. Services available:")
                for svc in client.services:
                    for ch in svc.characteristics:
                        print(f"    {ch.uuid}  [{','.join(ch.properties)}]")
            # Sync RTC on the sensor
            now_epoch = int(time.time())
            sync_cmd = bytes([_CMD_SYNC_TIME]) + struct.pack("<I", now_epoch)
            _log(f"Sending clock sync: {sync_cmd.hex()}")
            await client.write_gatt_char(_PVVX_CHAR, sync_cmd, response=False)
            # Subscribe to notifications
            _log(f"Subscribing to notifications on {_PVVX_CHAR}")
            await client.start_notify(_PVVX_CHAR, handle_notification)
            # Init handshake (query current measurements) — required before GetMemo
            _log(f"Sending init query: {bytes([_CMD_QUERY, 0xC8]).hex()}")
            await client.write_gatt_char(_PVVX_CHAR, bytes([_CMD_QUERY, 0xC8]), response=False)
            await asyncio.sleep(0.5)  # wait for init response
            # GetMemo: [0x35, count_lo, count_hi, start_lo, start_hi]
            n = min(count, 19632)
            memo_cmd = bytes([_CMD_GET_MEMO]) + struct.pack("<HH", n, 0)
            _log(f"Sending GetMemo: {memo_cmd.hex()} (requesting {n} records)")
            await client.write_gatt_char(_PVVX_CHAR, memo_cmd, response=False)
            # Wait for end-of-memo signal, with idle_timeout as fallback
            last_activity[0] = time.monotonic()
            try:
                await asyncio.wait_for(done.wait(), timeout=idle_timeout + n * 0.05 + 10)
            except asyncio.TimeoutError:
                _log(f"Timeout waiting for end-of-memo (got {len(records)} records so far)")
            _log(f"Total bytes received: {raw_bytes_received[0]}, records parsed: {len(records)}")
            await client.stop_notify(_PVVX_CHAR)
    except (BleakError, asyncio.TimeoutError, Exception) as e:
        _log(f"Connection/GATT error: {type(e).__name__}: {e}")
        return []

    if records:
        _log(f"Oldest: {records[0]['ts']}, Newest: {records[-1]['ts']}")
    return records
