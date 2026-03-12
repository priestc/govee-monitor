from __future__ import annotations
import dataclasses


@dataclasses.dataclass
class Reading:
    address: str
    name: str
    temp_c: float
    humidity: float
    battery: int | None  # percent
    rssi: int | None

    @property
    def temp_f(self) -> float:
        return self.temp_c * 9 / 5 + 32

    def __str__(self) -> str:
        batt = f"  battery={self.battery}%" if self.battery is not None else ""
        rssi = f"  rssi={self.rssi}" if self.rssi is not None else ""
        return (
            f"{self.name} ({self.address})"
            f"  temp={self.temp_c:.1f}°C/{self.temp_f:.1f}°F"
            f"  humidity={self.humidity:.1f}%"
            f"{batt}{rssi}"
        )


GOVEE_COMPANY_ID = 0xEC88


def decode_advertisement(address: str, name: str, manufacturer_data: dict, rssi: int | None) -> Reading | None:
    """Decode a Govee H5074 BLE advertisement into a Reading.
    Returns None if the data cannot be decoded.
    """
    data = manufacturer_data.get(GOVEE_COMPANY_ID)
    if data is None:
        return None
    # Payload is either 4 bytes (original H5075-style) or 7 bytes (H5074 with leading 0x00).
    # 7-byte format: byte 0 = 0x00 prefix, bytes 1-3 = packed temp+humidity, byte 4 = battery.
    # 4-byte format: bytes 0-2 = packed temp+humidity, byte 3 = battery.
    if len(data) >= 7 and data[0] == 0x00:
        raw_bytes = data[1:4]
        battery = data[4]
    elif len(data) >= 4:
        raw_bytes = data[0:3]
        battery = data[3]
    else:
        return None

    raw = int.from_bytes(raw_bytes, "big")
    if raw & 0x800000:
        raw = 0x1000000 - raw
        temp_c = -(raw // 1000) / 10
    else:
        temp_c = (raw // 1000) / 10
    humidity = (raw % 1000) / 10

    return Reading(
        address=address,
        name=name,
        temp_c=temp_c,
        humidity=humidity,
        battery=battery,
        rssi=rssi,
    )
