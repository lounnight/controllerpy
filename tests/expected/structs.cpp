const int LED = 13;
const int SENSOR = A0;
const int THRESHOLD = 512;
const int PAUSE = 200;
int samples = 0;

struct Reading {
    int value;
    bool bright;
};

struct Sample {
    int number;
    Reading reading;
};

bool is_bright(Reading reading);

bool is_bright(Reading reading) {
    return reading.value > THRESHOLD;
}

void setup() {
    pinMode(LED, OUTPUT);
    Serial.begin(9600);
}

void loop() {
    samples = samples + 1;

    Reading reading;
    reading.value = analogRead(SENSOR);
    reading.bright = is_bright(reading);

    Sample sample;
    sample.number = samples;
    sample.reading = reading;

    if (sample.reading.bright) {
        digitalWrite(LED, HIGH);
    } else {
        digitalWrite(LED, LOW);
    }

    Serial.print("sample ");
    Serial.print(sample.number);
    Serial.print(": ");
    Serial.println(sample.reading.value);

    delay(PAUSE);
}
