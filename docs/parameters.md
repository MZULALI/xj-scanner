# Parameters

What the test car's computer (1994 Cherokee 4.0L, PCM 56030117) answers to `14 <id>`, and how each raw byte becomes a number. The table in code is `PARAMS` in `pc/xj_protocol.py`. Names and formulas come from ChryslerScanner unless noted.

## Logged by default

| ID | Name | Scaling (raw = one byte, 0–255) |
|---|---|---|
| 11 | Engine speed | raw × 32 rpm |
| 05 | Coolant temperature | 1.8 × (raw − 128) + 32 °F |
| 1B | Intake air temperature | same as coolant |
| 07 | Throttle position sensor | raw × 0.0196 V |
| 0B | MAP (manifold pressure) | raw × 0.059756 psi |
| 02 | Upstream O2 sensor | raw × 0.0196 V |
| 0A | Battery voltage | raw × 0.0625 V |
| 15 | Spark advance | raw × 0.5 degrees |
| 0C | Target idle air (IAC) position | raw steps |
| 41 | Vehicle speed | raw mph. **Reads double on the test car**, see below |
| 0E | Long-term fuel trim | raw − 128 counts. See below |
| 3B | Fuel system status | **does not answer** on this computer |

## Also answer (use `--all` or `--pids`)

| ID | Name | Scaling |
|---|---|---|
| 08 | Minimum TPS voltage | × 0.0196 V (reads 1.02 V while closed throttle is 0.63 V; unexplained) |
| 06, 1C, 40, 01, 09 | Coolant, intake air, MAP, battery-temp and knock sensor voltages | × 0.0196 V |
| 0F | Barometric pressure | × 0.059756 psi |
| 45 | MAP vacuum | × 0.059756 psi (matches baro − MAP) |
| 24 | Target charging voltage | × 0.0625 V |
| 2D | Ambient/battery temperature | as coolant |
| 42 | Upstream O2 state | A0 lean, B1 rich, FF center |
| 12 | Cam/crank sync | bit 4 set = in sync |
| 47 | Spark advance (second copy) | × 0.5 degrees |
| 46 | Delta throttle position | × 0.0196 V |
| 0D | Idle fuel adaptation | raw, 128 = neutral (same scale as 0E) |
| 10 | — | same byte as engine speed (rpm ÷ 32). The code labels it "Fuel command"; it isn't one |
| 13, 1E, 1F | Key-on cycles since errors 1–3 | raw count |
| 1D | Cruise set speed | × 0.5 mph |
| 20 | Cruise status | two 4-bit codes, decoded in `cruise_status()` |
| 27 | Theft alarm status | raw |
| 22, 23 | unknown | raw |

Neither fuel-system status ID (3B, 57) answers, so there is no "closed loop" flag. Closed loop shows up as the O2 voltage switching back and forth across about 0.45 V.

## Quirks that will mislead you

### Long-term fuel trim (0E) is not a percentage, and it is not signed the usual way

- **128 means no correction.** Below 128 the computer is removing fuel; above, adding.
- **One count is 1/384 of the fuel, about 0.26 %.** The multiplier is `(256 + raw) / 384`.
- The computer only lets it move between **108 and 168** (−5.2 % to +10.4 %).
- ChryslerScanner's formula treats the top bit as a sign and gives the opposite story: raw 110 comes out as "+21.6 %" when it really means −4.7 %. On the test car that wrong +22 % sent a whole day of testing after a fuel-delivery problem that didn't exist.
- The scanner logs it as *counts from 128* (so −18 for raw 110). Multiply by 0.26 for percent.
- This was settled from the computer's own code: the routine that applies the trim, and the reset command writing 128. `tools/romcheck.py` checks that your computer has the same code.

### Vehicle speed (41) reads double

On the test car the raw value is about twice the real speed (it showed 56 on a residential street). Halve it: `tools/drive_report.py <log> 0.5`. Check yours against the speedometer.

### Erasing codes resets learning

`17` (erase fault codes) and `23 02` both put the learned fuel trim back to 128. The engine then relearns over the next drive. Don't do either before a drive you want to compare with an earlier one.

## Fault codes

`10` returns one byte per stored code. Descriptions are in `pc/dtc_table.py`. Unplugging a sensor or injector with the engine running stores a code and turns the check-engine light on; erase it when you're done.
