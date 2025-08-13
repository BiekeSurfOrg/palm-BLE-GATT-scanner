import asyncio
from bleak import BleakScanner, BleakClient

TARGET_TEXT = "PALMKI"

async def scan_and_connect():
    print("Scanning for BLE devices...")
    devices = await BleakScanner.discover()

    target_device = None
    for device in devices:
        print(f"Device: {device.name} ({device.details})")
        if "manufacturer_data" in device.details:
            print(f"Device: {device.name} ({device.details['manufacturer_data']})")
            for manufacturer_id, data in device.details["manufacturer_data"].items():
                try:
                    decoded_data = data.decode('utf-8', errors='ignore')
                    if TARGET_TEXT in decoded_data:
                        print(f"Found device with manufacturer data: {decoded_data} ({device.address})")
                        target_device = device
                        break
                except UnicodeDecodeError:
                    pass # Ignore if not decodable as utf-8
            if target_device: # Break outer loop if found in manufacturer data
                break

    if target_device:
        print(f"Connecting to {target_device.address}...")
        try:
            async with BleakClient(target_device.address) as client:
                if client.is_connected:
                    print(f"Connected to {target_device.address}")
                    # Discover services and characteristics
                    for service in client.services:
                        print(f"  Service: {service.uuid}")
                        for char in service.characteristics:
                            print(f"    Characteristic: {char.uuid}, Properties: {char.properties}")
                            if "read" in char.properties:
                                try:
                                    value = await client.read_gatt_char(char.uuid)
                                    print(f"      Value: {value.decode('utf-8', errors='ignore')}")
                                except Exception as e:
                                    print(f"      Could not read characteristic {char.uuid}: {e}")
                else:
                    print(f"Failed to connect to {target_device.address}")
        except Exception as e:
            print(f"Error during connection or communication: {e}")
    else:
        print("No BLE package with 'PALMKI' found.")

if __name__ == "__main__":
    asyncio.run(scan_and_connect())