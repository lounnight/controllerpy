from builtins import *
from controllerpy_api import *

SENSOR = A0
BAUD = 9600
PAUSE = 1000
KEEP = 5

def main():
    serial_begin(BAUD)

def loop():
    line = "raw=" + str(analog_read(SENSOR))
    line += "c"

    serial_println(line)
    serial_println(len(line))

    line.replace("raw", "temp")
    line.remove(len(line) - 1, 1)
    line.insert(0, "> ")
    line += " ok"

    serial_println(line)

    line.substring(len(line) - KEEP)
    serial_println(line)

    line.clear()
    serial_println(len(line))

    delay(PAUSE)
