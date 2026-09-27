from builtins import *
from controllerpy_api import *

class Led:
    def __init__(self, pin):
        self.pin = pin
        pin_mode(pin, OUTPUT)

    def on(self):
        digital_write(self.pin, HIGH)

    def off(self):
        digital_write(self.pin, LOW)

status = Led(13)

def main():
    serial_begin(9600)

def loop():
    status.on()
    delay(500)
    status.off()
    delay(500)
    serial_println("blink")
