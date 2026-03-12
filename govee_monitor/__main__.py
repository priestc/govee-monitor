from __future__ import annotations
import asyncio
import datetime
import click
from govee_monitor.scanner import scan
from govee_monitor import labels as _labels


@click.group()
def main():
    """Monitor Govee H5074 temperature/humidity sensors via BLE."""


@main.command()
@click.option("--duration", "-d", type=float, default=None,
              help="How many seconds to scan (default: indefinitely).")
@click.option("--verbose", "-v", is_flag=True, help="Show raw advertisement data.")
def monitor(duration, verbose):
    """Continuously print readings from nearby H5074 sensors."""
    label_map = _labels.load()
    pending: set[str] = set()
    seen: set[str] = set()

    async def _run():
        loop = asyncio.get_event_loop()

        async def prompt_label(address: str, name: str) -> None:
            click.echo(f"\nNew sensor found: {name} ({address})")
            label = await loop.run_in_executor(
                None, lambda: click.prompt("  Enter a label").strip()
            )
            label_map[address] = label
            _labels.save(label_map)

        def on_reading(reading):
            if reading.address not in label_map:
                if reading.address not in pending:
                    pending.add(reading.address)
                    asyncio.ensure_future(prompt_label(reading.address, reading.name))
                return  # skip printing until label is assigned
            reading.label = label_map[reading.address]
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            click.echo(f"[{ts}] {reading}")
            seen.add(reading.address)

        await scan(on_reading, duration=duration, verbose=verbose)

    click.echo("Scanning for Govee H5074 sensors... (Ctrl+C to stop)")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        click.echo(f"\nDone. Saw {len(seen)} device(s).")


@main.command()
@click.option("--timeout", "-t", type=float, default=30.0,
              help="Seconds to scan (default: 30).")
@click.option("--verbose", "-v", is_flag=True, help="Show raw advertisement data.")
def scan_once(timeout, verbose):
    """Scan for a fixed duration and print all devices found."""
    label_map = _labels.load()
    pending: set[str] = set()
    readings: dict[str, object] = {}

    async def _run():
        loop = asyncio.get_event_loop()

        async def prompt_label(address: str, name: str) -> None:
            click.echo(f"\nNew sensor found: {name} ({address})")
            label = await loop.run_in_executor(
                None, lambda: click.prompt("  Enter a label").strip()
            )
            label_map[address] = label
            _labels.save(label_map)

        def on_reading(reading):
            if reading.address not in label_map:
                if reading.address not in pending:
                    pending.add(reading.address)
                    asyncio.ensure_future(prompt_label(reading.address, reading.name))
                return
            reading.label = label_map[reading.address]
            readings[reading.address] = reading

        await scan(on_reading, duration=timeout, verbose=verbose)

    click.echo(f"Scanning for {timeout}s...")
    try:
        asyncio.run(_run())
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
