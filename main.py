import machine
import network
import time
import ntptime
import urequests
from lcd import LCD
import ujson
import gc

# Give the board 5 seconds to breathe on boot 
# so you can always recover the COM port if something fails!

print("Booting up weather station...")
time.sleep(5) 

# Initialize the LCD with our exact wiring pins
screen = LCD(rs=10, en=11, d4=12, d5=13, d6=14, d7=15)
screen.clear()
screen.move_to(0, 0)
screen.print("Booting up...")

# Set how many readings to store before sending the bulk POST
BUFFER_LIMIT = 60

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
API_URL = "https://weather-station-wwau.onrender.com/api/sensor"
API_KEY = secrets.get("API_KEY", "default_key")
BUFFER_FILE = "buffer.json"


def connect_wifi():
    screen.clear()
    screen.move_to(0, 0)
    screen.print("Connecting Wi-Fi...")
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)  # Force a hard reset of the wireless chip
    time.sleep(1)
    wlan.active(True)
    
    # Disconnect just in case it held an old connection state
    if wlan.isconnected():
        wlan.disconnect()
        
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    # Give it up to 15 seconds to connect
    timeout = 30
    start_time = time.time()
    
    while not wlan.isconnected():
        if time.time() - start_time > timeout:
            screen.clear()
            screen.move_to(0, 0)
            screen.print("Wi-Fi Failed!")
            screen.move_to(0, 1)
            screen.print("Check SSID/Pass")
            print(">>> WIFI CONNECTION TIMEOUT <<<")
            return False
        time.sleep(1)
        print(".", end="")
        
    print("\nWi-Fi Connected! IP:", wlan.ifconfig()[0])
    screen.clear()
    screen.move_to(0, 0)
    screen.print("Connected!")
    time.sleep(1)
    return True

def sync_time():
    screen.move_to(0, 1)
    screen.print("Syncing Time...")
    try:
        ntptime.settime() # Fetches UTC time from the internet
        print("Time Synced!")
    except:
        screen.print("Time Sync Failed!")
        time.sleep(2)

def save_buffer_to_flash(buffer_list):
    try:
        with open(BUFFER_FILE, "w") as f:
            f.write(ujson.dumps(buffer_list))
    except Exception as e:
        print("Failed to save buffer to flash:", e)

def load_buffer_from_flash():
    try:
        with open(BUFFER_FILE, "r") as f:
            data = f.read()
            if data:
                return ujson.loads(data)
    except OSError:
        # File doesn't exist yet, which is totally normal on first booy
        pass
    except Exception as e:
        print("Failed to load buffer from flash:", e)
    return []
    
connect_wifi()
sync_time()
screen.clear()

# This is the list that mimics my old Python PC script
data_buffer = load_buffer_from_flash()
print(f"Restored {len(data_buffer)} pending readings from flash storage.")

try:
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
                screen.move_to(0, 3)
                screen.print(f"PM10: {pm10}   ")

                # Calculate local time
                # ntptime returns UTC. Subtracting 14,400 seconds offsets it to UTC-4 (Chile Standard Time)
                t = time.localtime(time.time() - 14400)

                # Format exactly like my MySQL database expects: YYYY-MM-DD HH:MM:SS
                time_str = f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

                print(f"[{time_str}] PM1.0: {pm1},  PM2.5: {pm25},  PM10: {pm10}")
                
                live_data = {
                    'timestamp': time_str,
                    'pm1': pm1,
                    'pm25': pm25,
                    'pm10': pm10
                }

                data_buffer.append(live_data)
                save_buffer_to_flash(data_buffer)

                screen.move_to(15, 3)
                screen.print(f"{len(data_buffer):2d}")

                headers = {"X-API-Key": API_KEY}
                # print(payload)
            
                # Check if buffer reached the limit to trigger the bulk POST
                if len(data_buffer) >= BUFFER_LIMIT:
                    screen.move_to(19, 3)
                    screen.print("*") # Show upload indicator

                    gc.collect() # Free up RAM before processing the big list

                    try:
                        # Send the entire list directly to my Flask API:
                        response = urequests.post(API_URL, json=data_buffer, headers=headers)

                        if response.status_code in [200, 201]:
                            data_buffer.clear()
                            save_buffer_to_flash(data_buffer) # Clears the flash file too!
                            screen.move_to(19, 3)
                            screen.print(" ")
                            print(f"Bulk Success")
                        response.close()
                    except Exception as e:
                        print("POST Failed with error: ", e)
                        screen.move_to(19, 3)
                        screen.print("E")
                        # Note: If it fails, we DO NOT clear the buffer. It wil keep growing
                        # and try to send everything again on the next loop
                else:
                    try:
                        response = urequests.post(API_URL, json=live_data, headers=headers)
    
                        if response.status_code in [200, 201]:
                            screen.move_to(19, 3)
                            screen.print("^")
                        response.close()
                    except Exception as e:
                        screen.move_to(19, 3)
                        screen.print("-")
                        print("Live Ping Failed:", e)
                        pass
                # Pause to keep sync with the sensor's ~1 second reporting rate
                time.sleep_ms(800)
# If literally anything crashes inside the loop:
except Exception as e:
    # 1. Print the error (helpful when plugged into PC)
    print("FATAL ERROR ENCOUNTERED:", e)
    
    # 2. Update the LCD so you know it crashed
    screen.clear()
    screen.move_to(0, 0)
    screen.print("SYSTEM CRASHED!")
    screen.move_to(0, 1)
    screen.print("Rebooting in 5s...")
    
    # 3. Wait 5 seconds, then physically reboot the microcontroller
    time.sleep(5)
    machine.reset()