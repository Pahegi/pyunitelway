"""Read-only connectivity check against the NUM 1060.

Every request below is a read. The writes (mode selection, supervisor message, ladder writes,
shutdown) stay commented out; uncomment one deliberately, never as a side effect of a test run.

Runs at debug level 2 and tees the whole output, every wire byte included, to
``example/logs/test-<timestamp>.log`` so the machine's real answers can become test vectors.
Each request runs in its own try/except so one failure does not hide the others.
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path

from pyunitelway import UnitelwayClient
from pyunitelway.num_constants import Object, Mode

debug = 2

ADAPTER_IP = "10.1.70.202"
ADAPTER_PORT = 8234


class Tee:
    """Write to the terminal and to a line-buffered log file at the same time."""

    def __init__(self, path):
        self.terminal = sys.stdout
        self.file = open(path, "w", buffering=1)

    def write(self, text):
        self.terminal.write(text)
        self.file.write(text)

    def flush(self):
        self.terminal.flush()
        self.file.flush()


def attempt(label, call):
    """Run one request, print its result or its traceback, and carry on."""
    print(f"\n======== {label} ========", flush=True)
    try:
        result = call()
        print(f"{label} -> {result!r}", flush=True)
        return result
    except Exception:
        print(f"{label} FAILED:", flush=True)
        traceback.print_exc(file=sys.stdout)
        return None


def main():
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"test-{datetime.now():%Y%m%d-%H%M%S}.log"
    sys.stdout = Tee(log_path)
    print(f"Logging to {log_path}")

    client = UnitelwayClient()  # slave_address=0x01 by default - check with `poetry run listen` first
    client.connect_socket(ADAPTER_IP, ADAPTER_PORT)
    # client.connect_socket("127.0.0.1", 8234)  # used for debug mockup server

    # ---- read-only requests ----
    attempt("mirror", lambda: client.mirror([0x00], debug))  # ping the NUM 1060
    attempt("unit identification", lambda: client.get_unit_identification(debug))  # e.g. NUM 1060 UC SII
    attempt("unit status", lambda: client.get_unit_status(debug=debug))  # mode, programme number, G functions, ...
    attempt("available bytes in NC RAM", lambda: client.get_available_bytes_in_ram(debug))
    attempt("read object: mode", lambda: client._read_objects(Object.MODE_SELECTION, 0x00, 0x00, 0x01, debug))
    attempt("stations managed by master", lambda: client.get_stations_managed_by_master(debug))
    attempt("unit fault history", lambda: client.get_unit_fault_history(debug))

    # ---- writes: keep commented out unless you mean it ----
    # print(client.write_message("Hello World!", debug))  # displays text on the NC (A8: cannot send yet)
    # print(client._write_objects(Object.MODE_SELECTION, 0x00, 0x00, 0x01, [Mode.MDI, 0x00], debug))  # sets the mode (Mode.AUTO = 0, Mode.MDI = 2)

    # read ladder
    # print(client.read_ladder("%R5.1"))  # program active
    # print(client.read_ladder("%R16.B"))  # current mode
    # print(client.read_ladder("%R1A.W"))  # active program number
    # print(client.read_ladder("%R14.1"))  # battery status
    # print(client.read_ladder("%R17.B"))  # displayed page number
    # print(client.read_ladder("%R18.B"))  # machine error number

    # write ladder
    # print(client.write_ladder("%W3.2", 0x01))  # cycle start set (needs reset)
    # print(client.write_ladder("%W3.2", 0x00))  # cycle start reset
    #
    # print(client.write_ladder("%W3.1", 0x01))  # cycle stop set (needs reset)
    # print(client.write_ladder("%W3.1", 0x00))  # cycle stop reset
    #
    # print(client.write_ladder("%W3.0", 0x01))  # reset request
    #
    # print(client.write_ladder("%W15.B", 210))  # output message N210 $ Werkzeug-Nr. falsch gewaehlt

    # tests

    # read ladder
    # client.read_ladder("%MA.0")

    # write object request (mode)
    # _write_objects:    [10,02,01,0F,20,00,FE,00,00,00,37,00,B4,00,00,00,01,00,02,2E]
    # custom:         [10,02,01,10,10,20,00,FE,00,00,00,37,00,B4,00,00,00,01,00,02,00,44]
    # # write mode request
    # message = []
    # message.append(0x37) # request code
    # message.append(0x00) # category code
    # message.append(0xb4) # segment (object address)
    # message.append(0x00) # size of plc object
    # message.append(0x00) # address of object in family (simple offset?) 1
    # message.append(0x00) # address of object in family (simple offset?) 2
    # message.append(0x01) # number of objects to read (bytes) 1
    # message.append(0x00) # number of objects to read (bytes) 2
    # message.append(0x07) # mode 1 (0 for auto, 7 for manual)
    # message.append(0x00) # mode 2

    # r = client.run_unite(slave_address, message, 0x02, "write current mode" , 1)
    # print(r)

    # # file download test
    # message = []
    # message.append(0x3a) # request code
    # message.append(0x00) # category code
    # message.append(0x06) # file type code
    # message.append(0x41) # additional identification 1
    # message.append(0x00) # additional identification 2 not significant for text files
    # message.append(0x00) # additional identification 3 not significant for text files
    # message.append(0x00) # additional identification 4 not significant for text files
    # message.append(0x01) # extension code
    # filename = "9002.0"
    # for c in filename:
    #     message.append(ord(c))
    # r = client.run_unite(slave_address, message, 0x02, "file download test" , 1)
    # print(r)
    #
    # # transfer segment
    #
    #
    # # close file download
    # message = []
    # message.append(0x3c) # request code
    # message.append(0x00) # category code
    # r = client.run_unite(slave_address, message, 0x02, "close file download" , 1)
    # print(r)

    # client.shutdown()
    client.disconnect_socket()


if __name__ == "__main__":
    main()
