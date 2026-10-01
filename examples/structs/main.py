from builtins import *
from controllerpy_api import *

LED = 13
SENSOR = A0
THRESHOLD = 512
PAUSE = 200

class Reading:
    value: int
    bright: bool

class Sample:
    number: int
    reading: Reading

samples = 0

def is_bright(reading: Reading) -> bool:
    return reading.value > THRESHOLD

def main():
    pin_mode(LED, OUTPUT)
    serial_begin(9600)

def loop():
    samples = samples + 1

    reading = Reading()
    reading.value = analog_read(SENSOR)
    reading.bright = is_bright(reading)

    sample = Sample()
    sample.number = samples
    sample.reading = reading

    if sample.reading.bright:
        digital_write(LED, HIGH)
    else:
        digital_write(LED, LOW)

    serial_print("sample ")
    serial_print(sample.number)
    serial_print(": ")
    serial_println(sample.reading.value)

    delay(PAUSE)