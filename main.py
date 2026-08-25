import machine
import network
import time
import ntptime
import urequests
from lcd import LCD

# Initialize the LCD with our exact wiring pins
screen = LCD(rs=10, en=11, d4=12, d5=13, d6=14, d7=15)
screen.clear()
screen.move_to(0, 0)
screen.print("Connecting Wi-fi...")

# Set how many readings to store before sending the bulk POST
BUFFER_LIMIT = 120

# Setup Hardware UART for PMS7003 (Using GP5 for RX)
uart = machine.UART(1, baudrate=9600, tx=machine.Pin(4), rx=machine.Pin(5))

# Function to read .env files manually
def load_env():
    env_vars = {}
    try:
        with open('.env') as f:
            for line in f:
                # Skip empty lines and comments
                if not line.strip() or line.startswith('#'):
                    continue
                # Split the line at the first equals sign
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    # Remove any accidental quotes around the password
                    env_vars[key] = value.strip('"\'')
        return env_vars
    except OSError:
        print("Error: No .env file found on the Pico!")
        return {}

secrets = load_env()

# --- CONFIGURATION ---
WIFI_SSID = secrets.get("WIFI_SSID", "default_network")
WIFI_PASSWORD = secrets.get("WIFI_PASSWORD", "default_password")
API_URL = "https://your-app.onrender.com/api/sensor"
API_KEY = secrets.get("API_KEY", "default_key")

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("Connecting to Wi-Fi...")
    while not wlan.isconnected():
        time.sleep(1)

    screen.clear()
    screen.move_ty(0, 0)
    screen.print("Wi-Fi Connected!")
    time.sleep(2)
    screen.clear()

    print("Wi-Fi Connected! IP:", wlan.ifconfig()[0])

def sync_time():
    screen.move_to(0, 1)
    screen.print("Syncing Time...")
    try:
        ntptime.settime() # Fetches UTC time from the internet
    except:
        screen.print("Time Sync Failed!")
        time.sleep(2)

connect_wifi()
sync_time()
screen.clear()

# This is the list that mimics my old Python PC script
data_buffer = []

while True:
    # Check if the sensor has sent a data packet
    if uart.any():
        buffer = uart.read(32)
        # Verify the 32-byte packet and the start bytes (0x42, 0x4D)
        if buffer and len(buffer) == 32 and buffer[0] == 0x42 and buffer[1] == 0x4D:
            pm1 = (buffer[10] << 8) | buffer[11]
            pm25 = (buffer[12] << 8) | buffer[13]
            pm10 = (buffer[14] << 8) | buffer[15]

            # Update the screen with live data
            screen.move_to(0, 0)
            screen.print("Air Quality (ug/m3) ")
            screen.move_to(0, 1)
            screen.print(f"PM1.0: {pm1}   ")
            screen.move_to(0, 2)
            screen.print(f"PM2.5: {pm25}   ")
            screen.move_ty(0, 3)
            screen.print(f"PM10: {pm10}   ")

            # Calculate local time
            # ntptime returns UTC. Subtracting 14,400 seconds offsets it to UTC-4 (Chile Standard Time)
            t = time.localtime(time.time() - 14400)

            # Format exactly like my MySQL database expects: YYYY-MM-DD HH:MM:SS
            time_str = f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

            # Append raw reading to the buffer list
            data_buffer.append({
                "timestamp": time_str,
                "pm1": pm1,
                "pm25": pm25,
                "pm10": pm10
            })

            # Check if buffer reached the limit to trigger the bulk POST
            if len(data_buffer) >= BUFFER_LIMIT:
                screen.move_to(19, 3)
                screen.print("*") # Show upload indicator

                headers = {"Content-Type": "application/json", "X-API-Key": API_KEY}

                try:
                    # Send the entire list directly to my Flask API:
                    response = urequests.post(API_URL, json=data_buffer, headers=headers)
                    response.close()

                    # Only clear the buffer if the POST was successful
                    data_buffer.clear()
                    screen.move_to(19, 3)
                    screen.print(" ")
                except Exception as e:
                    screen.move_to(19, 3)
                    screen.print("E")
                    # Note: If it fails, we DO NOT clear the buffer. It wil keep growing
                    # and try to send everything again on the next loop
            
            # Pause to keep sync with the sensor's ~1 second reporting rate
            time.sleep_ms(800)