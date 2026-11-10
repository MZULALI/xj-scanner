# For the agent

You are helping someone connect a laptop to the engine computer of a 1991–95 Jeep (Chrysler SBEC, OBD1) through an Arduino Nano, and then read it. The person may never have used a breadboard or a multimeter. Go one step at a time, wait for them to report what they see, and explain in plain words.

## Start here

| The person wants to… | Follow |
|---|---|
| Set it up for the first time | [.claude/skills/hookup/SKILL.md](.claude/skills/hookup/SKILL.md) |
| Read codes, watch live data, log a drive | [.claude/skills/scan/SKILL.md](.claude/skills/scan/SKILL.md) |
| Fix "it's wired but nothing answers" | [.claude/skills/first-contact/SKILL.md](.claude/skills/first-contact/SKILL.md) |

Reference, read when a step needs it:

- [docs/connector.md](docs/connector.md): the plug, cavity by cavity, with the measured voltages
- [docs/wiring.md](docs/wiring.md): Nano pins, the breadboard layout, the resistor question
- [docs/protocol.md](docs/protocol.md): how the SCI line works and every command the tools send
- [docs/parameters.md](docs/parameters.md): every parameter this computer answers, scaling, known quirks
- [docs/troubleshooting.md](docs/troubleshooting.md): symptoms and fixes

## Rules

1. **Never let anything be connected to a 12 V cavity.** On the test car that is cavity 6. Have the person measure every cavity with the key ON before any wire goes in. Wire color is not evidence: ground and the 12 V cavity share a color on the test car.
2. **Every measurement in this repo comes from one car** (1994 Cherokee XJ 4.0L, PCM 56030117). Treat it as what to expect, then confirm on theirs. If their numbers differ, stop and work out why before connecting.
3. **Prove the laptop side first.** Run `pc/xj_scan.py --cli DEMO` before touching the car, so a later failure can only be wiring.
4. **Reading is safe; three things are not just reading.** Ask before each one, and say what it does:
   - erasing fault codes (`17`) also clears what the computer has learned about fuel;
   - `23 02` resets the learned fuel trim;
   - actuator tests (`--actuator`) switch real hardware: the fuel pump, injectors, coils, fans. Key on, engine off, short runs, and tell them what will click or spray first.
5. **Don't guess at a diagnosis.** Report what the data shows and what it doesn't. A reading that looks wrong may be a scaling quirk; check [docs/parameters.md](docs/parameters.md) (fuel trim and vehicle speed both have one).
6. Logs go to `pc/logs/`. Don't commit them unless asked.

## Commands you will use

```sh
python3 -m venv .venv && .venv/bin/pip install -r pc/requirements.txt
.venv/bin/python pc/xj_scan.py --cli DEMO            # simulated Jeep
.venv/bin/python pc/xj_scan.py --cli auto            # codes, then live data to pc/logs/xj_<date>.csv
.venv/bin/python pc/xj_scan.py --cli auto --codes    # fault codes only
.venv/bin/python pc/xj_scan.py --cli auto --o2       # O2 sensor only, ~20 readings a second
.venv/bin/python pc/xj_scan.py --cli auto --all      # everything this computer answers
.venv/bin/python tools/summarize.py pc/logs/xj_XXXX.csv
```

`auto` finds the Nano's serial port. Close anything else that has the port open (Arduino's Serial Monitor) first.
