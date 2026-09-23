"""The first live ladder write, as agreed on 2026-09-22 (todo.md D). One script, one approval, every step logged.

Sequence, aborting at the first mismatch but always attempting the restore:

1. read  %W16.B  - MSG2, the message number the PLC shows on line 2 of the NC's error page (938846 §3.8.2.8);
                   no ladder network of this machine writes it, and there is no %9999.9 to display a text
2. write %W16.B = 1, read back, expect 1
3. write %W16.B = the old value, read back, expect the old value
4. write_message("PYUNITELWAY TEST") - request F5/4B (938914 §4.17), prints the line on the NC screen

Usage::

    poetry run write_checks --dry-run      # offline: canned answers, shows the frames it would send
    poetry run write_checks                # live - only after Paul approved this exact script
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.utils import format_hex_list

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234
VARIABLE = "%W16.B"  # MSG2
MESSAGE = "PYUNITELWAY TEST"

log = logging.getLogger("write_checks")


class Mismatch(Exception):
    pass


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"write-checks-{datetime.now():%Y%m%d-%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    file = logging.FileHandler(log_path)
    file.setLevel(logging.DEBUG)
    file.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file])
    log.info("logging to %s", log_path)


def expect(label, got, wanted):
    if got != wanted:
        raise Mismatch(f"{label}: expected {wanted!r}, got {got!r}")
    log.info("%s = %r  OK", label, got)


def dry_run_client():
    """Canned answers: reads echo a memory cell, writes update it - the frames are logged as sent."""
    client = UnitelwayClient(writable={VARIABLE})
    memory = {VARIABLE: 3}

    def fake_run_unite(address, query, timeout=None, text=""):
        log.info("dry-run tx %s: %s", text, format_hex_list(query))
        if query[0] == 0x36:  # Read-Object -> 66 <specific> <byte>
            return [0x66, query[3], memory[VARIABLE]]
        if query[0] == 0x37:  # Write-Object -> FE
            memory[VARIABLE] = query[8]
            return [0xFE]
        if query[0] == 0xF5:  # Write-Message -> F5 FE
            return [0xF5, 0xFE]
        raise AssertionError(query)

    client.run_unite = fake_run_unite
    return client


def run(client):
    old = client.read_ladder(VARIABLE, signed=False)
    log.info("%s before = %d", VARIABLE, old)
    test_value = 1 if old != 1 else 2  # must differ from the old value, or the read-back proves nothing
    wrote = False
    try:
        expect(f"write {VARIABLE} = {test_value}", client.write_ladder(VARIABLE, test_value, signed=False), True)
        wrote = True
        expect(f"read back {VARIABLE}", client.read_ladder(VARIABLE, signed=False), test_value)
    finally:
        if wrote:
            expect(f"restore {VARIABLE} = {old}", client.write_ladder(VARIABLE, old, signed=False), True)
            expect(f"read back {VARIABLE}", client.read_ladder(VARIABLE, signed=False), old)
    expect(f"write_message({MESSAGE!r})", client.write_message(MESSAGE), True)
    log.info("all steps passed")


def main():
    setup_logging()
    if "--dry-run" in sys.argv:
        log.info("DRY RUN: nothing is sent")
        run(dry_run_client())
        return
    client = UnitelwayClient(writable={VARIABLE})  # exactly MSG2, nothing else, this run
    client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    try:
        run(client)
    except Mismatch as e:
        log.error("ABORTED: %s", e)
        sys.exit(1)
    finally:
        client.disconnect_socket()


if __name__ == "__main__":
    main()
