---
name: scan
description: Read fault codes and live data from the Jeep's engine computer, log a drive, and summarize what the log shows. Use once the hookup works and the person wants to check on or diagnose the engine.
---

# Read the Jeep

The scanner is `pc/xj_scan.py`. Run it from the repo root with the venv's Python. `auto` finds the Nano. Key ON for everything; engine running only where it says so.

## Common asks

| They ask | Run | Then |
|---|---|---|
| "Any codes?" | `.venv/bin/python pc/xj_scan.py --cli auto --codes` | Give each code with its description. `10 FE 0E` means none |
| "How's it running?" | `... --cli auto --seconds 30` (engine idling, warm) | Report rpm, coolant, battery, O2 behavior, trim |
| "Watch the O2 sensor" | `... --cli auto --o2 --seconds 30` | A healthy warm sensor swings between about 0.1 and 0.9 V several times in 10 s |
| "Log my drive" | `... --cli auto --all` and Ctrl+C at the end | The CSV path is printed at the start. Laptop on the passenger seat, they drive, you read afterwards |
| "What does this computer support?" | `.venv/bin/python tools/pid_sweep.py` | Lists every parameter that answers |
| "Summarize that log" | `.venv/bin/python tools/summarize.py pc/logs/xj_XXXX.csv` | Timeline plus O2 behavior |
| "Break the drive down by speed" | `.venv/bin/python tools/drive_report.py pc/logs/xj_XXXX.csv 0.5` | The `0.5` halves the doubled speed reading |

Logs are plain CSV, one row per pass, one column per parameter. Read them yourself for anything the helpers don't cover.

## Reading the numbers honestly

Before interpreting, read [docs/parameters.md](../../../docs/parameters.md). The two that mislead:

- **Fuel trim** is counts from 128, 0.26 % each, clamped to −5.2 %…+10.4 %. A tool that shows "+22 %" for this computer is using the wrong formula.
- **Speed** reads about double on the test car.

Say what the data shows and what it can't show. This computer has no closed-loop flag, no downstream O2 sensor and no misfire counter. A drive log covers the load and speed they actually drove, nothing else.

## Things that change the car: ask first

- **Erase codes** (window button, or `--send "17"`): also resets learned fuel trim.
- **Reset fuel trim** (`--send "23 02"`): the engine relearns over the next drive.
- **Actuator tests** (`--actuator <id> --seconds N`): key on, engine off. The list is `ACTUATOR_TESTS` in `pc/xj_protocol.py` (`33` fuel pump relay, `04`–`06` and `1D`–`1F` injectors 1–6, `01`–`03` coils). The tool refuses if the engine is running. Tell the person what will click, buzz or spray, keep runs short (the fuel pump test pressurizes the rail and an injector test sprays fuel into the intake), and stop on request: Ctrl+C sends the stop command.
- **Hold idle** (`--idle <rpm>`): in park only.
