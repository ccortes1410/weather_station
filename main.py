import machine
from machine import Pin, Timer
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

# Setup LEDs on GPIO 14 and 15 as Outputs
green_led = Pin(16, Pin.OUT)
red_led = Pin(17, Pin.OUT)

green_led.off()
red_led.off()

heartbeat_timer = Timer(-1)

def turn_off_leds(t):
    green_led.off()
    red_led.off()

# Set how many readings to store before sending the bulk POST
BUFFER_LIMIT = 600

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
BUFFER_FILE = "buffer.txt"


def connect_wifi():
    screen.clear()
    screen.move_to(0, 0)
    screen.print("Connecting Wi-Fi...")

    network.country('CL')
    wlan = network.WLAN(network.STA_IF)

    wlan.active(False)  # Force a hard reset of the wireless chip
    time.sleep(1)
    wlan.active(True)

    wlan.config(pm=0xa11140)

    print("Wifi:", WIFI_SSID)
    # Disconnect just in case it held an old connection state
    if wlan.isconnected():
        wlan.disconnect()

    
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    
    # Give it a generous 15 seconds to finish the handshake
    max_wait = 15
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        print('Waiting for connection...')
        time.sleep(1)

    # 4. Check the final status
    if wlan.status() != 3:
        print("Connection Failed. Status code:", wlan.status())
    else:
        screen.clear()
        print("Connected successfully!")
        print("IP:", wlan.ifconfig()[0])

        screen.move_to(0, 0)
        screen.print("Connected to: ")
        screen.move_to(0, 1)
        screen.print(f"{WIFI_SSID}")
        time.sleep(1)
        
    return True

def sync_time():
    screen.clear()
    screen.move_to(0, 0)
    screen.print("Syncing Time...")
    try:
        ntptime.settime() # Fetches UTC time from the internet
        print("Time Synced!")
        screen.clear()
        screen.move_to(0, 0)
        screen.print("Time Synced!")
        time.sleep(0.1)
    except:
        screen.print("Time Sync Failed!")
        time.sleep(2)

def append_reading_to_flash(new_reading):
    try:
        with open(BUFFER_FILE, "a") as f:
            f.write(ujson.dumps(new_reading) + '\n')
    except Exception as e:
        print("Failed to append to flash:", e)

def process_backlog():
    try:
        screen.clear()
        screen.move_to(0, 0)
        screen.print("Processing backlog...")
        # Read the file as raw text strings
        screen.move_to(0, 0)

        with open(BUFFER_FILE, 'r') as f:
            lines = f.readlines()
    except OSError:
        print("No backup file found. Starting fresh.")
        screen.clear()
        screen.move_to(0, 0)
        screen.print("No backup found.")
        screen.move_to(0, 1)
        screen.print("Starting fresh...")
        return

    screen.clear()
    screen.move_to(0, 0)
    screen.print("Backlog remaining: ")
    

    while len(lines) > 0:
        gc.collect()

        screen.move_to(0, 1)
        print(f"Backlog remaining: {len(lines)} readings...")
        
        screen.print(f"{len(lines)} readings...")
        # 1. Take ONLY the fisrt 120 text lines
        chunk_lines = lines[:120]
        lines = lines[120:] # Keep the rest for the next loop

        # 2. Convert the lines to dictionaries
        upload_chunk = []
        for line in chunk_lines:
            if line.strip():
                try:
                    upload_chunk.append(ujson.loads(line))
                except ValueError:
                    pass

        # 3. Serialize and sweep memory
        payload = ujson.dumps(upload_chunk)
        gc.collect()

        try:
            # 4. Upload the chunk of 120
            headers = {'X-API-Key': API_KEY}
            response = urequests.post(API_URL, data=payload, headers=headers, timeout=10.0)
            screen.move_to(0, 2)

            if response.status_code in [200, 201]:
                
                print("Chunk uploaded succesfully!")
                screen.print("Upload success!")
                # 5. Save progress: rewrite the file with remaining lines
                with open(BUFFER_FILE, 'w') as f:
                    for l in lines:
                        f.write(l)

            response.close()
        except Exception as e:
            print("Network failed, keeping remaining backlog:", e)
            screen.print("Upload failed")
            screen.move_to(0, 3)
            screen.print("Keeping leftovers")
            # 6. Stop chewing and let the main loop run so we don't block the sensor
            break

def clear_flash_buffer():
    try:
        with open(BUFFER_FILE, "w") as f:
            f.write('')
    except Exception as e:
        print("Failed to clear flush:", e)

    
connect_wifi()
sync_time()

process_backlog()

screen.clear()

# This is the list that mimics my old Python PC script
data_buffer = []

last_blink = time.ticks_ms()
led_is_on = False

ping_counter = 0

try:
    while True:
        # Check if the sensor has sent a data packet
        if uart.any():
            buffer = uart.read(32)
            # Verify the 32-byte packet and the start bytes (0x42, 0x4D)
            if buffer and len(buffer) == 32:
                if buffer[0] == 0x42 and buffer[1] == 0x4D:

                    # Calculate the checksum
                    # Add up all the values from byte 0 to byte 29
                    calculated_checksum = sum(buffer[0:30])
                    # Combine bytes 30 and 31 to get the sensor's official total
                    sensor_checksum = (buffer[30] << 8) | buffer[31]

                    # Compare them. Only proceed if the checksum matches
                    if calculated_checksum == sensor_checksum:
                        gc.collect() # Free up RAM before processing the big list
                        
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


                        # time_str_short = f"{t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
                        # screen.move_to(12, 1)
                        # screen.print(time_str_short)

                        # Calculate local time
                        # ntptime returns UTC. Subtracting 14,400 seconds offsets it to UTC-4 (Chile Standard Time)
                        t = time.localtime(time.time() - 14400)

                        # Format exactly like my MySQL database expects: YYYY-MM-DD HH:MM:SS
                        time_str = f"{t[0]}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

                        current_ms = time.ticks_ms()
                        # Check if 5000 ms have passed
                        if time.ticks_diff(time.ticks_ms(), last_blink) >= 5000:
                            if pm25 <= 25:
                                # Good air: quick green flash
                                green_led.on()
                            else:
                                # Bad air: quick red flash
                                red_led.on()
                            heartbeat_timer.init(period=100, mode=Timer.ONE_SHOT, callback=turn_off_leds)

                            last_blink = current_ms
                        
                        live_data = {
                            'timestamp': time_str,
                            'pm1': pm1,
                            'pm25': pm25,
                            'pm10': pm10
                        }

                        ping_counter += 1

                        data_buffer.append(live_data)
                        append_reading_to_flash(live_data)

                        screen.move_to(15, 3)
                        screen.print(f"{len(data_buffer):2d}  ")
                        screen.move_to(19, 3)
                        screen.print(" ")

                        headers = {"X-API-Key": API_KEY}
                        # print(payload)
                    
                        # Check if buffer reached the limit to trigger the bulk POST
                        if len(data_buffer) >= BUFFER_LIMIT:
                            screen.move_to(19, 3)
                            screen.print("*") # Show upload indicator

                            upload_chunk = data_buffer[:BUFFER_LIMIT]

                            payload = ujson.dumps(upload_chunk)

                            gc.collect()

                            try:
                                # Send the entire list directly to my Flask API:
                                response = urequests.post(API_URL, data=payload, headers=headers, timeout=10.0)

                                if response.status_code in [200, 201]:
                                    data_buffer = data_buffer[BUFFER_LIMIT:]
                                    
                                    with open(BUFFER_FILE, "w") as f:
                                        for remaining_reading in data_buffer:
                                            f.write(ujson.dumps(remaining_reading) + '\n')

                                    screen.move_to(19, 3)
                                    screen.print(" ")
                                    print(f"Bulk Success")

                                response.close()
                            except Exception as e:
                                print("Upload Failed:", e)
                                screen.move_to(19, 3)
                                screen.print("E")
                                # Note: If it fails, we DO NOT clear the buffer. It wil keep growing
                                # and try to send everything again on the next loop
                        else:
                            if ping_counter >= 5:
                                try:
                                    response = urequests.post(API_URL, json=live_data, headers=headers, timeout=3.0)
                
                                    if response.status_code in [200, 201]:
                                        screen.move_to(19, 3)
                                        screen.print("^")
                                    response.close()
                                except Exception as e:
                                    screen.move_to(19, 3)
                                    screen.print("-")
                                    print("Live Ping Failed:", e)
                                    pass
                                ping_counter = 0
                                gc.collect()
                        # Pause to keep sync with the sensor's ~1 second reporting rate
                        time.sleep_ms(800)
                    else:
                        # The frame was misaligned or electrically corrupted
                        print("Checksum mismatch. Discarding frame.")
                        print("Calculated:", calculated_checksum, "Sensor:", sensor_checksum)
                        uart.read()
                else:
                    print("Framing error detected! Resyncing UART...")
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