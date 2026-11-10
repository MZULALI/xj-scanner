"""Break a drive log into speed bands and report load, O2 behaviour and fuel trim in each.

    python3 tools/drive_report.py pc/logs/xj_XXXX.csv [speed_scale]

speed_scale multiplies the logged vehicle speed (0.5 if this PCM reports half-mph units).
"""

import csv
import sys

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
SPEED_SCALE = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
C = {
    "t": "elapsed_s", "rpm": "Engine speed (rpm)", "mph": "Vehicle speed (mph)", "tps": "Throttle position sensor (V)",
    "map": "MAP (manifold pressure) (psi)", "o2": "Upstream O2 sensor (V)", "o2s": "Upstream O2 state",
    "spk": "Spark advance (deg)", "ltft": "Long-term fuel trim (%)", "ect": "Coolant temp (°F)", "iac": "Target IAC position (steps)",
}
data = []
for r in rows:
    try:
        d = {k: (r[v] if k == "o2s" else float(r[v])) for k, v in C.items()}
        d["mph"] *= SPEED_SCALE
        data.append(d)
    except (ValueError, KeyError):
        pass

print(f"{len(data)} usable rows, {data[0]['t']:.0f}–{data[-1]['t']:.0f} s, "
      f"coolant {min(d['ect'] for d in data):.0f}–{max(d['ect'] for d in data):.0f} °F")

# timeline every ~10 s
print("\n   t  mph   rpm   tps   map    o2  state   spk  ltft")
nxt = 0
for d in data:
    if d["t"] >= nxt:
        nxt = d["t"] + 10
        print(f"{d['t']:4.0f} {d['mph']:4.0f} {d['rpm']:5.0f} {d['tps']:5.2f} {d['map']:5.2f} {d['o2']:5.2f} {d['o2s']:>6} {d['spk']:5.1f} {d['ltft']:5.1f}")


def band(name, sel):
    ds = [d for d in data if sel(d)]
    if not ds:
        print(f"\n{name}: no rows")
        return
    o2 = [d["o2"] for d in ds]
    rich = sum(1 for v in o2 if v > 0.55)
    lean = sum(1 for v in o2 if v < 0.35)
    cross = sum(1 for a, b in zip(ds, ds[1:]) if b["t"] - a["t"] < 2 and (a["o2"] - 0.45) * (b["o2"] - 0.45) < 0)
    secs = sum(b["t"] - a["t"] for a, b in zip(ds, ds[1:]) if b["t"] - a["t"] < 2)

    def avg(k):
        return sum(d[k] for d in ds) / len(ds)

    print(f"\n{name}: {len(ds)} rows (~{secs:.0f} s)")
    print(f"  rpm {avg('rpm'):.0f}  tps {avg('tps'):.2f} V  MAP {avg('map'):.2f} psi (vacuum {14.7 - avg('map'):.1f} psi)  spark {avg('spk'):.1f}°")
    print(f"  O2 mean {sum(o2)/len(o2):.2f} V, min {min(o2):.2f}, max {max(o2):.2f}; rich {100*rich/len(o2):.0f}%, lean {100*lean/len(o2):.0f}%, "
          f"crossings {cross} ({60*cross/secs:.0f}/min at ~1.5 samples/s)" if secs else "")
    print(f"  LTFT {min(d['ltft'] for d in ds):.1f}–{max(d['ltft'] for d in ds):.1f} %")


band("Stopped / idle (0 mph)", lambda d: d["mph"] == 0)
band("Crawl (1–9 mph)", lambda d: 1 <= d["mph"] <= 9)
band("~15 mph (11–19)", lambda d: 11 <= d["mph"] <= 19)
band("~25 mph (21–30)", lambda d: 21 <= d["mph"] <= 30)
band("Above 30 mph", lambda d: d["mph"] > 30)
band("Decel (closed throttle, moving)", lambda d: d["mph"] > 5 and d["tps"] < 0.75)

lt = [(d["t"], d["ltft"]) for d in data]
changes = [(t, v) for (t, v), (_, p) in zip(lt[1:], lt) if v != p]
print(f"\nLTFT changes during the drive: {changes or 'none'}")
