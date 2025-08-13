from flask import Flask, jsonify
import asyncio
from datetime import datetime
from bleak import BleakScanner, BleakClient
from flask_cors import CORS

app = Flask(__name__)
CORS(app) # Enable CORS for frontend communication

TARGET_TEXT = "PALMKI"

async def perform_ble_scan():
    print("Scanning for BLE devices...")
    status = "No BLE package found"
    info = ""
    
    raw: Dict[str, tuple] = await BleakScanner.discover(
        return_adv=True, cb={"allow_duplicates": True}
    )

    devices: List[Dict[str, Any]] = []
    timestamp = datetime.now().isoformat()

    for addr, (dev, adv) in raw.items():
        # Convert manufacturer_data: bytes → hex
        man_data = {
            mfg_id: data for mfg_id, data in adv.manufacturer_data.items()
        }
        # Convert service_data: bytes → hex
        svc_data = {uuid: data for uuid, data in adv.service_data.items()}

        device_data = {
            "name": dev.name,
            "address": addr,
            "rssi": adv.rssi,
            "tx_power": adv.tx_power,
            "local_name": adv.local_name,
            "service_uuids": adv.service_uuids,
            "manufacturer_data": man_data,
            "service_data": svc_data,
            "timestamp": timestamp,
            # note: we deliberately leave out dev.details and adv.platform_data
        }
        devices.append(device_data)

    target_device = None
    for device in devices:
        if "manufacturer_data" in device:
            print(f"Device: {device['name']} ({device['manufacturer_data']})")
            for manufacturer_id, data in device["manufacturer_data"].items():
                hex_data = data.hex()
                if TARGET_TEXT.encode('utf-8').hex() in hex_data:
                    target_device = device
                    status = "PALMKI package found"
                    info = f"Device Address: {device['address']}\nManufacturer Data: {hex_data}"
                    break
                
               
            if target_device:
                break

    if target_device:
        status = "creating GATT"
        print("Creating GATT...")
        try:
            async with BleakClient(target_device['address']) as client:
                if client.is_connected:
                    status = "receiving GATT"
                    info += f"\nConnected to {target_device['address']}\n"
                    print(f"Connected to {target_device['address']}")
                    
                    for service in client.services:
                        info += f"  Service: {service.uuid}\n"
                        for char in service.characteristics:
                            info += f"    Characteristic: {char.uuid}, Properties: {char.properties}\n"
                            if "read" in char.properties:
                                try:
                                    value = await client.read_gatt_char(char.uuid)
                                    info += f"      Value: {value.decode('utf-8', errors='ignore')}\n"
                                except Exception as e:
                                    info += f"      Could not read characteristic {char.uuid}: {e}\n"
                    print(info)
                    status = "Finished"
                else:
                    status = f"Failed to connect to {target_device['address']}"
        except Exception as e:
            status = f"Error during connection or communication: {e}"
    else:
        status = "No BLE package found"
    print("GATT creation finished")

    return {"status": status, "info": info}

@app.route('/scan', methods=['GET'])
async def scan_ble():
    result = await perform_ble_scan()
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)