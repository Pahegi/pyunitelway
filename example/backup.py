"""Full backup of the NC over UNI-TE (938914 §4.13, §4.16): every part programme, the machine parameters and the
PLC archive, saved like the NCDat backup. Read-only. Open-Upload-Sequence takes the NC's single transfer slot,
so nothing is opened while a programme runs or the NC is in EDIT. Verified on the machine 2026-09-26.

Usage::

    poetry run backup [--out DIR] [--timeout S]   # live, only after Paul approved the run
    poetry run backup --dry-run                   # canned NC, nothing is sent

Output in example/backup/<timestamp>/ (gitignored): directory.txt, one file per programme (101.0, 9001.0, ...),
maschpar.xpa, archiev.xar. DEBUG log with every wire byte in example/logs/.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.constants import (
    CLOSE_DIRECTORY,
    CLOSE_UPLOAD,
    DIRECTORY,
    OPEN_DIRECTORY,
    OPEN_UPLOAD,
    READ_UPLOAD,
    SPECIFIC_REQUEST,
    STATUS,
)
from pyunitelway.errors import FileTransferError
from pyunitelway.num_constants import PLC_ALL_MODULES, FileType, Mode, program_index
from pyunitelway.utils import file_identification, format_hex_list

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234
SEGMENT = 122  # data bytes per Read-Upload-Segment (938914 §4.13.2)

log = logging.getLogger("backup")


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    file = logging.FileHandler(log_dir / f"backup-{datetime.now():%Y%m%d-%H%M%S}.log")
    for h in (console, file):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file])


def require_idle(client):
    """Exit unless no programme runs and the NC is not in EDIT."""
    status = client.get_unit_status()
    mode, running = status["nc_mode"], status["nc_status"]["active_program"]
    if running or mode == Mode.EDIT:
        sys.exit(f"NC not idle (programme running={running}, mode={mode.name}): refusing to open a file")
    log.info("NC idle: mode %s, active programme %%%d", mode.name, status["current_program_number"])


def backup(client, out, timeout):
    """Read everything into ``out``; return the number of files the NC refused."""
    programs = client.read_directory()
    (out / "directory.txt").write_text("".join(f"{p.name:<12} {p.size:>8} bytes\n" for p in programs))
    log.info("directory: %d programme(s)", len(programs))
    require_idle(client)
    jobs = [(p.name.lstrip("%"), lambda p=p: client.read_program(p.number, p.group, timeout)) for p in programs]
    jobs += [("maschpar.xpa", lambda: client.read_machine_parameters(timeout)),
             ("archiev.xar", lambda: client.read_plc_archive(timeout))]
    failed = 0
    for name, read in jobs:
        try:
            data = read()
        except FileTransferError as e:
            log.error("%s: %s", name, e)
            failed += 1
            continue
        (out / name).write_bytes(data)
        log.info("%s: %d bytes", name, len(data))
    log.info("%d of %d files read -> %s", len(jobs) - failed, len(jobs), out)
    return failed


# Unit status captured on the machine 2026-09-22: idle in AUTO, active programme %9001
IDLE_STATUS = [
    0x61, 0x00, 0x30, 0x02, 0x09, 0x11, 0x11, 0x9A, 0x5F, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x29, 0x23, 0x02, 0x00, 0x00,
    0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
]


class FakeNC:
    """``--dry-run``: canned answers with one transfer slot, like the NC."""

    def __init__(self):
        self.programs = {
            program_index(101): b"%101\r\nN10L160=2500L161=550L162=10\r\nM2\r\n",
            program_index(35): b"%35 (Kreistasche fraesen)\r\n" + b"N10 G01 X100\r\n" * 9,  # two segments
            program_index(9002): b"",  # 'programme empty'
        }
        self.files = {tuple(file_identification(FileType.PART_PROGRAM, i)): d for i, d in self.programs.items()}
        self.files[tuple(file_identification(FileType.MACHINE_PARAMETERS))] = b"P84N0:t5n1;0A\r\n" * 20
        self.files[tuple(file_identification(FileType.PLC_LADDER, PLC_ALL_MODULES << 16))] = bytes(range(256)) * 3
        self.open = None
        self.listing = []

    def run_unite(self, address, query, timeout=None, text=""):
        log.info("dry-run tx %s: %s", text, format_hex_list(query))
        code, arg = query[0], query[2:]
        if code == STATUS:
            return IDLE_STATUS
        if code == OPEN_UPLOAD:
            self.open = self.files.get(tuple(arg))
            return [0x6D, 5 if self.open is None else 15 if not self.open else 0]
        if code == READ_UPLOAD:
            n = int.from_bytes(arg, "little")
            chunk = self.open[(n - 1) * SEGMENT:n * SEGMENT]
            last = n * SEGMENT >= len(self.open)
            if last:
                self.open = None
            return [0x6E, 15 if last else 0, *arg, *len(chunk).to_bytes(2, "little"), *chunk]
        if code == CLOSE_UPLOAD:
            was_open, self.open = self.open is not None, None
            return [0x6F, 0 if was_open else 4]
        if code == SPECIFIC_REQUEST and arg[0] == OPEN_DIRECTORY:
            self.listing = sorted(self.programs)
        if code == SPECIFIC_REQUEST and arg[0] in (OPEN_DIRECTORY, DIRECTORY):
            page, self.listing = self.listing[:15], self.listing[15:]
            data = [b for i in page for b in (*i.to_bytes(4, "little"), *len(self.programs[i]).to_bytes(4, "little"))]
            return [0xF5, arg[0] + 0x30, 0 if self.listing else 15, *data]
        if code == SPECIFIC_REQUEST and arg[0] == CLOSE_DIRECTORY:
            return [0xF5, 0x7A, 0]
        raise AssertionError(query)


def main():
    ap = argparse.ArgumentParser(description="Full backup of the NC: part programmes, machine parameters, PLC archive.")
    ap.add_argument("--out", type=Path, help="output folder (default example/backup/<timestamp>)")
    ap.add_argument("--timeout", type=float, default=10, help="answer wait per attempt in seconds (default 10)")
    ap.add_argument("--dry-run", action="store_true", help="canned NC, nothing is sent")
    args = ap.parse_args()
    setup_logging()
    out = args.out or Path(__file__).parent / "backup" / f"{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    client = UnitelwayClient()  # nothing writable: this script only reads
    if args.dry_run:
        log.info("DRY RUN: nothing is sent")
        client.run_unite = FakeNC().run_unite
    else:
        client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    try:
        failed = backup(client, out, args.timeout)
    finally:
        if not args.dry_run:
            client.disconnect_socket()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
