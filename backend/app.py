from __future__ import annotations

from flask import Flask, jsonify
from flask_cors import CORS
import asyncio
from concurrent.futures import TimeoutError as FuturesTimeout
from threading import Thread
from typing import Dict, Any, List, Optional
from datetime import datetime
import platform

from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

# -------------------- Flask setup --------------------
app = Flask(__name__)
CORS(app)

# -------------------- Constants / filters --------------------
TARGET_TEXT = "PALMKI"
TARGET_HEX = TARGET_TEXT.encode("utf-8").hex()

SERVICE_UUID = "e2a2b8e0-0b6c-4b6d-8868-c2b53f6c8d7b"
CHAR_UUID    = "c3b3c9f0-1c7d-4e7e-8a8b-9e0f1d0a2b3c"

SCAN_SECONDS      = 5.0
CONNECT_TIMEOUT_S = 10.0
MAC = platform.system().lower() == "darwin"

# -------------------- Dedicated, long-lived asyncio loop --------------------
_ble_loop: asyncio.AbstractEventLoop | None = None

def _start_ble_loop_thread():
    global _ble_loop
    _ble_loop = asyncio.new_event_loop()
    t = Thread(target=_ble_loop.run_forever, name="bleak-loop", daemon=True)
    t.start()
    return _ble_loop

def run_on_ble_loop(coro: asyncio.coroutine, timeout: float | None = None):
    """
    Schedule a coroutine on the long-lived BLE loop and return its result.
    """
    assert _ble_loop is not None, "BLE loop not started"
    fut = asyncio.run_coroutine_threadsafe(coro, _ble_loop)
    try:
        return fut.result(timeout=timeout)
    except FuturesTimeout:
        fut.cancel()
        raise

# -------------------- BLE helpers (run on the BLE loop) --------------------
async def _wait_bluetooth_available(total: float = 30.0, step: float = 2.0) -> bool:
    """
    macOS-safe probe: try a very short discover; if CoreBluetooth is down (BT off),
    Bleak will raise. We retry until available or timeout.
    """
    if not MAC:
        return True
    remaining = total
    while remaining >= 0:
        try:
            await BleakScanner.discover(timeout=0.1)
            return True
        except Exception:
            if remaining <= 0:
                return False
            await asyncio.sleep(step)
            remaining -= step
    return False

async def _scan_with_manufacturer_filter() -> Optional[Dict[str, Any]]:
    """
    Scan for devices whose manufacturer data contains 'PALMKI' (hex),
    returning the strongest RSSI match or None.
    """
    timestamp = datetime.now().isoformat()

    if MAC:
        # macOS path: safe bounded discover; no detection_callback (avoids KVO->closed-loop crashes)
        try:
            raw: Dict[str, tuple] = await BleakScanner.discover(
                timeout=SCAN_SECONDS, return_adv=True, cb={"allow_duplicates": True}
            )
        except Exception:
            # Propagate to caller, who will format a nice status
            raise

        matches: List[Dict[str, Any]] = []
        for addr, (dev, adv) in raw.items():
            for mfg_id, data in adv.manufacturer_data.items():
                hex_data = data.hex()
                if TARGET_HEX in hex_data:
                    matches.append({
                        "name": dev.name,
                        "address": addr,  # on macOS this is a UUID-like identifier; Bleak accepts it
                        "rssi": adv.rssi,
                        "tx_power": adv.tx_power,
                        "local_name": adv.local_name,
                        "service_uuids": adv.service_uuids,
                        "manufacturer_data": {mfg_id: hex_data},
                        "timestamp": timestamp,
                    })

        if not matches:
            return None
        return sorted(matches, key=lambda d: (d["rssi"] if d["rssi"] is not None else -999), reverse=True)[0]

    # Non-macOS path: fast detection_callback
    matches: List[Dict[str, Any]] = []

    def detection_callback(device, advertisement_data):
        for mfg_id, data in advertisement_data.manufacturer_data.items():
            hex_data = data.hex()
            if TARGET_HEX in hex_data:
                matches.append({
                    "name": device.name,
                    "address": device.address,
                    "rssi": advertisement_data.rssi,
                    "tx_power": advertisement_data.tx_power,
                    "local_name": advertisement_data.local_name,
                    "service_uuids": advertisement_data.service_uuids,
                    "manufacturer_data": {mfg_id: hex_data},
                    "timestamp": timestamp,
                })

    scanner = BleakScanner(detection_callback)
    await scanner.start()
    await asyncio.sleep(SCAN_SECONDS)
    await scanner.stop()

    if not matches:
        return None
    return sorted(matches, key=lambda d: (d["rssi"] if d["rssi"] is not None else -999), reverse=True)[0]

async def _perform_ble_scan_core() -> Dict[str, str]:
    # 1) macOS: ensure Bluetooth is available; if not, return a friendly status.
    if MAC:
        ok = await _wait_bluetooth_available(total=30.0, step=2.0)
        if not ok:
            return {
                "status": "Bluetooth is OFF",
                "info": "Waiting for Bluetooth to be enabled on this Mac. Please toggle Bluetooth ON and retry."
            }

    # 2) Scan using manufacturer filter
    try:
        target = await _scan_with_manufacturer_filter()
    except BleakError as e:
        return {"status": "Bluetooth error", "info": f"{e}"}
    except Exception as e:
        return {"status": "Bluetooth error", "info": f"{e}"}

    if not target:
        return {"status": "No BLE package found", "info": ""}

    # 3) Connect and ONLY read your target characteristic (to avoid pairing popups)
    status = "creating GATT"
    mfg_hex = next(iter(target["manufacturer_data"].values()))
    info =  f"Device Address: {target['address']}\n"
    info += f"Manufacturer Data: {mfg_hex}\n"

    try:
        async with BleakClient(target["address"], timeout=CONNECT_TIMEOUT_S) as client:
            if not client.is_connected:
                return {"status": f"Failed to connect to {target['address']}", "info": info}

            status = "receiving GATT"
            info += f"Connected to {target['address']}\n"

            try:
                value = await client.read_gatt_char(CHAR_UUID)
                # Prefer UTF-8, fallback to hex
                try:
                    decoded = value.decode("utf-8")
                    info += f"  Service: {SERVICE_UUID}\n"
                    info += f"    Characteristic: {CHAR_UUID}, Properties: ['read']\n"
                    info += f"      Value: {decoded}\n"
                except UnicodeDecodeError:
                    info += f"  Service: {SERVICE_UUID}\n"
                    info += f"    Characteristic: {CHAR_UUID}, Properties: ['read']\n"
                    info += f"      Value (hex): {value.hex()}\n"
            except Exception as e:
                info += f"  Failed to read target characteristic: {e}\n"

            status = "Finished"
    except Exception as e:
        status = f"Error during connection or communication: {e}"

    return {"status": status, "info": info}

# -------------------- Flask route (runs work on the BLE loop) --------------------
@app.route('/scan', methods=['GET'])
def scan_ble():
    try:
        result = run_on_ble_loop(_perform_ble_scan_core(), timeout=60.0)
    except FuturesTimeout:
        return jsonify({"status": "Timeout", "info": "BLE operation timed out."})
    except Exception as e:
        return jsonify({"status": "Internal error", "info": f"{e}"}), 500
    return jsonify(result)

# -------------------- App bootstrap --------------------
if __name__ == '__main__':
    _start_ble_loop_thread()  # start & keep a dedicated loop alive for all Bleak I/O
    # Use Flask dev server; for production prefer an ASGI server and keep a persistent loop similarly.
    app.run(host='0.0.0.0', port=5001)
