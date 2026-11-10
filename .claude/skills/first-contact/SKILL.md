---
name: first-contact
description: Debug a hookup that is wired but not talking to the engine computer - no bridge, line idles HIGH, no echo, or nonsense values. Use when the first reading fails or a working setup stops answering.
---

# It's wired but nothing answers

Find which layer is broken before changing anything. Go in this order and stop at the first one that fails.

## 1. Laptop ↔ Nano

`.venv/bin/python pc/xj_scan.py --cli auto --codes` and read the first lines.

- `No Arduino found on USB`: cable or port. `ls /dev/cu.*` before and after plugging in.
- `No bridge answered`: the sketch isn't on the Nano, or something else holds the port. Re-upload `arduino/xj_bridge`.
- `Bridge found: XJBRIDGE 1.0`: this layer is fine.

## 2. The idle level

The scanner prints `PCM transmit line idle check: IDLE HIGH% n`.

- **Near 0, "idles LOW"**: the computer is powered and wire A is connected. Go to 3.
- **Near 100, "idles HIGH"**: one of: key is off; wire A isn't touching in its cavity; wires A and B are swapped. Have them check the key, reseat wire A, and re-measure cavities 3 and 4 with the meter (5 V is B, 0 V is A).
- **Never LOW and there is a resistor from D10 to 5 V**: remove it. That pull-up is what blocked the first attempt on the test car; see [docs/wiring.md](../../../docs/wiring.md).
- **In between, "busy or noisy"**: ground. Check wire C end to end.

## 3. Echo

- `No echo for byte 14`: the computer isn't hearing the Nano. Wire B (D11 to the 5 V cavity) or ground. Check continuity from the spade to the Nano pin.
- `Echo mismatch`: try `--byte-order swap`.
- Echo works but values are wild (battery 3 V or 40 V): byte order again, `--byte-order swap` or `normal`.

## 4. Look at the wire itself

When the steps above don't explain it, upload `arduino/xj_sniff` and run `.venv/bin/python tools/sniff.py`. It sends `14`, `0A` and `10` in both polarities and prints what came back on D10.

- An echo of the sent byte in inverted polarity: wiring is right.
- Edges but garbage: wrong polarity or a bad ground.
- No edges at all: wire A or B isn't connected to the computer.

Upload `arduino/xj_bridge` again afterwards.

## 5. It worked and then stopped

Almost always a spade terminal that backed out, or the key got turned off. Reseat, key ON, run `--codes` again.

Full symptom table: [docs/troubleshooting.md](../../../docs/troubleshooting.md).
