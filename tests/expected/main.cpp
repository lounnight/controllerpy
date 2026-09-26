const int LED = 13;
const int BUTTON = 7;

void setup_led();

void setup_led() {
    pinMode(LED, OUTPUT);
}

void setup() {
    setup_led();
    pinMode(BUTTON, INPUT_PULLUP);
    Serial.begin(9600);
}

void loop() {
    if (digitalRead(BUTTON) == LOW) {
        digitalWrite(LED, HIGH);
        Serial.println("ON");
    } else {
        digitalWrite(LED, LOW);
    }

    delay(50);
}
