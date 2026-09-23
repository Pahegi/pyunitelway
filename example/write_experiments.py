"""Bit, byte and word writes on unnamed PLC working memory, through write_ladder. One approval per run.

%V7800/%V7801: named in no symbol table, read or written by no ladder network, 2 KB clear of the IPC
hand-over block %V7000-%V7087 (bundle: sps symbol tables, trace_signal.py). Every step is logged and
checked; the script aborts at the first mismatch but always restores the two bytes.

Settled 2026-09-23 15:23 with raw Write-Object frames: any non-zero data byte sets a bit (0x01 and
0x80 both did), 0x00 clears; a word write with QUANTITY 1 wrote both bytes. This script now exercises
the same steps through the guarded public API.

Usage::

    poetry run write_experiments --dry-run
    poetry run write_experiments             # live, after approval
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.utils import format_hex_list

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234
BASE = 0x7800
B0, B1, W0 = "%V7800.B", "%V7801.B", "%V7800.W"
PATTERN = 0x52  # 0101 0010: bit 3 clear, so a bit-3 set is visible

log = logging.getLogger("write_experiments")


class Mismatch(Exception):
    pass


def setup_logging():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"write-experiments-{datetime.now():%Y%m%d-%H%M%S}.log"
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
    client = UnitelwayClient(writable={B0, B1, W0, "%V7800.3"})
    mem = {BASE: 0, BASE + 1: 0}

    def fake(address, query, timeout=None, text=""):
        log.info("dry-run tx %s: %s", text, format_hex_list(query))
        seg, spec, addr = query[2], query[3], query[4] | query[5] << 8
        if query[0] == 0x36:
            if spec == 65:
                return [0x66, 65, mem[addr + 1], mem[addr]]
            return [0x66, spec, mem[addr]]
        data = query[8:]
        if spec == 64:
            mem[addr] = data[0]
        elif spec == 65:
            mem[addr], mem[addr + 1] = data[1], data[0]
        else:  # bit: non-zero sets
            mem[addr] = mem[addr] | 1 << spec if data[0] else mem[addr] & ~(1 << spec)
        return [0xFE]

    client.run_unite = fake
    return client


def run(client):
    rb = lambda var: client.read_ladder(var, signed=False)
    old0, old1 = rb(B0), rb(B1)
    log.info("before: %s = 0x%02X, %s = 0x%02X", B0, old0, B1, old1)
    try:
        # byte write
        expect(f"write {B0} = 0x{PATTERN:02X}", client.write_ladder(B0, PATTERN, signed=False), True)
        expect(f"read back {B0}", rb(B0), PATTERN)

        # bit 3 set and cleared
        expect(f"write {B0[:-1]}3 = True", client.write_ladder(B0[:-1] + "3", True), True)
        expect(f"read back {B0}", rb(B0), PATTERN | 0x08)
        expect(f"read {B0[:-1]}3", client.read_ladder(B0[:-1] + "3"), True)
        expect(f"write {B0[:-1]}3 = False", client.write_ladder(B0[:-1] + "3", False), True)
        expect(f"read back {B0}", rb(B0), PATTERN)

        # word: count 1 writes both bytes, first byte MSB
        expect(f"write {W0} = 0x1234", client.write_ladder(W0, 0x1234), True)
        expect(f"read back {B0}", rb(B0), 0x12)
        expect(f"read back {B1}", rb(B1), 0x34)
        expect(f"read back {W0}", rb(W0), 0x1234)
    finally:
        expect(f"restore {B0} = 0x{old0:02X}", client.write_ladder(B0, old0, signed=False), True)
        expect(f"restore {B1} = 0x{old1:02X}", client.write_ladder(B1, old1, signed=False), True)
        expect(f"read back {B0}", rb(B0), old0)
        expect(f"read back {B1}", rb(B1), old1)
    log.info("all steps passed")


def main():
    setup_logging()
    if "--dry-run" in sys.argv:
        log.info("DRY RUN: nothing is sent")
        run(dry_run_client())
        return
    client = UnitelwayClient(writable={B0, B1, W0, "%V7800.3"})
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
