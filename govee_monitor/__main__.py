from __future__ import annotations
import asyncio
import datetime
import click
from govee_monitor.scanner import scan


@click.group()
def main():
    """Monitor Govee H5074 temperature/humidity sensors via BLE."""


@main.command()
@click.option("--duration", "-d", type=float, default=None,
              help="How many seconds to scan (default: indefinitely).")
@click.option("--verbose", "-v", is_flag=True, help="Show raw advertisement data.")
def monitor(duration, verbose):
    """Continuously print readings from nearby H5074 sensors."""
    seen = set()

    def on_reading(reading):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        click.echo(f"[{ts}] {reading}")
        seen.add(reading.address)

    click.echo("Scanning for Govee H5074 sensors... (Ctrl+C to stop)")
    try:
        asyncio.run(scan(on_reading, duration=duration, verbose=verbose))
    except KeyboardInterrupt:
        click.echo(f"\nDone. Saw {len(seen)} device(s).")


@main.command()
@click.option("--timeout", "-t", type=float, default=10.0,
              help="Seconds to scan (default: 10).")
@click.option("--verbose", "-v", is_flag=True, help="Show raw advertisement data.")
def scan_once(timeout, verbose):
    """Scan for a fixed duration and print all devices found."""
    readings = {}

    def on_reading(reading):
        readings[reading.address] = reading

    click.echo(f"Scanning for {timeout}s...")
    try:
        asyncio.run(scan(on_reading, duration=timeout, verbose=verbose))
    except KeyboardInterrupt:
        pass

    if not readings:
        click.echo("No Govee H5074 devices found.")
    else:
        click.echo(f"\nFound {len(readings)} device(s):")
        for r in readings.values():
            click.echo(f"  {r}")


@main.command("scan-all")
@click.option("--timeout", "-t", type=float, default=15.0,
              help="Seconds to scan (default: 15).")
def scan_all(timeout):
    """Scan for ALL nearby BLE devices and dump their raw advertisement data.

    Use this to diagnose what your sensors are actually advertising.
    """
    import asyncio
    from bleak import BleakScanner

    seen = {}

    def callback(device, adv):
        seen[device.address] = (device, adv)

    async def _run():
        async with BleakScanner(detection_callback=callback):
            await asyncio.sleep(timeout)

    click.echo(f"Scanning all BLE devices for {timeout}s...")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass

    if not seen:
        click.echo("No BLE devices found. Check that bluetoothd is running and you have permission.")
        click.echo("Try: sudo govee-monitor scan-all")
        return

    click.echo(f"\nFound {len(seen)} device(s):\n")
    for addr, (device, adv) in sorted(seen.items()):
        name = device.name or adv.local_name or "(no name)"
        click.echo(f"  {addr}  name={name!r}  rssi={adv.rssi}")
        if adv.manufacturer_data:
            for cid, data in adv.manufacturer_data.items():
                click.echo(f"    manufacturer[0x{cid:04X}] = {data.hex()}")
        if adv.service_data:
            for uuid, data in adv.service_data.items():
                click.echo(f"    service_data[{uuid}] = {data.hex()}")
        if adv.service_uuids:
            click.echo(f"    service_uuids = {adv.service_uuids}")


if __name__ == "__main__":
    main()
