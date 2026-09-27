from builtins import *
from controllerpy_api import *

LED = 13

def main():
    pin_mode(LED, OUTPUT)

def loop():
    digital_write(LED, HIGH)
    delay(1000)
    digital_write(LED, LOW)
    delay(1000)
