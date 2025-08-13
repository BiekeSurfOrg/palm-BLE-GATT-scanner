# BLE Scanner with GATT Connection

This project consists of a backend and a frontend to scan for Bluetooth Low Energy (BLE) advertisements containing the text "PALMKI", establish a GATT connection, retrieve data, and display it.

## Project Structure

- `backend/`: Contains the Python script for BLE scanning and GATT communication.
- `frontend/`: Contains the web interface for displaying status and data.

## Getting Started

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
   ```bash
   python app.py
   ```
   The backend server will run on `http://127.0.0.1:5001`.

### Frontend

1. Open the `frontend/index.html` file in your web browser.
   ```bash
   open frontend/index.html
   ```
   (On Windows, you might use `start frontend\index.html` or simply double-click the file.)

Make sure the backend server is running before opening the frontend, as the frontend will try to fetch data from the backend.
