const int SENSOR = A0;
const int BAUD = 9600;
const int PAUSE = 1000;
const int KEEP = 5;

void setup() {
    Serial.begin(BAUD);
}

void loop() {
    String line = String("raw=") + String(analogRead(SENSOR));
    line += "c";

    Serial.println(line);
    Serial.println(line.length());

    line.replace("raw", "temp");
    line.remove(line.length() - 1, 1);
    line.insert(0, "> ");
    line += " ok";

    Serial.println(line);

    line.substring(line.length() - KEEP);
    Serial.println(line);

    line.remove(0);
    Serial.println(line.length());

    delay(PAUSE);
}
