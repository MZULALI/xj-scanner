---
name: hookup
description: Walk someone through connecting an Arduino Nano to a 1991-95 Jeep's diagnostic plug and getting the first reading from the engine computer. Use when they are setting this up for the first time or rebuilding the wiring.
---

# Hook the laptop up to the Jeep

Go one step at a time. After each step, wait for the person to tell you what they saw before moving on. They may be new to all of this: say what a thing is the first time you name it.

Read [docs/connector.md](../../../docs/connector.md) and [docs/wiring.md](../../../docs/wiring.md) before you start. Every number in them is from one car; the person's car has to confirm them.

## 1. Laptop side (no car needed)

```sh
python3 -m venv .venv && .venv/bin/pip install -r pc/requirements.txt
.venv/bin/python pc/xj_scan.py --cli DEMO --seconds 5
```

You should see `PCM is talking`, two made-up fault codes and rows of live values. If this fails, fix it here; nothing later will work without it.

## 2. Put the sketch on the Nano

```sh
brew install arduino-cli            # macOS; on other systems install arduino-cli their way
arduino-cli core install arduino:avr
ls /dev/cu.*                        # plug the Nano in; a new usbserial or wchusbserial device appears
arduino-cli compile --upload -p <that port> --fqbn arduino:avr:nano:cpu=atmega328old arduino/xj_bridge
```

- "not in sync" on upload: use `cpu=atmega328` instead.
- No new device when the Nano is plugged in: the cable is charge-only. Try another.

Check it: `.venv/bin/python pc/xj_scan.py --cli auto --codes`. With nothing wired it should find the bridge (`Bridge found: XJBRIDGE 1.0`), report the line idling HIGH, and then stop with a "no echo" error. That is correct for now: the Nano works and nothing is connected to it.

## 3. Build the three wires

Per [docs/wiring.md](../../../docs/wiring.md): wire A to D10, wire B to D11, wire C to GND, a spade terminal on the far end of each, **no resistors**. Label the wires A, B and C with tape. Then the bench checks at the bottom of that file (continuity end to end, no two wires touching).

## 4. Find the cavities with a meter

This is the step that protects the Nano and the car. Follow "How to identify the cavities on another car" in [docs/connector.md](../../../docs/connector.md). Have them read you the voltage in every cavity with the key ON and write the table down together:

- which one is ground (0 V and beeps to battery negative),
- which one sits near 5 V (PCM receive, wire B),
- which one sits near 0 V and is not ground, and does not jump when the key turns on (PCM transmit, wire A),
- which sit at 12 V (nothing goes there).

If their table doesn't match the test car's pattern, stop and say so. Don't guess.

## 5. Connect

Key OFF. Wire C into ground first, then B, then A. Push each spade fully in. Then key ON, engine off.

## 6. First contact

```sh
.venv/bin/python pc/xj_scan.py --cli auto --codes
```

Good: `line idles LOW: looks right for OBD1 with the key ON`, then `PCM is talking. Battery 12.xx V`, then the fault codes (or none).

Not good: go to the `first-contact` skill.

## 7. Show them something

```sh
.venv/bin/python pc/xj_scan.py --cli auto --seconds 20
```

Read a few values back in plain words: battery voltage, coolant temperature, whether any codes are stored. Mention the two quirks from [docs/parameters.md](../../../docs/parameters.md) (fuel trim, speed) before they draw conclusions from those numbers.

## For a permanent install

Route the wires through the firewall grommet the factory harness uses, keep the Nano inside the cab, and zip-tie it down.
