"""XJ Scan: live engine data from a 1991-1995 Jeep through an Arduino SCI bridge.

    python3 xj_scan.py                    window (pick the port, or DEMO to try it without the Jeep)
    python3 xj_scan.py --cli auto         text mode: finds the Nano, prints and logs live values
    python3 xj_scan.py --cli auto --o2    O2 sensor only, about 20 readings a second
    python3 xj_scan.py --cli DEMO         text mode against the simulated Jeep
"""

import argparse
import csv
import datetime
import os
import queue
import sys
import threading
import time

from xj_protocol import ACTUATOR_TESTS, PARAMS, PARAMS_BY_PID, Link, LinkError, describe_code, hexs

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


class CsvLog:
    def __init__(self, pids):
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(LOG_DIR, f"xj_{stamp}.csv")
        self.pids = list(pids)
        self.file = open(self.path, "w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        self.writer.writerow(["time", "elapsed_s"] + [PARAMS_BY_PID[p].label for p in self.pids])
        self.t0 = time.monotonic()

    def write(self, values):
        now = datetime.datetime.now().isoformat(timespec="milliseconds")
        row = [now, f"{time.monotonic() - self.t0:.2f}"] + [values.get(p, "") for p in self.pids]
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        self.file.close()


def connect(port, inverted, byte_order, info):
    """Open the bridge and settle the byte order. Returns a ready Link."""
    link = Link.open(port, inverted=inverted, on_info=info)
    if byte_order == "auto":
        swap, volts = link.detect_byte_order()
        if swap is None:
            info("Could not read battery voltage in either byte order. Check wiring (see README: troubleshooting).")
        else:
            info(f"PCM is talking. Battery {volts:.2f} V, byte order: {'nibble-swapped' if swap else 'normal'}")
    else:
        link.nibble_swap = byte_order == "swap"
    return link


# --- text mode ----------------------------------------------------------------

# --all: everything this 1994 PCM answers. Fast-changing readings every row; the slow ones take
# turns, SLOW_PER_ROW per row, so each still refreshes every few seconds without slowing O2/rpm.
ALL_FAST = [0x11, 0x02, 0x0B, 0x07, 0x10, 0x15, 0x41]
ALL_SLOW = [0x05, 0x1B, 0x0A, 0x0E, 0x0C, 0x42, 0x45, 0x47, 0x46, 0x20, 0x1D, 0x24, 0x08, 0x0F,
            0x06, 0x1C, 0x40, 0x2D, 0x13, 0x27, 0x0D, 0x22, 0x23, 0x1E, 0x1F]
SLOW_PER_ROW = 2


def run_cli(port, inverted, byte_order, codes_only, pids=None, seconds=None, slow_pids=None, idle_rpm=None,
            slow_per_row=SLOW_PER_ROW):
    link = connect(port, inverted, byte_order, print)
    try:
        try:
            codes, ok, raw = link.read_codes()
            print(f"Fault codes: {hexs(raw)}  checksum {'OK' if ok else 'BAD'}")
            for c in codes:
                print(f"  {c:02X}  {describe_code(c)}")
            if not codes:
                print("  none stored")
        except LinkError as e:
            print(f"Fault codes: could not read ({e})")
        if codes_only:
            return
        pids = pids or [p.pid for p in PARAMS if p.default_on]
        slow_pids = slow_pids or []
        log = CsvLog(pids + slow_pids)
        print(f"Logging to {log.path}  (Ctrl+C to stop)", flush=True)
        stop_at = time.monotonic() + seconds if seconds else None
        turn = 0
        try:
            while stop_at is None or time.monotonic() < stop_at:
                if idle_rpm:
                    # ChryslerScanner's "set idle speed": 19 <rpm/8>, resent every ~0.5 s; the PCM
                    # goes back to its own idle when the messages stop.
                    link.raw_send(bytes([0x19, min(255, idle_rpm // 8)]))
                batch = list(pids)
                if slow_pids:
                    batch += [slow_pids[(turn + i) % len(slow_pids)] for i in range(min(slow_per_row, len(slow_pids)))]
                    turn += slow_per_row
                values = {}
                for pid in batch:
                    try:
                        values[pid] = link.read_param(pid)
                    except LinkError as e:
                        values[pid] = ""
                        print(f"  {PARAMS_BY_PID[pid].name}: {e}")
                log.write(values)
                print(" | ".join(f"{PARAMS_BY_PID[p].name}: {values[p]}{PARAMS_BY_PID[p].unit}" for p in batch), flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            log.close()
            print(f"Saved {log.path}")
    finally:
        link.close()


def run_actuator(port, inverted, test_id, seconds, force):
    """Run one PCM actuator test for `seconds`, engine off unless forced, then stop it."""
    link = connect(port, inverted, "auto", print)
    try:
        rpm = link.read_param(0x11)
        if rpm > 0 and not force:
            sys.exit(f"Engine is running ({rpm} rpm). Actuator tests are for key on, engine off. "
                     "Use --force only if you know this test is safe with the engine running.")
        name = ACTUATOR_TESTS.get(test_id, "unknown test")
        print(f"Starting actuator test {test_id:02X} ({name}) for {seconds:.0f} s")
        print(f"  PCM replied: {hexs(link.actuator_start(test_id)) or 'nothing'}", flush=True)
        stop_at = time.monotonic() + seconds
        try:
            while time.monotonic() < stop_at:
                extra = link._collect(0.2, 0.05)
                if extra:
                    print(f"  PCM: {hexs(extra)}", flush=True)
        except KeyboardInterrupt:
            pass
        finally:
            print(f"Stopping: PCM replied {hexs(link.actuator_stop()) or 'nothing'}")
    finally:
        link.close()


# --- window -------------------------------------------------------------------

class Worker(threading.Thread):
    """Owns the serial link; the window talks to it through two queues."""

    def __init__(self, events):
        super().__init__(daemon=True)
        self.commands = queue.Queue()
        self.events = events
        self.link = None
        self.live = False
        self.pids = []
        self.log = None
        self.show_raw = False

    def info(self, text):
        self.events.put(("info", text))

    def raw(self, text):
        if self.show_raw:
            self.events.put(("raw", text))

    def run(self):
        while True:
            try:
                cmd, arg = self.commands.get(timeout=0.01 if self.live else 0.2)
                self.handle(cmd, arg)
            except queue.Empty:
                pass
            except LinkError as e:
                self.info(f"ERROR: {e}")
            except Exception as e:  # keep the worker alive whatever happens
                self.info(f"ERROR: {type(e).__name__}: {e}")
            if self.live and self.link:
                self.poll_once()

    def handle(self, cmd, arg):
        if cmd == "connect":
            self.disconnect()
            port, inverted, byte_order = arg
            self.link = connect(port, inverted, byte_order, self.info)
            self.link.on_raw = self.raw
            self.events.put(("connected", True))
        elif cmd == "disconnect":
            self.disconnect()
        elif cmd == "pids":
            self.pids = list(arg)
        elif cmd == "live":
            self.live = bool(arg) and self.link is not None
            self.events.put(("live", self.live))
        elif cmd == "log":
            if arg and self.log is None:
                self.log = CsvLog(self.pids)
                self.info(f"Logging to {self.log.path}")
            elif not arg and self.log is not None:
                self.log.close()
                self.info(f"Saved log {self.log.path}")
                self.log = None
            self.events.put(("logging", self.log is not None))
        elif cmd == "show_raw":
            self.show_raw = bool(arg)
        elif self.link is None:
            self.info("Connect first.")
        elif cmd == "codes":
            codes, ok, raw = self.link.read_codes()
            self.info(f"Fault code response: {hexs(raw)} (checksum {'OK' if ok else 'BAD'})")
            if not codes:
                self.info("No stored fault codes.")
            for c in codes:
                self.info(f"  CODE {c:02X}: {describe_code(c)}")
        elif cmd == "erase":
            self.info(f"Erase response: {hexs(self.link.erase_codes()) or 'nothing'}")
        elif cmd == "rawsend":
            self.info(f"Sent {hexs(arg)}  ->  received {hexs(self.link.raw_send(arg)) or 'nothing'}")

    def disconnect(self):
        self.live = False
        if self.log:
            self.handle("log", False)
        if self.link:
            self.link.close()
            self.link = None
            self.info("Disconnected.")
        self.events.put(("connected", False))
        self.events.put(("live", False))

    def poll_once(self):
        start = time.monotonic()
        values, errors = {}, []
        for pid in list(self.pids):
            if not self.commands.empty():
                return  # let a button press through; the next loop resumes polling
            try:
                values[pid] = self.link.read_param(pid)
            except LinkError as e:
                errors.append(f"{PARAMS_BY_PID[pid].name}: {e}")
        if values and self.log:
            self.log.write(values)
        rate = 1.0 / max(1e-3, time.monotonic() - start)
        self.events.put(("values", (values, rate, errors)))


def run_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    try:
        from serial.tools import list_ports
    except ImportError:
        list_ports = None

    root = tk.Tk()
    root.title("XJ Scan - 1991-95 Jeep engine data")
    root.geometry("1000x700")
    events = queue.Queue()
    worker = Worker(events)
    worker.start()

    style = ttk.Style()
    style.configure("Big.Treeview", font=("Segoe UI", 14), rowheight=30)
    style.configure("Big.Treeview.Heading", font=("Segoe UI", 11, "bold"))

    # top bar
    top = ttk.Frame(root, padding=6)
    top.pack(fill="x")
    ttk.Label(top, text="Port").pack(side="left")
    port_var = tk.StringVar()
    port_box = ttk.Combobox(top, textvariable=port_var, width=28, state="readonly")
    port_box.pack(side="left", padx=4)

    def refresh_ports():
        ports = []
        if list_ports:
            ports = [f"{p.device} - {p.description}" for p in list_ports.comports()]
        port_box["values"] = ports + ["DEMO - simulated Jeep"]
        if not port_var.get():
            port_var.set(port_box["values"][0])

    ttk.Button(top, text="Refresh", command=refresh_ports).pack(side="left")
    refresh_ports()

    ttk.Label(top, text="  Logic").pack(side="left")
    logic_var = tk.StringVar(value="OBD1 inverted (1991-95)")
    ttk.Combobox(top, textvariable=logic_var, width=22, state="readonly",
                 values=["OBD1 inverted (1991-95)", "Normal"]).pack(side="left", padx=4)
    ttk.Label(top, text="Byte order").pack(side="left")
    order_var = tk.StringVar(value="auto")
    ttk.Combobox(top, textvariable=order_var, width=7, state="readonly",
                 values=["auto", "normal", "swap"]).pack(side="left", padx=4)

    connect_btn = ttk.Button(top, text="Connect")
    connect_btn.pack(side="left", padx=8)

    # middle: parameter picks on the left, live values on the right
    mid = ttk.Frame(root, padding=6)
    mid.pack(fill="both", expand=True)
    picks = ttk.LabelFrame(mid, text="Parameters", padding=6)
    picks.pack(side="left", fill="y")
    pick_vars = {}
    for p in PARAMS:
        v = tk.BooleanVar(value=p.default_on)
        pick_vars[p.pid] = v
        ttk.Checkbutton(picks, text=p.label, variable=v, command=lambda: send_pids()).pack(anchor="w")

    right = ttk.Frame(mid)
    right.pack(side="left", fill="both", expand=True, padx=(8, 0))
    table = ttk.Treeview(right, columns=("value", "unit"), style="Big.Treeview")
    table.heading("#0", text="Parameter")
    table.heading("value", text="Value")
    table.heading("unit", text="Unit")
    table.column("#0", width=330)
    table.column("value", width=230, anchor="e")
    table.column("unit", width=70)
    table.pack(fill="both", expand=True)
    rate_var = tk.StringVar(value="Not connected")
    ttk.Label(right, textvariable=rate_var).pack(anchor="w")

    buttons = ttk.Frame(right)
    buttons.pack(fill="x", pady=4)
    live_btn = ttk.Button(buttons, text="Start live data", state="disabled")
    live_btn.pack(side="left")
    log_btn = ttk.Button(buttons, text="Start logging", state="disabled")
    log_btn.pack(side="left", padx=4)
    codes_btn = ttk.Button(buttons, text="Read fault codes", state="disabled",
                           command=lambda: worker.commands.put(("codes", None)))
    codes_btn.pack(side="left", padx=4)

    def erase():
        if messagebox.askyesno("Erase fault codes", "Erase the stored fault codes in the engine computer?"):
            worker.commands.put(("erase", None))

    erase_btn = ttk.Button(buttons, text="Erase fault codes", state="disabled", command=erase)
    erase_btn.pack(side="left", padx=4)

    raw_row = ttk.Frame(right)
    raw_row.pack(fill="x")
    ttk.Label(raw_row, text="Raw bytes (hex)").pack(side="left")
    raw_var = tk.StringVar(value="14 0A")
    ttk.Entry(raw_row, textvariable=raw_var, width=20).pack(side="left", padx=4)

    def raw_send():
        try:
            data = bytes.fromhex(raw_var.get())
        except ValueError:
            messagebox.showerror("Raw bytes", "Enter hex bytes like: 14 0A")
            return
        worker.commands.put(("rawsend", data))

    raw_btn = ttk.Button(raw_row, text="Send", state="disabled", command=raw_send)
    raw_btn.pack(side="left")
    show_raw_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(raw_row, text="Show all traffic in the console", variable=show_raw_var,
                    command=lambda: worker.commands.put(("show_raw", show_raw_var.get()))).pack(side="left", padx=8)

    # console
    console = tk.Text(root, height=10, font=("Consolas", 10))
    console.pack(fill="x", padx=6, pady=(0, 6))

    def say(text):
        console.insert("end", text + "\n")
        console.see("end")
        if int(console.index("end-1c").split(".")[0]) > 2000:
            console.delete("1.0", "500.0")

    state = {"connected": False, "live": False, "logging": False}

    def selected_pids():
        return [p.pid for p in PARAMS if pick_vars[p.pid].get()]

    def send_pids():
        pids = selected_pids()
        worker.commands.put(("pids", pids))
        table.delete(*table.get_children())
        for pid in pids:
            p = PARAMS_BY_PID[pid]
            table.insert("", "end", iid=str(pid), text=p.name, values=("-", p.unit))

    def on_connect():
        if state["connected"]:
            worker.commands.put(("disconnect", None))
            return
        port = port_var.get().split(" - ")[0]
        say(f"Connecting to {port}...")
        worker.commands.put(("connect", (port, logic_var.get().startswith("OBD1"), order_var.get())))

    def on_live():
        worker.commands.put(("live", not state["live"]))

    def on_log():
        worker.commands.put(("log", not state["logging"]))

    connect_btn["command"] = on_connect
    live_btn["command"] = on_live
    log_btn["command"] = on_log
    send_pids()

    last_error_shown = [0.0]

    def pump():
        while True:
            try:
                kind, data = events.get_nowait()
            except queue.Empty:
                break
            if kind in ("info", "raw"):
                say(data)
            elif kind == "connected":
                state["connected"] = data
                connect_btn["text"] = "Disconnect" if data else "Connect"
                for b in (live_btn, codes_btn, erase_btn, raw_btn, log_btn):
                    b["state"] = "normal" if data else "disabled"
                rate_var.set("Connected" if data else "Not connected")
            elif kind == "live":
                state["live"] = data
                live_btn["text"] = "Stop live data" if data else "Start live data"
            elif kind == "logging":
                state["logging"] = data
                log_btn["text"] = "Stop logging" if data else "Start logging"
                for child in picks.winfo_children():
                    child["state"] = "disabled" if data else "normal"
            elif kind == "values":
                values, rate, errors = data
                for pid, v in values.items():
                    if table.exists(str(pid)):
                        table.set(str(pid), "value", v)
                rate_var.set(f"{rate:.1f} updates/s" + (f"   ({len(errors)} parameters not answering)" if errors else ""))
                if errors and time.monotonic() - last_error_shown[0] > 5:
                    last_error_shown[0] = time.monotonic()
                    say("Not answering: " + "; ".join(errors))
        root.after(50, pump)

    def on_close():
        worker.commands.put(("disconnect", None))
        root.after(300, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    say("1) Pick the Arduino's COM port (or DEMO), 2) Connect, 3) Start live data.")
    pump()
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", metavar="PORT", help="text mode on this port (e.g. COM5, or DEMO)")
    ap.add_argument("--normal-logic", action="store_true", help="non-inverted SCI (not for 1991-95 OBD1)")
    ap.add_argument("--byte-order", choices=["auto", "normal", "swap"], default="auto")
    ap.add_argument("--codes", action="store_true", help="with --cli: read fault codes and exit")
    ap.add_argument("--o2", action="store_true", help="with --cli: read only the O2 sensor, as fast as possible")
    ap.add_argument("--pids", help="with --cli: comma-separated parameter IDs in hex, e.g. 02,11,05")
    ap.add_argument("--seconds", type=float, help="with --cli: stop logging after this many seconds")
    ap.add_argument("--fast-o2", action="store_true", help="with --cli: O2 every row (~7/s) plus trim, rpm, "
                    "MAP, coolant, intake air taking turns one per row")
    ap.add_argument("--all", action="store_true", help="with --cli: log everything this PCM answers "
                    "(fast readings every row, the rest in rotation)")
    ap.add_argument("--actuator", metavar="ID", help="with --cli: run PCM actuator test ID (hex, e.g. 1A) "
                    "for --seconds (default 5), key on engine off, then stop it")
    ap.add_argument("--force", action="store_true", help="allow --actuator with the engine running")
    ap.add_argument("--idle", type=int, metavar="RPM", help="with --cli: ask the PCM to hold this idle "
                    "speed (max 2040) while logging; park only. Use a short --pids list so it's resent often")
    ap.add_argument("--send", metavar="HEX", help="with --cli: send raw bytes (e.g. '1A 02' switch test, "
                    "'15 01 23' read memory) one at a time with echo, print the reply, and exit")
    args = ap.parse_args()
    pids = None
    slow = None
    per_row = SLOW_PER_ROW
    if args.fast_o2:
        pids, slow, per_row = [0x02], [0x0E, 0x11, 0x0B, 0x05, 0x1B], 1
    elif args.all:
        pids, slow = ALL_FAST, ALL_SLOW
    elif args.o2:
        pids = [0x02]
    elif args.pids:
        pids = [int(p, 16) for p in args.pids.split(",")]
        unknown = [f"{p:02X}" for p in pids if p not in PARAMS_BY_PID]
        if unknown:
            sys.exit(f"Unknown parameter IDs: {', '.join(unknown)}")
    if args.cli and args.send:
        link = connect(args.cli, not args.normal_logic, "auto", print)
        try:
            data = bytes.fromhex(args.send)
            print(f"Sent {hexs(data)} -> {hexs(link.raw_send(data)) or 'nothing'}")
        finally:
            link.close()
    elif args.cli and args.actuator:
        try:
            run_actuator(args.cli, not args.normal_logic, int(args.actuator, 16), args.seconds or 5, args.force)
        except LinkError as e:
            sys.exit(f"ERROR: {e}")
    elif args.cli:
        try:
            run_cli(args.cli, not args.normal_logic, args.byte_order, args.codes, pids, args.seconds, slow,
                    min(args.idle, 2040) if args.idle else None, per_row)
        except LinkError as e:
            sys.exit(f"ERROR: {e}")
    else:
        run_gui()


if __name__ == "__main__":
    main()
