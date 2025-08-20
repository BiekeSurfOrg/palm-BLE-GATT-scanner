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

NOTIFY_WAIT_TOTAL_S = 15.0   # how long to wait for all chunks
NOTIFY_POLL_STEP_S  = 0.05  # polling interval while waiting


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

        # 3) Connect and stream via NOTIFY (reassemble frames)
    status = "creating GATT"
    mfg_hex = next(iter(target["manufacturer_data"].values()))
    info =  f"Device Address: {target['address']}\n"
    info += f"Manufacturer Data: {mfg_hex}\n"
    # Parse the manufacturer data based on the Kotlin buildManufacturerPayload function:
    # [version(1B)=0x01][“PALMKI” ASCII][rolling counter (2B LE)]
    mfg_bytes = bytes.fromhex(mfg_hex)
    version = mfg_bytes[0]
    tag = mfg_bytes[1:7].decode('utf-8', errors='ignore') # "PALMKI" is 6 bytes
    # Rolling counter is 2 bytes, Little Endian
    rolling_counter = int.from_bytes(mfg_bytes[7:9], byteorder='little')

    manufacture_data_ascii = f"Version: {version}, Tag: {tag}, Counter: {rolling_counter}"
    info += f"Manufacturer Data ASCII: {manufacture_data_ascii}\n"

    try:
        async with BleakClient(target["address"], timeout=CONNECT_TIMEOUT_S) as client:
            if not client.is_connected:
                return {"status": f"Failed to connect to {target['address']}", "info": info}

            info += f"Connected to {target['address']}\n"
            status = "discovering_services"
            target_characteristic_obj = None
            try:
                info += "  Discovering services...\n"
                # CORRECTED WAY TO ACCESS SERVICES:
                # The client.services property is a BleakGATTServiceCollection,
                # which can be iterated or accessed by UUID.
                # Explicitly calling a method like discover_services() or get_services()
                # might be needed if services aren't populated automatically after connection,
                # but often they are. Let's assume they are populated or Bleak handles it.

                # Iterate through discovered services
                for service_uuid_str, service_obj in client.services.services.items():
                    if service_obj.uuid.lower() == SERVICE_UUID.lower():
                        info += f"  Found service: {service_obj.uuid} (Handle: {service_obj.handle})\n"
                        for char_obj in service_obj.characteristics:
                            if char_obj.uuid.lower() == CHAR_UUID.lower():
                                info += f"  Found characteristic: {char_obj.uuid} (Handle: {char_obj.handle}, Properties: {char_obj.properties})\n"
                                if "notify" in char_obj.properties:
                                    target_characteristic_obj = char_obj
                                    break  # Found the target characteristic
                                else:
                                    info += f"    Characteristic {char_obj.uuid} does not support notify.\n"
                        if target_characteristic_obj:
                            break  # Found the target service and characteristic
                
                if not target_characteristic_obj:
                    info += f"  Target characteristic {CHAR_UUID} with notify property not found in service {SERVICE_UUID}.\n"
                    # status will be handled before attempting start_notify
            
            except Exception as e:
                info += f"  Error during service discovery: {e}\n"
                # status will be handled before attempting start_notify
            status = "receiving_gatt_notifications" # Updated status
            # --- Notification reassembly state ---
            chunks: Dict[int, bytes] = {}
            total_frames: Optional[int] = None

            def handle_frame(_, data: bytearray):
                nonlocal total_frames
                if len(data) < 6:
                    info += f"  Received runt frame (len {len(data)}), skipping.\n"
                    return
                seq   = data[0] | (data[1] << 8)
                total = data[2] | (data[3] << 8)
                ln    = data[4] | (data[5] << 8)
                if 6 + ln > len(data):
                    info += f"  Received frame with invalid length spec (header_len={ln}, actual_data_len={len(data)-6}), skipping.\n"
                    return
                payload = bytes(data[6:6+ln])
                chunks[seq] = payload
                total_frames = total

            try:
                # <<< MODIFICATION: Use target_characteristic_obj if found >>>
                if not target_characteristic_obj:
                    # This check is now more crucial after explicit discovery
                    info += "  Cannot start notifications: target characteristic was not resolved.\n"
                    status = "characteristic_resolve_failed_before_notify"
                else:
                    info += f"  Attempting to start notifications on characteristic handle {target_characteristic_obj.handle}...\n"
                    await client.start_notify(target_characteristic_obj, handle_frame) # Use the object

                    waited = 0.0
                    while (total_frames is None) or (len(chunks) < total_frames):
                        await asyncio.sleep(NOTIFY_POLL_STEP_S)
                        waited += NOTIFY_POLL_STEP_S
                        if waited >= NOTIFY_WAIT_TOTAL_S:
                            break
                    
                    info += "  Stopping notifications...\n"
                    await client.stop_notify(target_characteristic_obj) # Use the object
                # <<< MODIFICATION END >>>

                if total_frames is None and target_characteristic_obj : # only log if we attempted notifications
                    info += "  Did not receive any notification frames (total_frames is None).\n"
                elif total_frames is not None and len(chunks) < total_frames:
                    info += f"  Incomplete: got {len(chunks)}/{total_frames} frames before timeout.\n"
                elif total_frames is not None:
                    assembled_data = b""
                    missing_frame_in_reassembly = False
                    for i in range(total_frames):
                        if i not in chunks:
                            info += f"  Error during reassembly: Missing frame {i}.\n"
                            missing_frame_in_reassembly = True
                            break
                        assembled_data += chunks[i]
                    
                    if not missing_frame_in_reassembly:
                        try:
                            decoded = assembled_data.decode("utf-8")
                            info += f"  Service: {SERVICE_UUID}\n" # You can get actual service UUID from service_obj.uuid
                            info += f"    Characteristic: {CHAR_UUID}, Properties: {target_characteristic_obj.properties if target_characteristic_obj else 'N/A'}\n"
                            info += f"      Value: {decoded}\n"
                        except UnicodeDecodeError:
                            info += f"  Service: {SERVICE_UUID}\n"
                            info += f"    Characteristic: {CHAR_UUID}, Properties: {target_characteristic_obj.properties if target_characteristic_obj else 'N/A'}\n"
                            info += f"      Value (hex): {assembled_data.hex()}\n"
                    else:
                        info += "  Could not fully reassemble data due to missing frames.\n"
                  
                status = "finished_gatt_operations"

            except Exception as e:
                info += f"  Error during notification handling or assembly: {e}\n"
                status = f"notification_error_exception" # More specific status

    except BleakError as be: # Catch Bleak specific errors first
        status = f"bleak_error_during_connection"
        info += f"BleakError: {be}\n"
    except Exception as e:
        status = f"general_error_during_connection"
        info += f"Exception: {e}\n"

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
