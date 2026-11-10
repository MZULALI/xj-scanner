"""Read the PCM's own program with command 15 HI LO and check it against the 1994 Cherokee 4.0
automatic EPROM 56029009 (github.com/AR1972/jeep_2.5L): the fuel-trim (PID 0E) code, its limits,
and the math that sets the scale. Key on, engine off. Read-only: nothing is written to the PCM.

    .venv/bin/python tools/romcheck.py          # part number + check, a few seconds
    .venv/bin/python tools/romcheck.py --dump   # also save the whole 32 KB program
                                               # to data/ (resumes if interrupted; ~18 min)
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "pc"))

from xj_protocol import BYTE_TIMEOUT, Link, LinkError  # noqa: E402

# (start address, expected bytes from EPROM 56029009, what it is)
CHECKS = [
    (0xCCD1, "0A 0B", "PID 0D reads RAM $0A, PID 0E reads RAM $0B"),
    (0xCF43, "C1 40 24 18 C1 00 27 F5 C1 2D 22 F1 CE CC C4 4F 3A E6 00 C1 FF 27 E6 8F A6 00 20 6A",
     "14 PID handler (looks up that table)"),
    (0xCAB6, "86 80 97 0A 97 0B 20 F3", "23 02 reset: $0A and $0B = 128, reply F0"),
    (0x8633, "A8 6C", "trim limits: 168 max, 108 min"),
    (0xC142, "D6 0B F1 86 34 25 05 F1 86 33 23 06 86 80 97 0B", "learning code checks $0B against those limits"),
    (0xC5CA, "CE 60 8F 86 01 D6 81 FD 60 8F D6 82 BD E4 40 FD 60 8F 86 01 D6 0B BD E4 40 FD 60 8F "
             "86 01 D6 83 BD E4 40 FD 60 8F 18 8F 96 84 BD E3 64 18 8F 05 05 F3 60 8F DD 75 39",
     "fuel multiplier: x (1 + $0B/256), with the O2 short-term value $83 the same way"),
    (0xE440, "36 17 1A EE 00 BD E3 64 32 4D 18 8F 27 07 E3 00 24 03 CC FF FF", "multiply by (1 + value/256)"),
    (0xE364, "36 18 3C 33 3D 18 8F 33 32 3D 89 00 16 18 3A 18 3C 18 38 39", "value/256 math"),
]


def read_mem(link, addr, tries=3):
    for attempt in range(tries):
        try:
            link.ser.reset_input_buffer()
            link._send_with_echo(0x15)
            link._send_with_echo(addr >> 8)
            link._send_with_echo(addr & 0xFF)
            value = link._get(BYTE_TIMEOUT)  # sent once; the next read's buffer reset drops any stray byte
            if value is None:
                raise LinkError(f"No value for address {addr:04X}")
            return value
        except LinkError:
            if attempt == tries - 1:
                raise
            time.sleep(0.1)


def main():
    link = Link.open("auto", inverted=True, on_info=lambda s: None)
    try:
        pn = [read_mem(link, a) for a in range(0x8002, 0x8006)]
        part = "".join(f"{b:02X}" for b in pn)
        print(f"PCM part number (ROM $8002-$8005): {part}   (repo file: 56029009)")
        mismatches = 0
        for start, hexbytes, what in CHECKS:
            want = bytes.fromhex(hexbytes)
            got = bytes(read_mem(link, start + i) for i in range(len(want)))
            ok = got == want
            mismatches += not ok
            print(f"{'MATCH   ' if ok else 'DIFFERENT'} ${start:04X}  {what}")
            if not ok:
                print(f"           expected {want.hex(' ').upper()}\n           got      {got.hex(' ').upper()}")
        print("\nAll match: 0E scale = 1/384 = 0.26 % fuel per count, limits 108-168." if not mismatches else
              f"\n{mismatches} block(s) differ: run with --dump so the whole program can be searched.")

        if "--dump" in sys.argv:
            os.makedirs(os.path.join(HERE, "..", "data"), exist_ok=True)
            path = os.path.join(HERE, "..", "data", f"pcm_rom_{part}.bin")
            done = os.path.getsize(path) if os.path.exists(path) else 0
            start = time.monotonic()
            with open(path, "ab") as f:
                for addr in range(0x8000 + done, 0x10000):
                    f.write(bytes([read_mem(link, addr)]))
                    n = addr - 0x8000 + 1
                    if n % 512 == 0:
                        f.flush()
                        rate = (n - done) / (time.monotonic() - start)
                        print(f"  {n}/32768 bytes, ~{(32768 - n) / rate / 60:.0f} min left", flush=True)
            print(f"Saved {path}")
    finally:
        link.close()


if __name__ == "__main__":
    try:
        main()
    except LinkError as e:
        sys.exit(f"ERROR: {e}")
