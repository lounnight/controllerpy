const int BAUD = 9600;

int read_sensor();

int read_sensor() {
    int value = analogRead(A0);
    return value;
}

void setup() {
    Serial.begin(BAUD);
    Serial.println("ready");
}

void loop() {
    int command;

    int reading = read_sensor();
    Serial.print("sensor: ");
    Serial.println(reading);

    if (Serial.available() > 0) {
        command = Serial.read();
        Serial.println(command);
    }

    delay(100);
}
