from builtins import *
from controllerpy_api import *
LED = 13
PAUSE = 250

def blink(count):
    for i in range(count):
        digital_write(LED, HIGH)
        delay(PAUSE)
        digital_write(LED, LOW)
        delay(PAUSE)

def main():
    pin_mode(LED, OUTPUT)

def loop():
    for i in range(3):
        blink(i + 1)

    while True:
        if digital_read(2) == HIGH:
            break
