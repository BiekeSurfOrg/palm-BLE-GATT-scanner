# BLE Scanner with GATT Connection

This project consists of a backend and a frontend to scan for Bluetooth Low Energy (BLE) advertisements containing the text "PALMKI", establish a GATT connection, retrieve data, and display it.

## Project Structure

- `backend/`: Contains Python scripts for BLE scanning and GATT communication.
- `frontend/`: Contains the web interface for displaying status and data.

## Functional Description

### `app.py`

This script scans for BLE advertisements containing "PALMKI" in their manufacturer data. When a device is found, it automatically establishes a GATT connection and retrieves service and characteristic data. This version does not require user authorization for GATT connections.

**Step-by-step functionality:**

1. Initializes a Flask web application.
2. Defines a `/scan` endpoint that handles BLE scanning.
3. Uses `BleakScanner` to discover BLE devices.
4. Filters devices based on the presence of "PALMKI" in their manufacturer data.
5. If a target device is found, it attempts to connect using `BleakClient`.
6. Discovers GATT services and characteristics of the connected device.
7. Reads data from readable characteristics and displays it.
8. Returns the scan results and GATT data as JSON to the frontend.

### `app-scan-all.py`

This script scans for all BLE packages and requires user authorization for GATT connections.

**Step-by-step functionality:**

1. Initializes a Flask web application.
2. Defines a `/scan` endpoint that handles BLE scanning.
3. Uses `BleakScanner` to discover all available BLE devices without filtering.
4. Presents a list of all discovered devices to the user.
5. If the user selects a device and authorizes the connection, it attempts to connect using `BleakClient`.
6. Discovers GATT services and characteristics of the connected device.
7. Reads data from readable characteristics and displays it.
8. Returns the scan results and GATT data as JSON to the frontend.

### `ble_scanner.py`

This script performs BLE scanning, checks for devices with "PALMKI" in their manufacturer data, establishes GATT connections to matching devices, and reads service and characteristic data. It includes error handling for connection and data reading.

**Step-by-step functionality:**

1. Initializes `BleakScanner` for device discovery.
2. Scans for all available BLE devices.
3. Iterates through discovered devices, checking their manufacturer data for the "PALMKI" string.
4. If "PALMKI" is found, it designates that device as the target.
5. Attempts to establish a GATT connection to the target device using `BleakClient`.
6. Upon successful connection, it discovers all services and characteristics.
7. For each characteristic with a 'read' property, it attempts to read its value.
8. Prints the device information, manufacturer data, and characteristic values to the console.
9. Includes error handling for decoding issues, connection failures, and characteristic read errors.

### `qr-code-generator.py`

This script generates a QR code containing a predefined JSON payload. The QR code is saved as a PNG image.

**Step-by-step functionality:**

1. Defines a Python dictionary `data` containing an `ID` and a `Hash`.
2. Converts the `data` dictionary into a JSON string.
3. Initializes a `qrcode.QRCode` instance with specified version, error correction, box size, and border.
4. Adds the JSON string to the QR code instance.
5. Generates the QR code image.
6. Saves the generated QR code image as `palm_qr_code.png`.

### `app-use-addr-ble-device.py`

This script is a copy of `app.py` but connects to a BLE device using its address instead of the device object. This is useful in scenarios where the device object might not be directly available or when reconnecting to a known device by its address.

**Step-by-step functionality:**

1. Initializes a Flask web application.
2. Defines a `/scan` endpoint that handles BLE scanning.
3. Uses `BleakScanner` to discover BLE devices.
4. Filters devices based on the presence of "PALMKI" in their manufacturer data.
5. If a target device is found, it attempts to connect using `BleakClient` by providing the device's address directly.
6. Discovers GATT services and characteristics of the connected device.
7. Reads data from readable characteristics and displays it.
8. Returns the scan results and GATT data as JSON to the frontend.

## Getting Started

### QR code generation

1. Navigate to the `backend` directory:
   ```bash
   cd backend
   ```
2. Run the `qr-code-generator.py` script:
   ```bash
   python qr-code-generator.py
   ```
   This will generate a QR code image named `palm_qr_code.png` in the same directory.
   The QR code can be scanned by the Palmki android app so it can transfer that data to the BLE scanner app (app.py) via GATT connection.

### Backend

1. Navigate to the `backend` directory:
   ```bash
   cd backend
   ```
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the Flask application:

   There are two main backend scripts:

   a. **`app.py`**: Scans for "PALMKI" in manufacturer data and automatically connects to the device if found. No user authorization is needed for the GATT connection.

   ```bash
   python app.py
   ```

   b. **`app-scan-all.py`**: Scans for all BLE packages and requires user authorization to make a GATT connection.

   ```bash
   python app-scan-all.py
   ```

   c. **`app-use-addr-ble-device.py`**: Connects to a BLE device using its address instead of the device object.

   ```bash
   python app-use-addr-ble-device.py
   ```

   Both backend servers will run on `http://127.0.0.1:5001`.

### Frontend

1. Open the `frontend/index.html` file in your web browser.
   ```bash
   open frontend/index.html
   ```
   (On Windows, you might use `start frontend\index.html` or simply double-click the file.)

Make sure the backend server is running before opening the frontend, as the frontend will try to fetch data from the backend.
