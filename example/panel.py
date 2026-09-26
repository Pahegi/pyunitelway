"""Operator panel (Bedienpult) of the IMA BIMA Quadroform as the PLC sees it: a read-only snapshot.

Inputs %I0100-%I0104 (buttons, key switch), outputs %Q0100-%Q0102 (lamps), pots %I0121.B / %I0123.B.
Labels and dead keys per the bundle's bedienpult-tasten.md and schluesselschalter-verriegelungen.md.
Verified on the machine 2026-09-22.

Usage::

    poetry run panel [--watch SECONDS]
"""

import argparse
import sys
import time
from datetime import datetime

from pyunitelway import UnitelwayClient

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234

BYTES = ["%I0100", "%I0101", "%I0102", "%I0103", "%I0104", "%Q0100", "%Q0101", "%Q0102", "%I0121", "%I0123"]
KEY_SWITCH = [("%I0101.3", "Dienstprogramm sperren"), ("%I0101.5", "Freigabe"), ("%I0101.4", "Betriebsart sperren")]
AXIS_KEYS = [("%I0100.0", "X1+"), ("%I0100.1", "X1-"), ("%I0100.2", "Y1+"), ("%I0100.3", "Y1-"),
             ("%I0101.0", "Z1+"), ("%I0101.1", "Z1-"), ("%I0101.2", "Eilgang")]  # the X2/Y2 keys are read by no network
POTS = [("%I0123", "Vorschubpoti"), ("%I0121", "Spindelpoti")]
# (button, lamp, label, note): lamps sit bit-parallel one byte apart from their button; "tot" = read by no network
FUNCTION_KEYS = [
    ("%I0103.1", "%Q0100.1", "NC-Start", ""),
    ("%I0103.0", "%Q0100.0", "NC-Stopp", ""),
    ("%I0102.5", None, "Reset", ""),
    ("%I0101.6", "%Q0101.6", "Störung quittieren", "Leuchte blinkt"),
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


def read_panel(client):
    """``{byte address: 0-255}``; a byte the NC did not answer is left out."""
    values = {}
    for addr in BYTES:
        try:
            values[addr] = client.read_ladder(f"{addr}.B", signed=False)
        except Exception as e:
            print(f"{addr}.B: {e}", file=sys.stderr)
    return values


def bit(values, variable):
    """``True``/``False`` for ``%I0103.1``, ``None`` if unread or no address."""
    if not variable or variable.split(".")[0] not in values:
        return None
    addr, n = variable.split(".")
    return bool(values[addr] >> int(n) & 1)


def mark(state, on="[x]", off="[ ]"):
    return {True: on, False: off, None: "[?]"}[state]


def render(values, when):
    out = [f"IMA BIMA Quadroform - Bedienpult   {when:%Y-%m-%d %H:%M:%S}",
           " ".join(f"{a}={values[a]:02X}" if a in values else f"{a}=??" for a in BYTES[:8]), "",
           "Schlüsselschalter  " + "  ".join(f"{mark(bit(values, a))} {l}" for a, l in KEY_SWITCH),
           "Achsen             " + "  ".join(f"{l} {mark(bit(values, a))}" for a, l in AXIS_KEYS), "",
           f"  {'Taster':24}Taste Leuchte  Hinweis"]
    for btn, lmp, label, note in FUNCTION_KEYS:
        b = mark(bit(values, btn)) if btn else "   "
        l = mark(bit(values, lmp), "(*)", "( )") if lmp else "   "
        out.append(f"  {label:24}{b:^5} {l:^7}  {note}")
    out.append("")
    for addr, label in POTS:
        v = values.get(addr)
        out.append(f"{label:24}{addr}.B = {'?' if v is None else v:>3}  {'' if v is None else '#' * (v * 20 // 255)}")
    return "\n".join(out + ["", "[x] Taste gedrückt   (*) Leuchte an   [?] nicht gelesen"])


def main():
    ap = argparse.ArgumentParser(description="Operator panel snapshot, read-only.")
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="refresh interval; default: one snapshot")
    args = ap.parse_args()
    client = UnitelwayClient()
    client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    try:
        while True:
            print(("\x1b[2J\x1b[H" if args.watch else "") + render(read_panel(client), datetime.now()), flush=True)
            if not args.watch:
                break
            time.sleep(args.watch)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect_socket()


if __name__ == "__main__":
    main()
