"""Drive xj_sniff.ino: send bytes in each polarity and decode what the PCM put on D10.

    .venv/bin/python tools/sniff.py            # default test: 14, 0A, 10 in both polarities
    .venv/bin/python tools/sniff.py N 14       # one byte, one polarity

The port is the first /dev/cu.usbserial* or /dev/cu.wchusbserial* device; set XJ_PORT to pick another.
"""

import glob
import os
import sys
import time

import serial

PORT = os.environ.get("XJ_PORT") or next(iter(sorted(glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.wchusbserial*"))), None)
if not PORT:
    sys.exit("No Arduino found on USB. Set XJ_PORT to its serial port.")
BIT = 32  # ticks per bit (4 us ticks, 7812.5 baud)


def level_at(start, edges, t):
    """Line level at tick t, given the starting level and edge times."""
    lvl = start
    for e in edges:
        if e > t:
            break
        lvl ^= 1
    return lvl


def decode(start, edges, end_tick, idle):
    """UART frames found on the line, assuming `idle` is the resting level (1 normal, 0 inverted)."""
    out = []
    i = 0
    while i < len(edges):
        e = edges[i]
        # a start bit is an edge away from idle
        if level_at(start, edges, e) != idle and e + 10 * BIT <= end_tick:
            bits = [level_at(start, edges, e + BIT // 2 + BIT * (k + 1)) for k in range(8)]
            if idle == 0:
                bits = [1 - b for b in bits]
            stop = level_at(start, edges, e + BIT // 2 + BIT * 9)
            val = sum(b << k for k, b in enumerate(bits))
            out.append((e * 4, val, "ok" if stop == idle else "bad stop"))
            nxt = e + 10 * BIT - BIT // 2
            while i < len(edges) and edges[i] < nxt:
                i += 1
            continue
        i += 1
    return out


def run(s, cmd):
    s.reset_input_buffer()
    s.write((cmd + "\n").encode())
    deadline = time.monotonic() + 2
    line = b""
    while time.monotonic() < deadline and not line.endswith(b"\n"):
        line += s.read(4096)
    text = line.decode(errors="replace").strip()
    if not text.startswith("CAP"):
        return text
    parts = dict(p.split("=", 1) for p in text.split()[1:])
    start, end = int(parts["start"]), int(parts["end"])
    edges = [int(x) for x in parts["t"].split(",") if x]
    summary = f"start={start} edges={len(edges)} end={end}"
    if edges:
        summary += f"  first edges (us): {[e * 4 for e in edges[:12]]}"
        for idle, name in ((1, "as normal"), (0, "as inverted")):
            frames = decode(start, edges, 60000, idle)
            if frames:
                summary += f"\n      {name}: " + " ".join(f"{v:02X}@{t}us({q})" for t, v, q in frames[:12])
    return summary


def main():
    s = serial.Serial(PORT, 115200, timeout=0.05)
    t = time.monotonic()
    buf = b""
    while time.monotonic() - t < 4 and b"XJSNIFF" not in buf:
        buf += s.read(64)
    print("banner:", buf.decode(errors="replace").strip())
    print("W (just listen):", run(s, "W"))
    if len(sys.argv) == 3:
        cmds = [f"{sys.argv[1]} {sys.argv[2]}"]
    else:
        cmds = [f"{m} {b}" for m in ("N", "I") for b in ("14", "0A", "10")]
    for cmd in cmds:
        print(f"{cmd}:", run(s, cmd))
        time.sleep(0.2)
    s.write(b"Z\n")
    s.close()


if __name__ == "__main__":
    main()
