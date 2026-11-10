"""Summarize an xj_scan CSV: a timeline every N seconds plus O2 behaviour over the last window.

    python3 tools/summarize.py pc/logs/xj_XXXX.csv [step_seconds] [window_seconds]
"""

import csv
import sys

path = sys.argv[1]
step = float(sys.argv[2]) if len(sys.argv) > 2 else 30
window = float(sys.argv[3]) if len(sys.argv) > 3 else 60

rows = list(csv.DictReader(open(path, encoding="utf-8")))
cols = {
    "rpm": "Engine speed (rpm)", "ect": "Coolant temp (°F)", "iat": "Intake air temp (°F)",
    "map": "MAP (manifold pressure) (psi)", "o2": "Upstream O2 sensor (V)", "o2s": "Upstream O2 state",
    "spk": "Spark advance (deg)", "iac": "Target IAC position (steps)", "mph": "Vehicle speed (mph)",
    "ltft": "Long-term fuel trim (%)", "tps": "Throttle position sensor (V)", "bat": "Battery voltage (V)",
}
extra = [k for k in rows[0] if k.startswith("PID ")]


def g(r, k):
    return r.get(cols.get(k, k), "")


print(f"{path}: {len(rows)} rows, {rows[0]['elapsed_s']}–{rows[-1]['elapsed_s']} s")
hdr = f"{'t':>6} {'rpm':>5} {'ect':>4} {'iat':>4} {'map':>5} {'tps':>5} {'o2':>5} {'o2s':>6} {'spk':>5} {'iac':>4} {'mph':>3} {'ltft':>5} {'bat':>5}  " + " ".join(k.replace('PID ', '').replace(' (raw)', '') for k in extra)
print(hdr)
next_t = 0.0
for r in rows:
    t = float(r["elapsed_s"])
    if t >= next_t or r is rows[-1]:
        next_t = t + step
        print(f"{t:6.0f} {g(r,'rpm'):>5} {g(r,'ect'):>4} {g(r,'iat'):>4} {g(r,'map'):>5} {g(r,'tps'):>5} {g(r,'o2'):>5} {g(r,'o2s'):>6} {g(r,'spk'):>5} {g(r,'iac'):>4} {g(r,'mph'):>3} {g(r,'ltft'):>5} {g(r,'bat'):>5}  "
              + " ".join(f"{r[k]:>3}" for k in extra))

end = float(rows[-1]["elapsed_s"])
last = [r for r in rows if float(r["elapsed_s"]) >= end - window and g(r, "o2")]
if last:
    o2 = [float(g(r, "o2")) for r in last]
    crossings = sum(1 for a, b in zip(o2, o2[1:]) if (a - 0.45) * (b - 0.45) < 0)
    states = {}
    for r in last:
        states[g(r, "o2s")] = states.get(g(r, "o2s"), 0) + 1
    print(f"\nLast {window:.0f} s ({len(o2)} samples): O2 min {min(o2):.2f} max {max(o2):.2f} "
          f"mean {sum(o2)/len(o2):.2f} V, crossings of 0.45 V: {crossings}, states {states}")
