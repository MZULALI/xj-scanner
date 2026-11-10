# How the computer talks (SCI, OBD1)

1991–95 Jeep/Chrysler engine computers of the SBEC family have a serial diagnostic line called **SCI**. It is what the dealer's DRB scan tool used.

## The line

- **7812.5 baud**, 8 data bits, no parity, 1 stop bit.
- **Electrically inverted** compared to a normal serial port: the line idles LOW with the key on, and a start bit is a HIGH. The Nano handles this in software (`SoftwareSerial` with inverse logic), so no inverter chip is needed.
- Two data wires. The computer listens on one (PCM receive, about 5 V at rest) and answers on the other (PCM transmit, about 0 V at rest), plus ground.
- **Every byte you send is echoed back** by the computer. The tools send one byte, wait for its echo, then send the next. Bursts get dropped.
- Some computers send their bytes with the two 4-bit halves swapped. The scanner detects this by checking that the battery voltage reads sanely (`--byte-order auto`); the test car is normal order.

## The bridge (Nano) side

The Nano runs `arduino/xj_bridge`. Over USB at 115200 baud it prints `XJBRIDGE 1.0` on reset and accepts three text commands:

| Command | Reply | Meaning |
|---|---|---|
| `PROBE` | `IDLE HIGH% n` | how often the PCM transmit line read high over 200 ms. Connected with key ON it should be near 0. Unconnected it is 100. |
| `GO I` | `OK INVERTED` | start passing bytes both ways, inverted logic (use this for OBD1) |
| `GO N` | `OK NORMAL` | same, normal logic |

After `GO`, every byte passes straight through until the Nano is reset.

## Commands the tools send to the computer

All values hex. "Echo" means the computer repeats the byte back.

| Send | What happens | Used by |
|---|---|---|
| `10` | Fault codes: replies `10`, one byte per code, then end markers (`FE`/`FD`) and a checksum (sum of the bytes before it, low 8 bits). `10 FE 0E` means no codes. | `--codes` |
| `14 <id>` | Read one live parameter. Each byte is echoed, then the computer repeats the value byte until it receives `00`. | everything live |
| `15 <hi> <lo>` | Read one byte of the computer's memory at that address. Read-only. | `tools/romcheck.py` |
| `13 <id>` / `13 00` | Start / stop an actuator test (fuel pump relay, an injector, a coil, a fan…). The list is `ACTUATOR_TESTS` in `pc/xj_protocol.py`. | `--actuator` |
| `17` | Erase stored fault codes. Also clears learned values. | window button |
| `19 <rpm/8>` | Ask the computer to hold an idle speed. Must be resent about twice a second; it returns to its own idle when you stop. Park only. | `--idle` |
| `23 02` | Reset the learned long-term fuel trim to neutral (128). Replies `F0`. | `--send "23 02"` |
| `1A <id>` | Switch tests (from ChryslerScanner's table). | `--send` |

`--send "<hex bytes>"` sends anything by hand and prints the reply.

## Reading a parameter, byte by byte

```
laptop → 14        computer → 14      (echo)
laptop → 0A        computer → 0A      (echo)
                   computer → C6      (the value: battery, 0xC6 × 0.0625 = 12.38 V)
                   computer → C6 C6…  (repeats)
laptop → 00                           (stop)
```

A full row of about 12 parameters takes roughly half a second. `--o2` reads one parameter about 20 times a second.

## The computer's memory

`15 <hi> <lo>` reads any address, so the whole 32 KB program ($8000–$FFFF) can be copied out one byte at a time; it takes about 18 minutes (`tools/romcheck.py --dump`). The part number is stored at $8002–$8005 as digits (`56 03 01 17` on the test car). The program is the manufacturer's code: keep your copy to yourself.
