// XJ SCI bridge: USB serial <-> Chrysler SCI bus (OBD1 SBEC engine computer).
//
// Turns a 5 V Arduino (Nano, Uno or Mega) into a USB adapter for the 7812.5 baud
// SCI line on 1991-1995 Jeep/Chrysler engine computers. OBD1 SCI is electrically
// inverted compared to a normal serial port; SoftwareSerial's inverse_logic flag
// handles that, so no inverter chip is needed.
//
// Wiring (as tested on a 1994 Cherokee 4.0, see docs/wiring.md):
//   D10 (Arduino RX) <---------------------- PCM SCI-TX  (the PCM talks on this one)
//   D11 (Arduino TX) ----------------------> PCM SCI-RX  (the PCM listens on this one)
//   GND              <---------------------- diagnostic connector ground
// No external pull-up on D10: on the test car a 1k pull-up to 5 V held the line high and nothing
// was ever received. The Nano's internal pull-up (enabled below) is enough.
//
// USB protocol (115200 baud):
//   On reset the bridge prints "XJBRIDGE 1.0" and waits for text commands:
//     PROBE   -> "IDLE HIGH% <0-100>"  how often D10 reads high over 200 ms
//     GO I    -> "OK INVERTED"         start bridging, inverted logic (OBD1)
//     GO N    -> "OK NORMAL"           start bridging, normal logic
//   After GO, every byte is passed straight through in both directions until reset.
//   Send one byte at a time and wait for its echo: SoftwareSerial blocks
//   interrupts while it transmits, so a burst from the PC could be dropped.

#include <SoftwareSerial.h>

const uint8_t SCI_RX_PIN = 10;
const uint8_t SCI_TX_PIN = 11;
const long USB_BAUD = 115200;
const long SCI_BAUD = 7812;  // nominal 7812.5 baud

SoftwareSerial *sci = nullptr;

void setup() {
  pinMode(SCI_RX_PIN, INPUT_PULLUP);
  pinMode(SCI_TX_PIN, INPUT);  // don't drive the bus until told to
  Serial.begin(USB_BAUD);
  Serial.println(F("XJBRIDGE 1.0"));
}

// Percentage of samples where the PCM transmit line reads high over ~200 ms.
uint8_t probeIdle() {
  uint16_t high = 0;
  for (uint16_t i = 0; i < 2000; i++) {
    if (digitalRead(SCI_RX_PIN)) high++;
    delayMicroseconds(100);
  }
  return high / 20;
}

void handleCommands() {
  static char line[16];
  static uint8_t len = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') {
      if (len < sizeof(line) - 1) line[len++] = c;
      continue;
    }
    line[len] = 0;
    len = 0;

    if (!strcmp(line, "PROBE")) {
      Serial.print(F("IDLE HIGH% "));
      Serial.println(probeIdle());
    } else if (!strcmp(line, "GO I") || !strcmp(line, "GO N")) {
      bool inverted = line[3] == 'I';
      sci = new SoftwareSerial(SCI_RX_PIN, SCI_TX_PIN, inverted);
      sci->begin(SCI_BAUD);
      digitalWrite(SCI_RX_PIN, HIGH);  // the internal pull-up: the only one this line needs
      Serial.println(inverted ? F("OK INVERTED") : F("OK NORMAL"));
      Serial.flush();
      return;
    } else {
      Serial.println(F("ERR"));
    }
  }
}

void loop() {
  if (!sci) {
    handleCommands();
    return;
  }
  while (Serial.available()) sci->write((uint8_t)Serial.read());
  while (sci->available()) Serial.write((uint8_t)sci->read());
}
