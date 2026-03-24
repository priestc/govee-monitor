"""PVVX firmware flasher for LYWSD03MMC temperature sensors.

Uses the Telink OAD (Over-the-Air Download) BLE protocol to flash the
pvvx/ATC_MiThermometer custom firmware.  After flashing, the sensor
advertises temperature/humidity passively (no GATT needed) with BLE name
ATC_XXXXXX where XXXXXX is the last 6 hex digits of the MAC address.

Protocol (from TelinkMiFlasher.html, pvvx/ATC_MiThermometer):
  OAD service:    00010203-0405-0607-0809-0a0b0c0d1912
  OAD write char: 00010203-0405-0607-0809-0a0b0c0d2b12
  Packet format:  [0x01][block_lo][block_hi][16 bytes firmware]  (19 bytes)
  Flow control:   write-with-response if char supports it (GATT-level ACK);
                  otherwise write-without-response with ~12 ms inter-packet delay.
"""
from __future__ import annotations
import asyncio
import struct
import urllib.request
from pathlib import Path
from bleak import BleakClient

# Telink OAD protocol UUIDs
OAD_SERVICE = "00010203-0405-0607-0809-0a0b0c0d1912"
OAD_CHAR    = "00010203-0405-0607-0809-0a0b0c0d2b12"

BLOCK_SIZE   = 16            # firmware bytes per OTA packet payload
TELINK_MAGIC = 0x544c4e4b   # "TLNK" at offset 0x08 in firmware header

# Default firmware: PVVX custom firmware for LYWSD03MMC
# Source: https://github.com/pvvx/ATC_MiThermometer
FIRMWARE_URL = (
    "https://github.com/pvvx/ATC_MiThermometer/raw/master/bin/ATC_v57.bin"
)
_CACHE_DIR = Path("~/.cache/smart-home").expanduser()


def download_firmware(url: str = FIRMWARE_URL) -> bytes:
    """Download PVVX firmware, caching locally in ~/.cache/smart-home/."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE_DIR / Path(url).name
    if cache_file.exists():
        return cache_file.read_bytes()
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = resp.read()
    cache_file.write_bytes(data)
    return data


def validate_firmware(data: bytes) -> int:
    """Validate Telink OTA firmware file.

    Returns the total number of 16-byte blocks.
    Raises ValueError if the file is not a valid Telink OTA image.
    """
    if len(data) < 0x20:
        raise ValueError(f"firmware too small ({len(data)} bytes)")
    magic = struct.unpack_from("<I", data, 0x08)[0]
    if magic != TELINK_MAGIC:
        raise ValueError(
            f"invalid Telink magic 0x{magic:08X} (expected 0x{TELINK_MAGIC:08X})"
        )
    return (len(data) + BLOCK_SIZE - 1) // BLOCK_SIZE


_DISCONNECT_ERRORS = ("disconnect", "closed", "not connected", "broken pipe")
_MAX_RETRIES       = 5    # reconnect attempts before giving up
_RECONNECT_DELAY   = 3.0  # seconds to wait before reconnecting
_INTER_BLOCK_DELAY = 0.020


async def _connect_and_find_oad(address_or_device):
    """Connect to device and return (BleakClient, oad_char).

    Raises RuntimeError if the OAD characteristic is not found.
    The returned client is already connected; caller must close it.
    """
    client = BleakClient(address_or_device, timeout=20.0)
    await client.connect()

    for svc in client.services:
        if svc.uuid.lower() == OAD_SERVICE.lower():
            for ch in svc.characteristics:
                if ch.uuid.lower() == OAD_CHAR.lower():
                    return client, ch

    await client.disconnect()
    raise RuntimeError(
        "OAD characteristic not found \u2014 make sure the sensor is in "
        "connectable mode (power it off and back on) and that it is "
        "a LYWSD03MMC running stock or PVVX firmware."
    )


async def flash_firmware(
    address_or_device,
    firmware: bytes,
    progress=None,
) -> None:
    """Flash PVVX firmware to a LYWSD03MMC via Telink OAD BLE protocol.

    address_or_device: MAC address string or BleakClient-compatible device.
    firmware: raw .bin bytes (validated by validate_firmware before calling).
    progress: optional callable(blocks_done: int, total_blocks: int).

    Automatically reconnects and resumes if the device drops the connection
    mid-transfer (common on stock firmware during OAD mode switch).
    Raises RuntimeError on failure.
    """
    total_blocks = validate_firmware(firmware)
    pad = total_blocks * BLOCK_SIZE - len(firmware)
    padded = firmware + b"\xff" * pad

    # Resolve address string once so reconnects can use it directly.
    address = (
        address_or_device
        if isinstance(address_or_device, str)
        else address_or_device.address
    )

    client, oad_char = await _connect_and_find_oad(address_or_device)

    # Use write-without-response throughout.  The stock LYWSD03MMC firmware
    # briefly disconnects/reconnects internally during OAD (switching to a
    # dedicated OTA mode), which invalidates BlueZ's service-discovery state
    # and causes write-with-response to fail with "Service Discovery has not
    # been performed yet".  Write-without-response avoids that check.
    # We pace at ~20 ms per block (50 blocks/s) to let the device keep up
    # with flash writes; the total transfer takes ~2 minutes for 86 KB.

    block_num = 0
    retries   = 0

    try:
        while block_num < total_blocks:
            is_last = block_num == total_blocks - 1
            offset  = block_num * BLOCK_SIZE

            # OAD packet: command(1) + block_index_LE(2) + data(16) = 19 bytes
            packet = (
                bytes([0x01, block_num & 0xFF, (block_num >> 8) & 0xFF])
                + padded[offset : offset + BLOCK_SIZE]
            )

            try:
                await client.write_gatt_char(OAD_CHAR, packet, response=False)

            except Exception as e:
                err = str(e).lower()
                is_disconnect = any(k in err for k in _DISCONNECT_ERRORS)

                if is_disconnect and (is_last or block_num >= total_blocks - 10):
                    # Device rebooted at/near end of transfer \u2014 treat as success.
                    block_num += 1
                    break

                if is_disconnect and retries < _MAX_RETRIES:
                    retries += 1
                    if progress:
                        # Emit a sentinel so the caller can show a reconnect message.
                        progress(block_num, total_blocks, reconnecting=True)
                    await asyncio.sleep(_RECONNECT_DELAY)
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    client, oad_char = await _connect_and_find_oad(address)
                    # Resume from the block that failed \u2014 do not advance block_num.
                    continue

                raise RuntimeError(
                    f"write failed at block {block_num} "
                    f"(retried {retries}x): {e}"
                ) from e

            await asyncio.sleep(_INTER_BLOCK_DELAY)
            block_num += 1
            retries = 0  # reset retry counter after each successful write
            if progress:
                progress(block_num, total_blocks)

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
