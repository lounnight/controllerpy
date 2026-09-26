const int LED = 13;
const int PAUSE = 250;

void blink(int count);

void blink(int count) {
    for (int i = 0; i < count; i++) {
        digitalWrite(LED, HIGH);
        delay(PAUSE);
        digitalWrite(LED, LOW);
        delay(PAUSE);
    }
}

void setup() {
    pinMode(LED, OUTPUT);
}

void loop() {
    for (int i = 0; i < 3; i++) {
        blink(i + 1);
    }

    while (true) {
        if (digitalRead(2) == HIGH) {
            break;
        }
    }
}
