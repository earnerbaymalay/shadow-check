"""BLE advertisement scanner (BlueZ via bleak)."""
import asyncio

from bleak import BleakScanner

from .fingerprint import ble_fingerprint


def _addr_type(device):
    try:
        return device.details["props"].get("AddressType")
    except Exception:
        return None


async def scan(recorder, stop: asyncio.Event):
    def on_adv(device, adv):
        fp = ble_fingerprint(
            addr=device.address,
            addr_type=_addr_type(device),
            name=adv.local_name,
            manufacturer_data=adv.manufacturer_data or {},
            service_uuids=adv.service_uuids or [],
            service_data=adv.service_data or {},
            tx_power=adv.tx_power,
        )
        recorder.record(fp, adv.rssi)

    async with BleakScanner(on_adv):
        await stop.wait()
