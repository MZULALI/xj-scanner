# Troubleshooting

Work down the list; each step rules out everything above it.

| What you see | Likely cause | Fix |
|---|---|---|
| `No Arduino found on USB` | Charge-only cable, or the Nano's USB chip isn't seen | Try another cable or a USB-A adapter. `ls /dev/cu.*` should show `usbserial-…` or `wchusbserial-…` |
| Upload fails with "not in sync" | Wrong bootloader setting | Switch between `cpu=atmega328old` and `cpu=atmega328` |
| `No bridge answered` | Sketch not uploaded, or another program has the port | Upload `arduino/xj_bridge`; close Arduino's Serial Monitor |
| Idle check: `line idles HIGH` | Key is off, wires A and B swapped, or wire A not touching | Key ON. Reseat the terminals. Re-measure cavities 3 and 4 |
| Idle LOW but `No echo for byte 14` | Wire B (to D11) not reaching the computer, wires A and B swapped, or bad ground | Check continuity plug-to-Nano on B and C; re-measure which cavity is which |
| Idle check never goes LOW and a 1 kΩ pull-up is fitted on D10 | The pull-up overpowers the computer's transmit line | Remove the pull-up (see [wiring.md](wiring.md)) |
| Echo works, values are nonsense | Byte order | Add `--byte-order swap` (or `normal`) |
| A parameter is always blank or 0 | This computer doesn't report it | See [parameters.md](parameters.md) |
| Fuel trim looks like a huge + or − percent | Wrong formula from another tool | It's counts from 128 at 0.26 % each, see [parameters.md](parameters.md) |
| Speed is about double | Known on the test car | Halve it |
| It worked, then stopped after moving wires | A spade terminal backed out | Push each terminal fully home |

## When the table doesn't solve it

Use the debug sketch: upload `arduino/xj_sniff`, run `.venv/bin/python tools/sniff.py`. It sends a byte in each polarity and prints exactly what came back on D10, as edge timings decoded into bytes. An echo of what you sent, in inverted polarity, means the wiring is right and the problem is in software. Nothing at all means wire A, wire B or ground. Upload `arduino/xj_bridge` again when you're done.

`tools/pid_sweep.py` asks for every parameter ID and prints which ones answer. Use it on a car that isn't the test car to see what its computer supports.
