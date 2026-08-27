import network

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

print("Scanning airwaves... (this takes a few seconds)")
networks = wlan.scan()

print(f"Found {len(networks)} networks:")
for net in networks:
    ssid = net[0].decode('utf-8', 'ignore')
    channel = net[2]
    rssi = net[3] # Signal strength (closer to 0 is better)
    print(f"Name: {ssid:20} | Channel: {channel:2} | Signal: {rssi}")