// XJ sniff: debug tool for the SCI wiring. Sends one byte on D11 (bit-banged, 7812.5 baud,
// either polarity), then records every level change on D10 for 60 ms and prints the edge times.
// tools/sniff.py drives it and decodes the result. Re-upload arduino/xj_bridge when done.
//
// USB commands (115200 baud), one per line:
//   N 14   D11 idles high, send 0x14 normal logic, capture D10
//   I 14   D11 idles low, send 0x14 inverted logic, capture D10
//   W      capture D10 only (D11 left as it is)
//   Z      D11 back to high impedance
// Reply: "CAP start=<level> n=<edges> end=<level> t=<tick>,<tick>,..."  (1 tick = 4 us)

const uint8_t RX_BIT = 2;              // D10 = PB2
const uint8_t TX_BIT = 3;              // D11 = PB3
const uint16_t BIT_TICKS = 32;         // 128 us per bit at 4 us per tick
const uint16_t CAPTURE_TICKS = 60000;  // 240 ms
const uint16_t MAX_EDGES = 400;

uint16_t edges[MAX_EDGES];

void setup() {
  DDRB &= ~_BV(RX_BIT);
  PORTB |= _BV(RX_BIT);   // D10 input, internal pull-up as backup to the external 1k
  DDRB &= ~_BV(TX_BIT);
  PORTB &= ~_BV(TX_BIT);  // D11 high impedance until told
  TCCR1A = 0;
  TCCR1B = _BV(CS11) | _BV(CS10);  // Timer1 free-running at 250 kHz
  Serial.begin(115200);
  Serial.println(F("XJSNIFF 1.0"));
}

void setTx(bool high) {
  if (high) PORTB |= _BV(TX_BIT);
  else PORTB &= ~_BV(TX_BIT);
}

void driveIdle(bool inverted) {
  setTx(!inverted);
  DDRB |= _BV(TX_BIT);
}

void sendByte(uint8_t b, bool inverted) {
  uint16_t frame = ((uint16_t)b << 1) | 0x200;  // start 0, data LSB first, stop 1
  uint16_t t = TCNT1;
  for (uint8_t i = 0; i < 10; i++) {
    bool one = frame & (1 << i);
    setTx(inverted ? !one : one);
    t += BIT_TICKS;
    while ((int16_t)(TCNT1 - t) < 0) {}
  }
}

void captureAndReport() {
  uint16_t n = 0;
  uint16_t t0 = TCNT1;
  uint8_t last = PINB & _BV(RX_BIT);
  uint8_t start = last ? 1 : 0;
  while ((uint16_t)(TCNT1 - t0) < CAPTURE_TICKS && n < MAX_EDGES) {
    uint8_t now = PINB & _BV(RX_BIT);
    if (now != last) {
      edges[n++] = TCNT1 - t0;
      last = now;
    }
  }
  sei();
  Serial.print(F("CAP start="));
  Serial.print(start);
  Serial.print(F(" n="));
  Serial.print(n);
  Serial.print(F(" end="));
  Serial.print(last ? 1 : 0);
  Serial.print(F(" t="));
  for (uint16_t i = 0; i < n; i++) {
    if (i) Serial.print(',');
    Serial.print(edges[i]);
  }
  Serial.println();
}

void loop() {
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
    if (line[0] == 'N' || line[0] == 'I') {
      bool inverted = line[0] == 'I';
      uint8_t b = strtoul(line + 1, nullptr, 16);
      driveIdle(inverted);
      delay(300);
      cli();
      sendByte(b, inverted);
      captureAndReport();
    } else if (line[0] == 'W') {
      cli();
      captureAndReport();
    } else if (line[0] == 'Z') {
      DDRB &= ~_BV(TX_BIT);
      PORTB &= ~_BV(TX_BIT);
      Serial.println(F("OK Z"));
    } else {
      Serial.println(F("ERR"));
    }
  }
}
