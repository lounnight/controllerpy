from builtins import *
from controllerpy_api import *

LED = 13
BUTTON = 7

def main():
    pin_mode(LED, OUTPUT)
    pin_mode(BUTTON, INPUT_PULLUP)

def loop():
    if digital_read(BUTTON) == LOW:
        digital_write(LED, HIGH)
    else:
        digital_write(LED, LOW)

    delay(50)
