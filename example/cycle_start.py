"""CYCLE START over the bus - the test planned in todo.md G. Nothing is sent without approval; ``--dry-run``
answers from a canned machine.

Two routes: ``--via run`` (default) sends the UNI-TE Run request (938914 §4.9) through ``client.cycle_start()``;
``--via w3`` pulses the ladder bit %W3.2 AZYKLUS = C_CYCLE "CYCLE START pulse" (938846 §3.8.2) through
``write_ladder``. Both skip the ladder's start memory (%SP11), both stay under the NC's state check and the PLC's
feed authorisation %W4.0 AUTAV.

Safety design: the NC must be in MDI with a single motion-free block typed at the panel (``G4 F2``, a 2 s dwell),
so a cycle can start but nothing can move; the feed pot at 0 % is no barrier for G0 (2026-09-26). The script aborts unless
the mode is MDI, the mats are acknowledged, feed is authorised, no cycle runs, no axis moves and the spindle is
off; then it asks for a typed confirmation, sends, and watches %R3.2 E_CYCLE "cycle in progress" for 4 s.

Usage::

    poetry run cycle_start --dry-run                # offline, canned answers
    poetry run cycle_start --pre-only               # live reads only; nothing is unlocked on that client
    poetry run cycle_start [--via run|w3]           # live, only after Paul approved this exact run
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.client import ladder_specific_byte, parse_ladder_variable
from pyunitelway.num_constants import NC_START, Action, Mode, Object
from pyunitelway.utils import format_hex_list

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234

CYCLE = "%R3.2"  # E_CYCLE "Cycle in progress" (938846 §3.8.1)
FEED_POT = "%I0123.B"  # Vorschubpoti, copied to %W102.B AVPOTI1 by %SP9; 0 = feed override 0 %
WATCH_SEC = 4.0  # a G4 F2 dwell shows E_CYCLE for ~2 s

# (variable, meaning, required value; None = information only). Bits read as bool, .B/.W/.L unsigned.
CHECKS = [
    ("%R16.B", "EBETRART active mode, must be 2 = MDI", 2),
    ("%V700.0", "V__NOTAQUI Not-Aus quittiert", True),
    ("%I0701.1", "IMeShm_Eig__ Schaltmatte eingeschaltet (mats acknowledged, drives enabled)", True),
    ("%W4.0", "VORFREIG = AUTAV feed authorised on all axis groups (%SP0/01)", True),
    (CYCLE, "E_CYCLE cycle in progress", False),
    ("%R3.1", "E_ARUS cycle stop", None),
    ("%R3.0", "E_RAZ CNC reset in progress", None),
    ("%R3.7", "E_OPER programme stop", None),
    (NC_START, "AZYKLUS = C_CYCLE cycle start pulse (%SP11/03 coil)", False),
    ("%R6.L", "AXBEWEAL axes in motion", 0),
    ("%R122.0", "M03 Spindel ein rechts", False),
    ("%R122.1", "M04 Spindel ein links", False),
    ("%R18.B", "MASCFEHL machine error number", None),
    ("%R1A.W", "PROGCOUR active programme number (not what MDI runs, logged)", None),
    (FEED_POT, "Vorschubpoti, 0 = feed override 0 % (did not hold a G0 on 2026-09-26)", None),
]

log = logging.getLogger("cycle_start")


class Abort(Exception):
    pass


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"cycle-start-{datetime.now():%Y%m%d-%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    file = logging.FileHandler(log_path)
    file.setLevel(logging.DEBUG)
    file.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file])
    log.info("logging to %s", log_path)


def is_number(variable):
    return variable[-2:] in (".B", ".W", ".L")


def checks(client, label, enforce=True):
    """Read every check variable and the mode, log them, return the misses (before: enforced; after: logged)."""
    misses = []
    mode = client.read_mode()
    ok = "" if not enforce or mode == Mode.MDI else "  <-- required MDI"
    log.info("%s read_mode  = %s%s", label, mode.name, ok)
    if ok:
        misses.append(f"mode {mode.name}, required MDI")
    for variable, meaning, required in CHECKS:
        value = client.read_ladder(variable, signed=False) if is_number(variable) else client.read_ladder(variable)
        ok = "" if not enforce or required is None or value == required else f"  <-- required {required}"
        log.info("%s %-9s = %-5r %s%s", label, variable, value, meaning, ok)
        if ok:
            misses.append(f"{variable} = {value!r}, required {required} ({meaning})")
        if variable == FEED_POT and value != 0:
            log.warning("feed pot reads %d, not 0", value)
    return misses


def confirm(via):
    print()
    print(f"About to send CYCLE START via {via}. The NC is in MDI; the MDI buffer must hold ONLY  G4 F2  and the")
    print("block decides what moves (the pot at 0 % did not hold a G0). Hand on the Not-Aus. Nobody in the machine area.")
    answer = input("Type SEND to start the cycle, anything else aborts: ")
    if answer.strip() != "SEND":
        raise Abort("not confirmed, nothing sent")


def send(client, via):
    if via == "run":
        started = client.cycle_start()
        log.info("cycle_start() = %r (True = FE, False = FD refused)", started)
        return started
    client.write_ladder(NC_START, True)  # %SP11/03 rewrites the coil within one PLC cycle; the NC wants a pulse
    client.write_ladder(NC_START, False)
    log.info("%s pulsed True then False", NC_START)
    return True


def watch(client, seconds=WATCH_SEC):
    """Poll E_CYCLE as fast as the bus allows and log every change; return (seen_running, running_at_end)."""
    deadline = time.monotonic() + seconds
    last = None
    seen = False
    while time.monotonic() < deadline:
        running = client.read_ladder(CYCLE)
        if running != last:
            log.info("%s E_CYCLE = %r", CYCLE, running)
            last = running
        seen = seen or running
    return seen, bool(last)


def live_client(via):
    if via is None:
        return connect(UnitelwayClient())  # --pre-only: nothing unlocked
    unlock = {Action.CYCLE_START} if via == "run" else {NC_START}
    return connect(UnitelwayClient(writable=unlock))


def connect(client):
    client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    return client


def dry_run_client(via):
    """Canned machine: MDI, idle, mats acknowledged, feed authorised, pot at 0. A start shows E_CYCLE for 2 s."""
    def key(variable):
        _symbol, segment, address, size, _index = parse_ladder_variable(variable)
        return (segment, ladder_specific_byte(size), address)

    bits = {"%V700.0": True, "%I0701.1": True, "%W4.0": True, "%R3.1": False, "%R3.0": False, "%R3.7": False,
            NC_START: False, "%R122.0": False, "%R122.1": False}
    numbers = {"%R16.B": [2], "%R6.L": [0, 0, 0, 0], "%R18.B": [0], "%R1A.W": [0x29, 0x23], FEED_POT: [0]}
    table = {key(v): v for v in list(bits) + list(numbers) + [CYCLE]}
    cycle_until = [0.0]
    client = UnitelwayClient(writable=() if via is None else ({Action.CYCLE_START} if via == "run" else {NC_START}))

    def fake_run_unite(address, query, timeout=None, text=""):
        log.debug("dry-run tx %s: %s", text, format_hex_list(query))
        if query[0] == 0x24:  # Run -> FE
            cycle_until[0] = time.monotonic() + 2.0
            return [0xFE]
        k = (query[2], query[3], int.from_bytes(query[4:6], "little"))
        if query[0] == 0x36 and query[2] == Object.MODE_SELECTION:  # segment 180 -> mode word, little-endian
            return [0x66, 0x00, 0x02, 0x00]
        if query[0] == 0x36:
            variable = table[k]
            if variable == CYCLE:
                return [0x66, query[3], 0x80 if time.monotonic() < cycle_until[0] else 0x00]
            if variable in numbers:
                return [0x66, query[3], *numbers[variable]]
            return [0x66, query[3], 0x80 if bits[variable] else 0x00]
        if query[0] == 0x37 and table[k] == NC_START:  # the pulse; the coil clears it again
            if query[8]:
                cycle_until[0] = time.monotonic() + 2.0
            return [0xFE]
        raise AssertionError(query)

    client.run_unite = fake_run_unite
    return client


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="canned answers, nothing on the wire")
    parser.add_argument("--pre-only", action="store_true", help="the pre-check reads only, nothing unlocked")
    parser.add_argument("--via", choices=("run", "w3"), default="run",
                        help="run: UNI-TE Run request (default); w3: pulse the ladder bit %%W3.2")
    args = parser.parse_args()
    setup_logging()
    via = None if args.pre_only else args.via
    log.info("route %s%s", via, " (dry run)" if args.dry_run else "" if via else " (pre-check only)")
    client = dry_run_client(via) if args.dry_run else live_client(via)
    try:
        misses = checks(client, "before")
        if misses:
            raise Abort("pre-check failed:\n  " + "\n  ".join(misses))
        if via is None:
            log.info("pre-check passed, --pre-only: nothing sent")
            return 0
        if not args.dry_run:
            confirm(via)
        started = send(client, via)
        seen, still = watch(client)
        checks(client, "after", enforce=False)
        if still:
            log.warning("RESULT: E_CYCLE still 1 after %.0f s - a dwell would be over; press CYCLE STOP and look", WATCH_SEC)
            return 1
        if seen:
            log.info("RESULT: a cycle ran and ended via %s", via)
            return 0
        log.info("RESULT: no cycle seen via %s (request answer %r)", via, started)
        return 1
    except Abort as e:
        log.error("%s", e)
        return 2
    finally:
        if client.socket is not None:
            client.disconnect_socket()


if __name__ == "__main__":
    sys.exit(main())
