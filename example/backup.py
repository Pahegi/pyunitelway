"""Read files out of the NC over UNI-TE (938914 §4.13, §4.16) and save them like the NCDat backup.

Every request is a read, but Open-Upload-Sequence takes the NC's single transfer slot, so the script
first checks that no programme is running and the NC is not in EDIT, and refuses otherwise.

Usage::

    poetry run backup --directory                # part programmes in the NC RAM, with sizes -> directory.txt
    poetry run backup --program 101 35 146.1     # %101.0, %35.0, %146.1 -> 101.0, 35.0, 146.1
    poetry run backup --parameters               # machine parameters -> maschpar.xpa
    poetry run backup --archive                  # all ladder and C modules -> archiev.xar
    poetry run backup --all                      # every listed programme except the active one
    poetry run backup --dry-run --all            # offline: canned NC, frames logged

Output: example/backup/<timestamp>/ (gitignored); DEBUG log in example/logs/.
Live only after Paul approved that exact command.
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.errors import FileTransferError
from pyunitelway.constants import (
    CLOSE_DIRECTORY,
    CLOSE_UPLOAD,
    DIRECTORY,
    OPEN_DIRECTORY,
    OPEN_UPLOAD,
    READ_UPLOAD,
    SPECIFIC_REQUEST,
    STATUS,
    TIMEOUT_SEC,
)
from pyunitelway.num_constants import PLC_ALL_MODULES, FileType, Mode, program_index
from pyunitelway.utils import file_identification, format_hex_list

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234
SEGMENT = 122  # data bytes per Read-Upload-Segment (938914 §4.13.2)

log = logging.getLogger("backup")


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"backup-{datetime.now():%Y%m%d-%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    file = logging.FileHandler(log_path)
    file.setLevel(logging.DEBUG)
    file.setFormatter(fmt)
    logging.basicConfig(level=logging.DEBUG, handlers=[console, file])
    log.info("logging to %s", log_path)


def parse_program(name):
    """``'101'``, ``'%146.1'`` -> (number, group)."""
    number, _, group = name.lstrip("%").partition(".")
    return int(number), int(group or 0)


def require_idle(client):
    """Exit unless no programme runs and the NC is not in EDIT; return the active programme number."""
    status = client.get_unit_status()
    mode, running = status["nc_mode"], status["nc_status"]["active_program"]
    active = status["current_program_number"]  # PROGCOUR %R1A.W
    if running or mode == Mode.EDIT:
        sys.exit(f"NC not idle (programme running={running}, mode={mode.name}): refusing to open a file")
    log.info("NC idle: mode %s, active programme %%%d", mode.name, active)
    return active


def save(out, name, read):
    """Read one file and write it; a refusal by the NC is logged and the run goes on."""
    try:
        data = read()
    except FileTransferError as e:
        log.error("%s: %s", name, e)
        return False
    path = out / name
    path.write_bytes(data)
    log.info("%s: %d bytes -> %s", name, len(data), path)
    return True


def run(client, args, out):
    """Return ``True`` when every requested file was read."""
    programs, results = [], []
    if args.directory or args.all:
        programs = client.read_directory()
        lines = [f"{p.name:<12} {p.size:>8} bytes" for p in programs]
        log.info("directory: %d programme(s)\n%s", len(programs), "\n".join(lines))
        (out / "directory.txt").write_text("\n".join(lines) + "\n")
    wanted = [parse_program(n) for n in args.program]
    if wanted or args.parameters or args.archive or args.all:
        active = require_idle(client)
        if args.all:
            wanted += [(p.number, p.group) for p in programs if p.number != active]
    for number, group in wanted:
        results.append(save(out, f"{number}.{group}", lambda: client.read_program(number, group, args.timeout)))
    if args.parameters:
        results.append(save(out, "maschpar.xpa", lambda: client.read_machine_parameters(args.timeout)))
    if args.archive:
        results.append(save(out, "archiev.xar", lambda: client.read_plc_archive(args.timeout)))
    if results:
        log.info("%d of %d file(s) read", sum(results), len(results))
    return all(results)


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
            program_index(101): b"%101\nN10L160=2500L161=550L162=10\nM02\n",
            program_index(35): b"%35 (Kreistasche fraesen)\n" + b"N10 G01 X100\n" * 9,  # two segments
            program_index(9001): b"%9001\nWZLIST=427,435,\nM02\n",
            program_index(9002): b"",  # 'programme empty'
        }
        self.files = {tuple(file_identification(FileType.PART_PROGRAM, i)): d for i, d in self.programs.items()}
        self.files[tuple(file_identification(FileType.MACHINE_PARAMETERS))] = b"P84N0:t5n1;0A\n" * 20
        self.files[tuple(file_identification(FileType.PLC_LADDER, PLC_ALL_MODULES << 16))] = bytes(range(256)) * 3
        self.open = None  # the file being uploaded
        self.listing = []  # directory entries not yet answered

    def run_unite(self, address, query, timeout=None, text=""):
        log.info("dry-run tx %s: %s", text, format_hex_list(query))
        code, arg = query[0], query[2:]
        if code == STATUS:
            return IDLE_STATUS
        if code == OPEN_UPLOAD:
            self.open = self.files.get(tuple(arg))
            return [0x6D, 5 if self.open is None else 15 if not self.open else 0]
        if code == READ_UPLOAD:
            if self.open is None:
                return [0x6E, 4, *arg, 0, 0]
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
            start = int.from_bytes(arg[1:5], "little")
            self.listing = sorted(i for i in self.programs if i >= start)
            return self.page(0x78)
        if code == SPECIFIC_REQUEST and arg[0] == DIRECTORY:
            return self.page(0x79)
        if code == SPECIFIC_REQUEST and arg[0] == CLOSE_DIRECTORY:
            self.listing = []
            return [0xF5, 0x7A, 0]
        raise AssertionError(query)

    def page(self, code):
        page, self.listing = self.listing[:15], self.listing[15:]
        data = []
        for i in page:
            data += [*i.to_bytes(4, "little"), *len(self.programs[i]).to_bytes(4, "little")]
        return [0xF5, code, 0 if self.listing else 15, *data]


def main():
    parser = argparse.ArgumentParser(description="Read files out of the NC and save them like the NCDat backup.")
    parser.add_argument("--directory", action="store_true", help="list the part programmes in the NC RAM")
    parser.add_argument("--program", nargs="+", default=[], metavar="N[.G]", help="part programme(s) to read")
    parser.add_argument("--parameters", action="store_true", help="machine parameters -> maschpar.xpa")
    parser.add_argument("--archive", action="store_true", help="all ladder and C modules -> archiev.xar")
    parser.add_argument("--all", action="store_true", help="every programme the directory lists, except the active one")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SEC, help="answer wait per attempt, seconds")
    parser.add_argument("--out", type=Path, help="output folder (default example/backup/<timestamp>)")
    parser.add_argument("--dry-run", action="store_true", help="offline: canned NC, nothing is sent")
    args = parser.parse_args()
    if not (args.directory or args.program or args.parameters or args.archive or args.all):
        parser.error("nothing to do: give --directory, --program, --parameters, --archive or --all")
    setup_logging()
    out = args.out or Path(__file__).parent / "backup" / f"{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    client = UnitelwayClient()  # nothing writable: this script only reads
    if args.dry_run:
        log.info("DRY RUN: nothing is sent")
        client.run_unite = FakeNC().run_unite
        sys.exit(0 if run(client, args, out) else 1)
    client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    try:
        ok = run(client, args, out)
    finally:
        client.disconnect_socket()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
