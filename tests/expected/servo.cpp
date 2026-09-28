#include <Servo.h>

const int ARM_PIN = 9;
const int MIN_ANGLE = 0;
const int MAX_ANGLE = 180;
const int STEP = 15;
const int PAUSE = 200;

void sweep_out();
void sweep_back();

Servo arm;

void sweep_out() {
    int angle = MIN_ANGLE;
    while (angle <= MAX_ANGLE) {
        arm.write(angle);
        delay(PAUSE);
        angle = angle + STEP;
    }
}

void sweep_back() {
    int angle = MAX_ANGLE;
    while (angle >= MIN_ANGLE) {
        arm.write(angle);
        delay(PAUSE);
        angle = angle - STEP;
    }
}

void setup() {
    arm.attach(ARM_PIN);
    arm.write(MIN_ANGLE);
}

void loop() {
    sweep_out();
    sweep_back();
}
