from builtins import *
from controllerpy_api import *
from controllerpy import Servo

ARM_PIN = 9
MIN_ANGLE = 0
MAX_ANGLE = 180
STEP = 15
PAUSE = 200

arm = Servo()

def sweep_out():
    angle = MIN_ANGLE
    while angle <= MAX_ANGLE:
        arm.write(angle)
        delay(PAUSE)
        angle = angle + STEP

def sweep_back():
    angle = MAX_ANGLE
    while angle >= MIN_ANGLE:
        arm.write(angle)
        delay(PAUSE)
        angle = angle - STEP

def main():
    arm.attach(ARM_PIN)
    arm.write(MIN_ANGLE)

def loop():
    sweep_out()
    sweep_back()
