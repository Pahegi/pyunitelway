"""Connectivity check against the NUM 1060.

Everything is a read except the mode round-trip (to MANUAL, then back to the mode found);
``--read-only`` skips it. Other writes stay commented out; uncomment one deliberately.

Console shows INFO (one line per exchange + result); ``example/logs/test-<timestamp>.log`` gets
DEBUG (every wire byte) so the machine's real answers can become test vectors.
"""

import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.num_constants import Mode, Object

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234

log = logging.getLogger("test")


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"test-{datetime.now():%Y%m%d-%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    file = logging.FileHandler(log_path)
    file.setLevel(logging.DEBUG)
    file.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file])
    log.info("logging to %s", log_path)


def attempt(label, call):
    """Run one request, log its result or its traceback, and carry on."""
    try:
        result = call()
        log.info("%s = %r", label, result)
        return result
    except Exception:
        log.error("%s FAILED\n%s", label, traceback.format_exc())
        return None


def main():
    setup_logging()
    # slave_address=0x01: the only address this master polls (poetry run listen); segment 180 unlocked for the round-trip,
    # %Q0700.6 QK_VakpEin__ "KR Vakuumpumpe einschalten" for the pump write below
    client = UnitelwayClient(writable={Object.MODE_SELECTION, "%Q0700.6"})
    client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    # client.connect_socket("127.0.0.1", 8234)  # debug mockup server

    # ---- read-only requests ----
    # attempt("mirror", lambda: client.mirror([0x00]))
    # attempt("unit identification", lambda: client.get_unit_identification())
    # attempt("unit status", lambda: client.get_unit_status())
    # attempt("available bytes in NC RAM", lambda: client.get_available_bytes_in_ram())
    # attempt("read_mode", lambda: client.read_mode())
    # attempt("stations managed by master", lambda: client.get_stations_managed_by_master())
    # attempt("unit fault history", lambda: client.get_unit_fault_history())

    # ---- ladder reads (all %R = NC -> PLC, read-only) ----
    # for var, what in [
    #     ("%R5.1", "E_PROG programme active"),
    #     ("%R16.B", "MODCOUR current mode"),
    #     ("%R1A.W", "PROGCOUR active programme"),
    #     ("%R14.1", "E_BAT battery"),
    #     ("%R17.B", "PGVISU displayed page"),
    #     ("%R18.B", "ERRMACH machine error number"),
    #     ("%R5.0", "E_CNPRET CNC ready"),
    #     ("%R6.L", "AXMVT axes in motion"),
    # ]:
    #     attempt(f"read_ladder {var} ({what})", lambda v=var: client.read_ladder(v))
    # attempt("_read_objects %R1A.W x2", lambda: client._read_objects(0xA4, 65, 0x1A, 2))  # QUANTITY probe (B1)

    # ---- ladder reads on the other segments; symbols per trace_signal.py, cross-checks against the panel ----
    # for var, what in [
    #     ("%V700.0", "V__NOTAQUI Not-Aus quittiert, = lamp %Q0101.7"),
    #     ("%V700.B", "the byte around it"),
    #     ("%V80.1", "VVSSHT_AUF Schutztuer auf"),
    #     ("%V80.L", "VL_AX__VST Vorschubstop alle Achsen"),
    #     ("%V118.L", "VL_AX__VSQ1G Vorschubstop Gruppe 1"),
    #     ("%W4.6", "DPAUS Dienstprogramme gesperrt, = key switch %I0101.3"),
    #     ("%W100.0", "VFREIG1 Vorschubfreigabe Gruppe 1"),
    #     ("%W14.B", "MODEDEM mode requested, never written by this PLC"),
    #     ("%W202.B", "AVPOTI2, = %I0123.B feed pot"),
    #     ("%M4010.W", "MFKT_CHN1 M-function index channel 1"),
    #     ("%M4004.W", "MIDABL3IPC"),
    #     ("%M77F8.W", "Hrsetfeh C-function handle"),
    #     ("%S0.W", "common word 0 (938846 §3.9)"),
    #     ("%I0100.L", "panel inputs 00-03 as one long: first byte is the MSB (938846 §4), 0x00200000 with the key in Freigabe"),
    #     ("%Q0100.W", "panel lamps 00-01 as word"),
    #     ("%I0600.B", "no card in slot 6: how does the NC refuse?"),
    # ]:
    #     attempt(f"read_ladder {var} ({what})", lambda v=var: client.read_ladder(v))
    # attempt("_read_objects %I0100.B x5", lambda: client._read_objects(0xA8, 64, 0x0100, 5))  # QUANTITY on bytes

    # ---- mode round-trip: live write, segment 180 (938914 §4.1.3); ends in the mode it found ----
    # if "--read-only" in sys.argv:
    #     log.info("--read-only: mode round-trip skipped")
    # else:
    #     before = attempt("read_mode before", lambda: client.read_mode())
    #     other = Mode.MANUAL if before != Mode.MANUAL else Mode.AUTO
    #     for mode in (other, before):
    #         attempt(f"write_mode {mode.name}", lambda m=mode: client.write_mode(m))
    #         time.sleep(0.5)
    #         attempt(f"read_mode after {mode.name}", lambda: client.read_mode())
    #         attempt(f"read_ladder %R16.B after {mode.name}", lambda: client.read_ladder("%R16.B"))

    # ---- vacuum pump: %Q0700.6 is a latched output (%SP24/00 Set/Reset); verified 2026-09-23, True starts it, False stops it.
    #      The coolant pump runs with it. Direct writes leave the panel lamp %Q0100.5 untouched. ----
    # attempt(f"write_vacuum_pump({True}) (%Q0700.6 QK_VakpEin__)", lambda: client.write_vacuum_pump(True))
    # time.sleep(3)
    attempt(f"write_vacuum_pump({False}) (%Q0700.6 QK_VakpEin__)", lambda: client.write_vacuum_pump(False))
    
    client.disconnect_socket()


if __name__ == "__main__":
    main()
