const int LED = 13;
const int BUTTON = 7;

void setup() {
    pinMode(LED, OUTPUT);
    pinMode(BUTTON, INPUT_PULLUP);
}

void loop() {
    if (digitalRead(BUTTON) == LOW) {
        digitalWrite(LED, HIGH);
    } else {
        digitalWrite(LED, LOW);
    }

    delay(50);
}
