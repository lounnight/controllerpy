class Led {
public:
    int pin;

    Led(int pin) {
        this->pin = pin;
        pinMode(pin, OUTPUT);
    }

    void on() {
        digitalWrite(this->pin, HIGH);
    }

    void off() {
        digitalWrite(this->pin, LOW);
    }
};

Led status(13);

void setup() {
    Serial.begin(9600);
}

void loop() {
    status.on();
    delay(500);
    status.off();
    delay(500);
    Serial.println("blink");
}
