import machine
import time

class LCD:
    def __init__(self, rs, en, d4, d5, d6, d7):
        self.rs = machine.Pin(rs, machine.Pin.OUT)
        self.en = machine.Pin(en, machine.Pin.OUT)
        self.data = [machine.Pin(p, machine.Pin.OUT) for p in [d4, d5, d6, d7]]
        self.init_display()

    def pulse_en(self):
        self.en.value(0)
        time.sleep_us(1)
        self.en.value(1)
        time.sleep_us(1)
        self.en.value(0)
        time.sleep_us(100)

    def write_nibble(self, val):
        for i in range(4):
            self.data[i].value((val >> i) & 0x01)
        self.pulse_en()

    def write_byte(self, val, is_data=True):
        self.rs.value(1 if is_data else 0)
        self.write_nibble(val >> 4)
        self.write_nibble(val & 0x0F)

    def init_display(self):
        time.sleep_ms(50)
        self.rs.value(0)
        self.write_nibble(0x03)
        time.sleep_ms(5)
        self.write_nibble(0x03)
        time.sleep_ms(1)
        self.write_nibble(0x03)
        self.write_nibble(0x02) 
        self.write_byte(0x28, False) 
        self.write_byte(0x0C, False) 
        self.write_byte(0x06, False) 
        self.clear()

    def clear(self):
        self.write_byte(0x01, False)
        time.sleep_ms(2)

    def move_to(self, col, row):
        # Memory offsets specifically for 20x4 screens
        offsets = [0x00, 0x40, 0x14, 0x54]
        self.write_byte(0x80 | (col + offsets[row]), False)

    def print(self, text):
        for char in text:
            self.write_byte(ord(char), True)