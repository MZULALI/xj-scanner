"""Ask the PCM for every parameter ID in a range and print which ones answer, with the raw byte.

    .venv/bin/python tools/pid_sweep.py          # 01-5F
    .venv/bin/python tools/pid_sweep.py 60 FF    # the rest
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pc"))

from xj_protocol import PARAMS_BY_PID, Link, LinkError  # noqa: E402

link = Link.open("auto", inverted=True, on_info=lambda s: None)
try:
    lo = int(sys.argv[1], 16) if len(sys.argv) > 2 else 0x01
    hi = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x5F
    for pid in range(lo, hi + 1):
        try:
            raw = link.read_raw(pid)
        except LinkError as e:
            print(f"{pid:02X}  --  {e}")
            continue
        p = PARAMS_BY_PID.get(pid)
        known = f"{p.name}: {p.decode(raw)}{p.unit}" if p else ""
        print(f"{pid:02X}  raw {raw:3d} (0x{raw:02X})  {known}")
finally:
    link.close()
