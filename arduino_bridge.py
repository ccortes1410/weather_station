import serial
import requests
import json
import time
import re

# Change this to whatever COM port your UNO is using (e.g., 'COM3' on Windows, '/dev/ttyACM0' on Mac/Linux)
UNO_PORT = 'COM8' 
BAUD_RATE = 115200
API_URL = 'http://localhost:5000/api/sensor'

def bridge_data():
    try:
        # Connect to the Arduino
        ser = serial.Serial(UNO_PORT, BAUD_RATE, timeout=2)
        print(f"Connected to Arduino on {UNO_PORT}. Listening for data...")
        
        while True:
            while ser.in_waiting > 100:
                ser.readline()

            if ser.in_waiting > 0:
                raw_line = ser.readline().decode('utf-8').strip()

                match = re.search(r'\{.*\}', raw_line)

                # Check if the line looks like our JSON string
                if match:
                    clean_line = match.group(0)
                    try:
                        # Convert string to JSON to verify it's valid
                        payload = json.loads(clean_line)
                        if "status" not in payload:
                            response = requests.post(API_URL, json=payload)

                            if response.status_code == 500:
                                ser.write(b'E')
                                print(">>> [LED] Sent ERROR command: Database unreachable! <<<")
                            
                            if response.status_code == 201:
                                answer = response.json()
                                # If Flash says it just bulk-inserted, send 'B' to Arduino
                                if answer.get("status") == "bulk_success":
                                    ser.write(b'B')
                                    print(">>> [LED] Sent BULK SUCCESS flash command! <<<")
                                else:
                                    ser.write(b'R')                                
                            
                            current_time = time.strftime("%H:%M:%S")
                            print(f"[{current_time}] Sent to DB: {payload}")
                        
                            if response.status_code == 201:
                                print("Successfully forwarded to Dashboard!")
                            else:
                                print(f"API Error: {response.status_code}")
                            
                    # Catch the error if Flask completely crashes and doesn't respond
                    except requests.exceptions.RequestException as e:
                        ser.write(b'E')
                        print(f">>> [LED] Sent ERROR command: Flask API is down! <<<")
                        
            time.sleep(0.1)
            
    except serial.SerialException as e:
        print(f"Could not connect to UNO on {UNO_PORT}: {e}")

if __name__ == '__main__':
    bridge_data()