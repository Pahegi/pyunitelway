"""Passive UNI-TELWAY bus listener.

Connects to the TCP<->serial adapter and only *receives* for a while, then reports which link
addresses the master polls (``<DLE><ENQ><addr>``, 35000789 §3.6) and any frames
(``<DLE><STX><addr>``) that went by. **Nothing is transmitted.** Use it to find the link address
to give ``UnitelwayClient(slave_address=...)`` before sending a first request.

Usage::

    poetry run listen [ip] [port] [seconds]

Defaults match ``example/test.py``. The raw bytes go to ``example/logs/listen-<timestamp>.log``.
"""

import socket
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

DLE, STX, ENQ = 0x10, 0x02, 0x05

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234
SECONDS = 10.0


def capture(ip, port, seconds):
    """Receive for ``seconds`` and return everything the adapter sent."""
    print(f"Connecting to {ip}:{port} (receive only, {seconds:.0f} s)")
    s = socket.create_connection((ip, port), timeout=5)
    s.settimeout(1.0)
    buf = bytearray()
    deadline = time.time() + seconds
    try:
        while time.time() < deadline:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                print("Adapter closed the connection")
                break
            buf += chunk
    finally:
        s.close()
    return bytes(buf)


def analyse(data):
    """Count ``<DLE><ENQ><addr>`` polls and ``<DLE><STX><addr>`` frame headers."""
    polls, frames = Counter(), Counter()
    i = 0
    while i < len(data) - 2:
        if data[i] == DLE and data[i + 1] == ENQ:
            polls[data[i + 2]] += 1
            i += 3
        elif data[i] == DLE and data[i + 1] == STX:
            frames[data[i + 2]] += 1
            i += 3
        else:
            i += 1
    return polls, frames


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else ADAPTER_IP
    port = int(sys.argv[2]) if len(sys.argv) > 2 else ADAPTER_PORT
    seconds = float(sys.argv[3]) if len(sys.argv) > 3 else SECONDS

    data = capture(ip, port, seconds)

    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"listen-{datetime.now():%Y%m%d-%H%M%S}.log"
    log_path.write_text(
        f"# passive capture {ip}:{port}, {seconds:.0f} s, {len(data)} bytes\n"
        + " ".join(f"{b:02X}" for b in data) + "\n"
    )

    polls, frames = analyse(data)
    print(f"\n{len(data)} bytes in {seconds:.0f} s ({len(data) / seconds:.0f} B/s), raw dump in {log_path}")
    if not data:
        print("Nothing received: wrong IP/port, NUM off, or the adapter is not in TCP server mode.")
        return
    if polls:
        print("\nLink addresses polled by the master (<DLE><ENQ><addr>):")
        for addr, n in sorted(polls.items()):
            print(f"  0x{addr:02X}  {n:5d} polls  ({n / seconds:.1f}/s)")
        print("\nPass one of these as UnitelwayClient(slave_address=0x..) - lowest first.")
    else:
        print("\nNo <DLE><ENQ> polling seen. Either the link is idle or the serial settings do not match P112.")
    if frames:
        print("\nFrames seen (<DLE><STX><addr>) - another station is talking on this link:")
        for addr, n in sorted(frames.items()):
            print(f"  0x{addr:02X}  {n:5d} frames")


if __name__ == "__main__":
    main()
