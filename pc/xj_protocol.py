"""Chrysler OBD1 SCI-bus protocol for 1991-1995 Jeep engine computers (SBEC).

Talks to the PCM through an Arduino running xj_bridge.ino.

Parameter IDs and scaling come from ChryslerScanner by Laszlo Daniel
(github.com/laszlodaniel/ChryslerScanner, GPLv3). OBD1 transaction shape
(from its firmware): send 0x14, wait for echo; send the parameter ID, wait
for echo; the PCM then repeats the value byte until it receives 0x00.
"""

import random
import threading
import time

from dtc_table import DTC_DESCRIPTIONS

USB_BAUD = 115200
BYTE_TIMEOUT = 0.25  # seconds to wait for an echo or a response byte


class LinkError(Exception):
    pass


# --- parameter decoding ------------------------------------------------------

def volts(raw):
    return round(raw * 0.0196, 3)


def temp_f(raw):
    return round(1.8 * (raw - 128) + 32)


def psi(raw):
    return round(raw * 0.059756, 2)


def battery_volts(raw):
    return round(raw * 0.0625, 2)


def fuel_trim(raw):
    pct = raw * 0.196
    if raw >= 128:
        pct -= 50.0
    return round(pct, 1)


def fuel_status(raw):
    names = ["OPEN LOOP", "CLOSED LOOP", "OPEN LOOP / DRIVE", "OPEN LOOP / DTC", "CLOSED LOOP / DTC"]
    set_bits = [name for bit, name in enumerate(names) if raw & (1 << bit)]
    return " | ".join(set_bits) if set_bits else "N/A"


def o2_state(raw):
    return {0xA0: "LEAN", 0xB1: "RICH", 0xFF: "CENTER"}.get(raw, "N/A")


# PID 0x20, from ChryslerScanner's OBD1 decoder: high nibble = why cruise last cut out,
# low nibble = current state (8 allowed, 9 engaged) or why it's being denied.
_CRUISE_CUTOUT = ["ON/OFF SW", "SPEED SEN", "RPM LIMIT", "BRAKE SW", "P/N SW", "RPM/SPEED", "CLUTCH",
                  "DTC PRESENT", "KEY OFF", "ACTIVE", "CLUTCH UP", "N/A", "SW DTC", "CANCEL SW",
                  "TPS LIMP-IN", "12V DTC"]
_CRUISE_STATE = ["ON/OFF SW", "SPEED SEN", "RPM LIMIT", "BRAKE SW", "P/N SW", "RPM/SPEED", "CLUTCH",
                 "DTC PRESENT", "ALLOWED", "ACTIVE", "CLUTCH UP", "N/A", "SW DTC", "CANCEL SW",
                 "TPS LIMP-IN", "12V DTC"]


def cruise_status(raw):
    last, now = _CRUISE_CUTOUT[raw >> 4], _CRUISE_STATE[raw & 0x0F]
    if raw & 0x0F in (8, 9):
        return f"{now} (last cutout {last})"
    return f"DENIED {now} (last cutout {last})"


# 0x13 <id> starts a PCM actuator test, 0x13 0x00 stops it (ChryslerScanner OBD1 table; ids for
# this 6-cylinder SBEC that matter here).
ACTUATOR_TESTS = {
    0x01: "ignition coil 1", 0x02: "ignition coil 2", 0x03: "ignition coil 3",
    0x04: "injector 1", 0x05: "injector 2", 0x06: "injector 3",
    0x1D: "injector 4", 0x1E: "injector 5", 0x1F: "injector 6",
    0x07: "idle air control motor", 0x08: "radiator fan relay", 0x09: "A/C clutch relay",
    0x0A: "auto shutdown relay", 0x0B: "evap purge solenoid", 0x0C: "cruise control solenoids",
    0x0D: "alternator field", 0x0E: "tachometer output", 0x0F: "torque converter clutch relay",
    0x10: "EGR solenoid", 0x14: "all solenoids / relays", 0x16: "transmission O/D solenoid",
    0x1A: "cruise control vent solenoid", 0x1B: "cruise control vacuum solenoid",
    0x1C: "ASD fuel system", 0x2C: "cruise control 12V feed", 0x33: "fuel pump relay",
}


def sync_state(raw):
    return "IN-SYNC" if raw & 0x10 else "ENGINE STOPPED"


class Param:
    def __init__(self, pid, name, unit, decode, default_on):
        self.pid = pid
        self.name = name
        self.unit = unit
        self.decode = decode
        self.default_on = default_on

    @property
    def label(self):
        return f"{self.name} ({self.unit})" if self.unit else self.name


PARAMS = [
    Param(0x11, "Engine speed", "rpm", lambda r: r * 32, True),
    Param(0x05, "Coolant temp", "°F", temp_f, True),
    Param(0x1B, "Intake air temp", "°F", temp_f, True),
    Param(0x07, "Throttle position sensor", "V", volts, True),
    Param(0x0B, "MAP (manifold pressure)", "psi", psi, True),
    Param(0x02, "Upstream O2 sensor", "V", volts, True),
    Param(0x0A, "Battery voltage", "V", battery_volts, True),
    Param(0x15, "Spark advance", "deg", lambda r: r * 0.5, True),
    Param(0x0C, "Target IAC position", "steps", lambda r: r, True),
    Param(0x41, "Vehicle speed", "mph", lambda r: r, True),
    Param(0x3B, "Fuel system", "", fuel_status, True),
    # On this 1994 SBEC 128 = no correction, and ChryslerScanner's sign-bit % formula is wrong here
    # (it reads raw 110 as +21.6 % when the computer is really removing fuel). Logged as counts from
    # 128: below 0 = removing fuel. The PCM's own code gives 1/384 = 0.26 % of fuel per count, and
    # learning is clamped to raw 108..168 (-5.2 % .. +10.4 %). See docs/parameters.md.
    Param(0x0E, "Long-term fuel trim (counts from 128)", "", lambda r: r - 128, True),
    Param(0x08, "Minimum TPS voltage", "V", volts, False),
    Param(0x06, "Coolant sensor voltage", "V", volts, False),
    Param(0x1C, "Intake air temp sensor voltage", "V", volts, False),
    Param(0x40, "MAP sensor voltage", "V", volts, False),
    Param(0x0F, "Barometric pressure", "psi", psi, False),
    Param(0x24, "Target charging voltage", "V", battery_volts, False),
    Param(0x42, "Upstream O2 state", "", o2_state, False),
    Param(0x12, "Cam/crank sync", "", sync_state, False),
    Param(0x09, "Knock sensor voltage", "V", volts, False),
    Param(0x2D, "Ambient/battery temp", "°F", temp_f, False),
    Param(0x01, "Battery temp sensor voltage", "V", volts, False),
]
# Also answered by this 1994 4.0 PCM (sweep 2026-10-16). Names and scaling from ChryslerScanner's
# OBD1 0x14 table. Neither 0x3B nor 0x57 (fuel system status 1/2) answers on it, so open vs
# closed loop has to be read from the upstream O2 switching.
PARAMS += [
    Param(0x45, "MAP vacuum", "psi", psi, False),
    Param(0x47, "Spark advance (0x47)", "deg", lambda r: r * 0.5, False),
    Param(0x46, "Delta throttle position", "V", volts, False),
    # ChryslerScanner calls 0x10 "minimum air flow test", but on this PCM it behaves like commanded
    # fuel: 47 cranking cold, ~25 → 21 as it warms, up with MAP/rpm, up when O2 reads lean (r = −0.76).
    Param(0x10, "Fuel command (0x10)", "raw", lambda r: r, False),
    Param(0x13, "Key-on cycles error 1", "", lambda r: r, False),
    Param(0x1E, "Key-on cycles error 2", "", lambda r: r, False),
    Param(0x1F, "Key-on cycles error 3", "", lambda r: r, False),
    Param(0x1D, "Cruise set speed", "mph", lambda r: r * 0.5, False),
    Param(0x20, "Cruise status", "", cruise_status, False),
    Param(0x27, "Theft alarm status", "raw", lambda r: r, False),
]
# Answer, but ChryslerScanner has no decoder for them.
PARAMS += [Param(pid, f"PID {pid:02X}", "raw", lambda r: r, False) for pid in (0x0D, 0x22, 0x23)]
PARAMS_BY_PID = {p.pid: p for p in PARAMS}


def swap_nibbles(b):
    return ((b << 4) & 0xF0) | ((b >> 4) & 0x0F)


def hexs(data):
    return " ".join(f"{b:02X}" for b in data)


# --- link to the PCM ---------------------------------------------------------

class Link:
    """One OBD1 SCI conversation with the PCM through the Arduino bridge."""

    def __init__(self, ser, nibble_swap=False, on_raw=None):
        self.ser = ser
        self.nibble_swap = nibble_swap
        self.on_raw = on_raw  # callback(str) for raw traffic, or None

    @classmethod
    def open(cls, port, inverted=True, on_info=print):
        """Open the bridge, report the idle level, and switch it into bridge mode."""
        if port.startswith("DEMO"):
            ser = FakeBridge(pcm_nibble_swap=port == "DEMO-SWAP")
        else:
            import serial
            if port == "auto":
                port = find_bridge_port()
                on_info(f"Using {port}")
            ser = serial.Serial(port, USB_BAUD, timeout=0.005)
        try:
            # Opening the port normally resets the Arduino; if it didn't, pulse DTR.
            banner = _wait_for_line(ser, "XJBRIDGE", 3.0)
            if banner is None:
                try:
                    ser.dtr = False
                    time.sleep(0.1)
                    ser.dtr = True
                except OSError:
                    pass
                banner = _wait_for_line(ser, "XJBRIDGE", 4.0)
            if banner is None:
                raise LinkError(f"No bridge answered on {port}. Is xj_bridge.ino uploaded to that Arduino?")
            on_info(f"Bridge found: {banner}")
            ser.write(b"PROBE\n")
            probe = _read_line(ser, 1.0)
            on_info(f"PCM transmit line idle check: {probe}  ->  {_explain_probe(probe, inverted)}")
            ser.write(b"GO I\n" if inverted else b"GO N\n")
            ok = _read_line(ser, 1.0)
            if not ok.startswith("OK"):
                raise LinkError(f"Bridge did not start (got {ok!r})")
            on_info(f"Bridge running: {ok}")
            ser.reset_input_buffer()
        except Exception:
            ser.close()
            raise
        return cls(ser)

    def close(self):
        self.ser.close()

    def _put(self, b):
        raw = swap_nibbles(b) if self.nibble_swap else b
        self.ser.write(bytes([raw]))
        if self.on_raw:
            self.on_raw(f"TX {raw:02X}")

    def _get(self, timeout):
        deadline = time.monotonic() + timeout
        while True:
            data = self.ser.read(1)
            if data:
                raw = data[0]
                if self.on_raw:
                    self.on_raw(f"RX {raw:02X}")
                return swap_nibbles(raw) if self.nibble_swap else raw
            if time.monotonic() >= deadline:
                return None

    def _collect(self, first_timeout, quiet, max_time=1.0):
        """Bytes until the line has been silent for `quiet` seconds (or max_time passes,
        since a PCM that keeps repeating a value never goes quiet)."""
        out = []
        stop = time.monotonic() + max_time
        b = self._get(first_timeout)
        while b is not None:
            out.append(b)
            if time.monotonic() >= stop:
                break
            b = self._get(quiet)
        return out

    def _send_with_echo(self, b):
        """Send a byte and wait for the PCM to echo it, skipping any leftover stream bytes."""
        self._put(b)
        deadline = time.monotonic() + BYTE_TIMEOUT
        other = []
        while True:
            got = self._get(max(0.0, deadline - time.monotonic()))
            if got == b:
                return
            if got is None:
                if other:
                    raise LinkError(f"Echo mismatch: sent {b:02X}, got {hexs(other)}")
                raise LinkError(f"No echo for byte {b:02X}")
            other.append(got)

    def read_raw(self, pid):
        """Raw value byte of one diagnostic parameter."""
        self.ser.reset_input_buffer()
        self._send_with_echo(0x14)
        self._send_with_echo(pid)
        value = self._get(BYTE_TIMEOUT)
        self._put(0x00)  # stop the PCM repeating the value
        self._collect(0.03, 0.03)
        if value is None:
            raise LinkError(f"No value for parameter {pid:02X}")
        return value

    def read_param(self, pid):
        return PARAMS_BY_PID[pid].decode(self.read_raw(pid))

    def detect_byte_order(self):
        """Pick normal or nibble-swapped bytes by checking battery voltage is sane."""
        for swap in (False, True):
            self.nibble_swap = swap
            try:
                v = battery_volts(self.read_raw(0x0A))
            except LinkError:
                continue
            if 9.0 <= v <= 16.5:
                return swap, v
        self.nibble_swap = False
        return None, None

    def read_codes(self):
        """Stored fault codes as (codes, checksum_ok, raw_bytes)."""
        self.ser.reset_input_buffer()
        self._put(0x10)
        data = self._collect(BYTE_TIMEOUT, 0.08)
        if not data or data[0] != 0x10:
            raise LinkError(f"Unexpected fault code response: {hexs(data) or 'nothing'}")
        if len(data) < 2:
            return [], False, data
        checksum_ok = (sum(data[:-1]) & 0xFF) == data[-1]
        codes = [c for c in data[1:-1] if c not in (0xFD, 0xFE)]
        return codes, checksum_ok, data

    def erase_codes(self):
        self.ser.reset_input_buffer()
        self._put(0x17)
        return self._collect(BYTE_TIMEOUT, 0.08)

    def actuator_start(self, test_id):
        """Start PCM actuator test `test_id` (0x13 <id>). Returns everything the PCM sent back."""
        return self.raw_send(bytes([0x13, test_id]))

    def actuator_stop(self):
        return self.raw_send(bytes([0x13, 0x00]))

    def raw_send(self, data):
        """Send bytes one at a time (each waits for its echo), return everything received."""
        self.ser.reset_input_buffer()
        received = []
        for b in data:
            self._put(b)
            received += self._collect(BYTE_TIMEOUT, 0.03)
        return received


def describe_code(code):
    return DTC_DESCRIPTIONS.get(code, "UNRECOGNIZED DTC")


def find_bridge_port():
    """The first USB serial port that looks like an Arduino (CH340 clones or genuine)."""
    from serial.tools import list_ports
    names = ("usbserial", "wchusbserial", "usbmodem", "ttyUSB", "ttyACM")
    for p in list_ports.comports():
        if p.vid == 0x1A86 or any(n in p.device for n in names):
            return p.device
    raise LinkError("No Arduino found on USB. Check the cable carries data and the Nano's light is on.")


def _read_line(ser, timeout):
    """Next non-empty text line from the bridge, or '' on timeout."""
    deadline = time.monotonic() + timeout
    buf = bytearray()
    while time.monotonic() < deadline:
        c = ser.read(1)
        if not c:
            continue
        if c == b"\n":
            line = buf.decode("ascii", "replace").strip()
            if line:
                return line
            buf.clear()
        else:
            buf += c
    return buf.decode("ascii", "replace").strip()


def _wait_for_line(ser, marker, timeout):
    """First line containing `marker` (skips boot noise), or None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = _read_line(ser, deadline - time.monotonic())
        if marker in line:
            return line[line.index(marker):]
    return None


def _explain_probe(probe, inverted):
    try:
        pct = int(probe.split()[-1])
    except (ValueError, IndexError):
        return "could not read"
    if inverted:
        if pct < 10:
            return "line idles LOW: looks right for OBD1 with the key ON"
        if pct > 90:
            return "line idles HIGH: key OFF, SCI wires swapped, or not connected"
        return "line is busy or noisy: check the ground wire"
    if pct > 90:
        return "line idles HIGH: looks right for normal logic"
    return "line does not idle HIGH: this PCM probably needs inverted (OBD1) mode"


# --- simulated Jeep for testing without the vehicle ---------------------------

class FakeBridge:
    """Pretends to be the Arduino bridge plugged into an idling 1994 4.0L."""

    def __init__(self, pcm_nibble_swap=False):
        self.timeout = 0.005
        self.dtr = True
        self.swap = pcm_nibble_swap
        self.bridging = False
        self.state = "cmd"
        self.rx = bytearray(b"XJBRIDGE 1.0 (DEMO)\r\n")
        self.lock = threading.Lock()
        self.line = b""
        self.codes = [0x1C, 0x29]  # demo stored codes
        self.t0 = time.monotonic()

    def _emit(self, *values):
        for v in values:
            self.rx.append(swap_nibbles(v) if self.swap else v)

    def _value(self, pid):
        t = time.monotonic() - self.t0
        rpm = 720 + 40 * random.random()
        warm = min(1.0, t / 120)
        table = {
            0x11: rpm / 32,
            0x05: 128 + (25 + 63 * warm),           # 77 °F -> 190 °F
            0x1B: 128 + 32,
            0x07: 0.78 / 0.0196,
            0x08: 0.76 / 0.0196,
            0x0B: (4.6 + 0.3 * random.random()) / 0.059756,
            0x0F: 14.5 / 0.059756,
            0x02: (0.1 if int(t * 1.5) % 2 else 0.8) / 0.0196,
            0x0A: 14.1 / 0.0625,
            0x24: 14.2 / 0.0625,
            0x15: 12 / 0.5,
            0x0C: 32,
            0x41: 0,
            0x3B: 0x02 if warm > 0.4 else 0x01,
            0x0E: 2,
            0x06: 1.8 / 0.0196,
            0x1C: 2.9 / 0.0196,
            0x40: 1.4 / 0.0196,
            0x42: 0xB1 if int(t * 1.5) % 2 == 0 else 0xA0,
            0x12: 0x10,
        }
        return int(table.get(pid, 0)) & 0xFF

    def write(self, data):
        with self.lock:
            for raw in data:
                if not self.bridging:
                    self._command_byte(raw)
                    continue
                time.sleep(0.0013)  # one byte at 7812.5 baud
                b = swap_nibbles(raw) if self.swap else raw
                if self.state == "pid":
                    self._emit(b, *[self._value(b)] * 3)
                    self.state = "stream"
                elif self.state == "stream" and b == 0x00:
                    self._emit(0x00)
                    self.state = "cmd"
                else:
                    self._emit(b)
                    if b == 0x14:
                        self.state = "pid"
                    elif b == 0x10:
                        body = [0x10] + self.codes + [0xFD]
                        self._emit(*body[1:], sum(body) & 0xFF)
                        self.state = "cmd"
                    elif b == 0x17:
                        self.codes = []
                        self._emit(0xE0)
                        self.state = "cmd"
                    else:
                        self.state = "cmd"
        return len(data)

    def _command_byte(self, c):
        if c != ord("\n"):
            self.line += bytes([c])
            return
        cmd, self.line = self.line.strip(), b""
        if cmd == b"PROBE":
            self.rx += b"IDLE HIGH% 0\r\n"
        elif cmd in (b"GO I", b"GO N"):
            self.rx += b"OK INVERTED\r\n" if cmd == b"GO I" else b"OK NORMAL\r\n"
            self.bridging = True
        else:
            self.rx += b"ERR\r\n"

    def read(self, n=1):
        deadline = time.monotonic() + (self.timeout or 0)
        while True:
            with self.lock:
                if self.rx:
                    out = bytes(self.rx[:n])
                    del self.rx[:n]
                    return out
            if time.monotonic() >= deadline:
                return b""
            time.sleep(0.001)

    def reset_input_buffer(self):
        with self.lock:
            self.rx.clear()

    def close(self):
        pass
