"""Show the machine operator panel (Bedienpult) of the IMA BIMA Quadroform as the PLC sees it.

Reads the panel's input bytes ``%I0100``-``%I0104`` (buttons, key switch), its output bytes
``%Q0100``-``%Q0102`` (lamps) and the two potentiometers ``%I0121.B`` / ``%I0123.B``, then
renders them as the panel is laid out. Read-only: nothing is written. Verified on the machine
2026-09-22 (all ten bytes answered; key switch, default lamps and pots read plausibly).

Labels, button/lamp pairing and the dead keys come from the bundle's
``corpus/01_Bedienung/bedienpult-tasten.md`` and ``schluesselschalter-verriegelungen.md``
(decoded ladder of this machine + electrical plan ``=Y1``, sheet 56). Addresses are
``%I r c bb . x`` = rack, card, byte, bit (938846 §3.7); the request carries them as the hex
number, e.g. ``%I0103.1`` -> ``0x0103`` bit 1 (938914 §4.1.3.3).

Usage::

    poetry run panel                    # one snapshot
    poetry run panel --watch 1          # refresh every second, Ctrl-C to stop
    poetry run panel --demo             # render sample data, no connection
    poetry run panel --ip 10.1.70.9 --debug   # wire bytes to example/logs/panel-<timestamp>.log
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234

log = logging.getLogger("panel")

INPUT_BYTES = ["%I0100", "%I0101", "%I0102", "%I0103", "%I0104"]
OUTPUT_BYTES = ["%Q0100", "%Q0101", "%Q0102"]
POTS = [("%I0123", "Vorschubpoti (Gruppe 1)"), ("%I0121", "Spindelpoti")]

# electrical plan =Y1 sheet 56, left to right
KEY_SWITCH = [("%I0101.3", "Dienstprogramm sperren"), ("%I0101.5", "Freigabe"), ("%I0101.4", "Betriebsart sperren")]

# (button, label, note) - note "tot": read by no network
AXIS_KEYS = [
    ("%I0100.0", "X1 +", ""), ("%I0100.1", "X1 -", ""),
    ("%I0100.2", "Y1 +", ""), ("%I0100.3", "Y1 -", ""),
    ("%I0101.0", "Z1 +", ""), ("%I0101.1", "Z1 -", ""),
    ("%I0101.2", "Eilgang", ""),
    ("%I0100.4", "Y2 +", "tot"), ("%I0100.5", "Y2 -", "tot"),
    ("%I0100.6", "X2 -", "tot"), ("%I0100.7", "X2 +", "tot"),
]

# (button, lamp, label, note) - lamps sit bit-parallel one byte apart from their button
FUNCTION_KEYS = [
    ("%I0103.1", "%Q0100.1", "NC-Start", ""),
    ("%I0103.0", "%Q0100.0", "NC-Stopp", ""),
    ("%I0102.5", None, "Reset", ""),
    ("%I0101.6", "%Q0101.6", "Störung quittieren", "überbrückt %V118.L, Leuchte blinkt"),
    ("%I0101.7", "%Q0101.7", "Not-Aus quittieren", "Leuchte = %V700.0 quittiert"),
    ("%I0103.7", "%Q0100.7", "Achsenstopp quittieren", ""),
    ("%I0103.5", "%Q0100.5", "Vakuum ein/aus", "Toggle"),
    ("%I0103.3", "%Q0100.3", "Absaugung Frässpindel", "Toggle"),
    ("%I0103.4", "%Q0100.4", "Langes Werkstück", "Leuchte = Merker der Spannlogik"),
    ("%I0102.4", "%Q0101.4", "Überbreites Teil", "Leuchte = Merker der Spannlogik"),
    ("%I0102.0", "%Q0101.0", "Achsumschaltung 1", ""),
    ("%I0102.1", "%Q0101.1", "Achsumschaltung 2", ""),
    ("%I0104.0", "%Q0102.0", "Gruppe 1 anwählen", "ohne Funktion (P97 = 1 0)"),
    ("%I0104.1", "%Q0102.1", "Gruppe 2 anwählen", "ohne Funktion (P97 = 1 0)"),
    ("%I0104.5", "%Q0102.5", "WZ-Magazin Haube auf/zu", "nur MANUAL"),
    ("%I0104.6", "%Q0102.6", "WZ-Magazin nach links", "nur MANUAL"),
    ("%I0104.7", "%Q0102.7", "WZ-Magazin nach rechts", "nur MANUAL"),
    ("%I0103.2", "%Q0100.2", "Verleimteil ein/aus", "tot"),
    ("%I0103.6", "%Q0100.6", "Lastspannung aus", "nur Hardware"),
    ("%I0104.2", "%Q0102.2", "Gruppe 3", "tot"),
    ("%I0104.3", "%Q0102.3", "Gruppe 4", "tot"),
    ("%I0104.4", "%Q0102.4", "Gruppe 5", "tot"),
    (None, "%Q0101.5", "Werkstück vorlegen", "Leuchte nie getrieben"),
]

DEMO = {  # NC-Start pressed, key in Freigabe, vacuum and suction lamps on, pots mid-way
    "%I0100": 0x00, "%I0101": 0x20, "%I0102": 0x00, "%I0103": 0x02, "%I0104": 0x00,
    "%Q0100": 0x2A, "%Q0101": 0x81, "%Q0102": 0x01, "%I0121": 0x80, "%I0123": 0xC8,
}


# ---- reading ----

def read_panel(client):
    """Return ``{byte address: 0-255 or None}`` for every panel byte; a failed read gives ``None``."""
    values = {}
    for addr in INPUT_BYTES + OUTPUT_BYTES + [p[0] for p in POTS]:
        try:
            values[addr] = client.read_ladder(f"{addr}.B", signed=False)
        except Exception:
            log.error("%s.B failed", addr, exc_info=True)
            values[addr] = None
    return values


def bit(values, variable):
    """State of ``%I0103.1`` from the byte map: ``True``/``False``, ``None`` if unread."""
    if variable is None:
        return None
    addr, n = variable.split(".")
    value = values.get(addr)
    return None if value is None else bool(value >> int(n) & 1)


# ---- rendering ----

def _color():
    return sys.stdout.isatty() and "--no-color" not in sys.argv


def paint(text, code):
    return f"\x1b[{code}m{text}\x1b[0m" if _color() else text


def button(state):
    return {True: paint("[■]", "1;33"), False: "[ ]", None: "[?]"}[state]


def lamp(state):
    return {True: paint("●", "1;32"), False: "○", None: "?"}[state]


def hexbytes(values, addrs):
    return " ".join("??" if values.get(a) is None else f"{values[a]:02X}" for a in addrs)


def render(values, when):
    out = [f"IMA BIMA Quadroform - Bedienpult          {when:%Y-%m-%d %H:%M:%S}",
           f"{INPUT_BYTES[0]}-{INPUT_BYTES[-1][-2:]}: {hexbytes(values, INPUT_BYTES)}    "
           f"{OUTPUT_BYTES[0]}-{OUTPUT_BYTES[-1][-2:]}: {hexbytes(values, OUTPUT_BYTES)}",
           ""]

    positions = "   ".join(f"{button(bit(values, a))} {label}" for a, label in KEY_SWITCH)
    out += [f"Schlüsselschalter   {positions}", ""]

    live = "   ".join(f"{label} {button(bit(values, a))}" for a, label, note in AXIS_KEYS if not note)
    dead = ", ".join(label for a, label, note in AXIS_KEYS if note)
    out += [f"Achsverfahrtasten   {live}", f"                    tot: {dead}", ""]

    out += [f"  {'Taster':24}{'Taste':^5} {'Leuchte':^7}  Hinweis"]
    for btn, lmp, label, note in FUNCTION_KEYS:
        b = button(bit(values, btn)) if btn else "   "
        l = lamp(bit(values, lmp)) if lmp else " "
        out.append(f"  {label:24}{b:^5} {l:^7}  {note}")
    out.append("")

    for addr, label in POTS:
        v = values.get(addr)
        bar = "" if v is None else "#" * (v * 20 // 255)
        out.append(f"{label:24}{addr}.B = {'?' if v is None else f'{v:3d}'}  {bar}")
    out += ["", "[■] Taste gedrückt   ● Leuchte an   tot = von keinem Netz gelesen   ? = Lesefehler"]
    return "\n".join(out)


# ---- main ----

def setup_logging(debug):
    handlers = [logging.StreamHandler(sys.stderr)]
    handlers[0].setLevel(logging.WARNING)
    if debug:
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        f = logging.FileHandler(log_dir / f"panel-{datetime.now():%Y%m%d-%H%M%S}.log")
        f.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        handlers.append(f)
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, handlers=handlers)


def main():
    ap = argparse.ArgumentParser(description="Render the operator panel of the IMA BIMA Quadroform (read-only).")
    ap.add_argument("--ip", default=ADAPTER_IP)
    ap.add_argument("--port", type=int, default=ADAPTER_PORT)
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="refresh interval; omit for one snapshot")
    ap.add_argument("--demo", action="store_true", help="render sample data without connecting")
    ap.add_argument("--debug", action="store_true", help="log every wire byte to example/logs/")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    setup_logging(args.debug)

    if args.demo:
        print(render(DEMO, datetime.now()))
        return

    client = UnitelwayClient()
    client.connect_socket(args.ip, args.port)
    try:
        while True:
            text = render(read_panel(client), datetime.now())
            if args.watch:
                print("\x1b[2J\x1b[H" + text, flush=True)
                time.sleep(args.watch)
            else:
                print(text)
                break
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect_socket()


if __name__ == "__main__":
    main()
