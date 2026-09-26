"""Full backup of the NC over UNI-TE (938914 §4.13, §4.16): every part programme, the machine parameters and the
PLC archive, saved like the NCDat backup. Read-only. Open-Upload-Sequence takes the NC's single transfer slot,
so nothing is opened while a programme runs or the NC is in EDIT. Verified on the machine 2026-09-26.

Usage::

    poetry run backup [--out DIR] [--timeout S]   # only after Paul approved the run

Output in example/backup/<timestamp>/ (gitignored): directory.txt, one file per programme (101.0, 9001.0, ...),
maschpar.xpa, archiev.xar. DEBUG log with every wire byte in example/logs/.
"""

import argparse
import logging
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.errors import FileTransferError
from pyunitelway.num_constants import Mode

ADAPTER = ("10.1.70.202", 8234)
HERE = Path(__file__).parent
log = logging.getLogger("backup")


def setup_logging(stamp):
    """INFO on the console, DEBUG with every wire byte in example/logs/backup-<stamp>.log."""
    (HERE / "logs").mkdir(exist_ok=True)
    console, file = logging.StreamHandler(sys.stdout), logging.FileHandler(HERE / "logs" / f"backup-{stamp}.log")
    console.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file], datefmt="%H:%M:%S",
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")


def require_idle(client):
    """Exit unless no programme runs and the NC is not in EDIT."""
    status = client.get_unit_status()
    mode, running = status["nc_mode"], status["nc_status"]["active_program"]
    if running or mode == Mode.EDIT:
        sys.exit(f"NC not idle (programme running={running}, mode={mode.name}): refusing to open a file")
    log.info("NC idle: mode %s, active programme %%%d", mode.name, status["current_program_number"])


def backup(client, out, timeout):
    """Read everything into ``out``; return the number of files the NC refused."""
    programs = client.read_directory()  # safe at any time: the directory does not take the transfer slot
    (out / "directory.txt").write_text("".join(f"{p.name:<12} {p.size:>8} bytes\n" for p in programs))
    log.info("directory: %d programme(s)", len(programs))
    require_idle(client)
    files = {p.name.lstrip("%"): partial(client.read_program, p.number, p.group, timeout) for p in programs}
    files["maschpar.xpa"] = partial(client.read_machine_parameters, timeout)
    files["archiev.xar"] = partial(client.read_plc_archive, timeout)
    failed = 0
    for name, read in files.items():
        try:
            data = read()
        except FileTransferError as e:
            log.error("%s: %s", name, e)
            failed += 1
            continue
        (out / name).write_bytes(data)
        log.info("%s: %d bytes", name, len(data))
    log.info("%d of %d files read -> %s", len(files) - failed, len(files), out)
    return failed



def main():
    ap = argparse.ArgumentParser(description="Full backup of the NC: programmes, machine parameters, PLC archive.")
    ap.add_argument("--out", type=Path, help="output folder (default example/backup/<timestamp>)")
    ap.add_argument("--timeout", type=float, default=10, help="answer wait per attempt in seconds (default 10)")
    args = ap.parse_args()
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    setup_logging(stamp)
    out = args.out or HERE / "backup" / stamp
    out.mkdir(parents=True, exist_ok=True)
    client = UnitelwayClient()  # nothing writable: this script only reads
    client.connect_socket(*ADAPTER)
    try:
        failed = backup(client, out, args.timeout)
    finally:
        client.disconnect_socket()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
