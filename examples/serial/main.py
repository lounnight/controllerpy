from builtins import *
from micropy_api import *
BAUD = 9600

def read_sensor():
    value = analog_read(A0)
    return value

def main():
    serial_begin(BAUD)
    serial_println("ready")

def loop():
    reading = read_sensor()
    serial_print("sensor: ")
    serial_println(reading)

    if serial_available() > 0:
        command = serial_read()
        serial_println(command)

    delay(100)
