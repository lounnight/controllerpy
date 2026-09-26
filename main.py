LED = 13
BUTTON = 7

def setup_led():
    pin_mode(LED, OUTPUT)

def main():
    setup_led()
    pin_mode(BUTTON, INPUT_PULLUP)
    serial_begin(9600)

def loop():
    if digital_read(BUTTON) == LOW:
        digital_write(LED, HIGH)
        serial_println("ON")
    else:
        digital_write(LED, LOW)

    delay(50)
