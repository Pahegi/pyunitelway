# Pyunitelway NUM 1060

This is a fork of the original [Pyunitelway](https://github.com/Purecontrol/pyunitelway) library adapted to work with the NUM 1060.
It implements a transport layer unitelway client and multiple application layer UNITE requests.

Verified on the machine (2026-09-22; the frames are regression vectors in `tests/test_hardware_vectors.py`):

* `mirror` - link test
* `get_unit_identification`, `get_unit_status`, `get_available_bytes_in_ram`
* `read_mode` / `read_object` - NC objects, e.g. the operating mode as a `Mode` enum
* `read_ladder` - PLC variables `%M %V %I %Q %R %W %S` as bit, byte, word or long word (verified on every segment)
* `get_stations_managed_by_master`, `get_unit_fault_history`

Verified live write: `write_mode` (segment 180, MANUAL and back to AUTO, read back over both
`read_mode` and `%R16.B`); `write_ladder` (2026-09-23: MSG2 `%W16.B` written and restored, bit and word writes
on unnamed `%V` memory, all read back; `write_vacuum_pump(True/False)` = `%Q0700.6`, started and stopped the pump); `cycle_start()` (UNI-TE Run, 2026-09-26: a `G4 F2` MDI block ran, a `G0 X2000` moved the machine; `read_cycle_in_progress` = `%R3.2`; `cycle_stop()` = UNI-TE Stop, the CYHLD machining stop, verified the same evening); `write_message`
(shown under E/A → Fehlermeldungen → Netz-Meldungen). Same pattern, not yet sent: `write_extraction_hood`,
`write_long_workpiece`, `write_wide_workpiece` (panel latches `%Q0100.3`, `%Q0100.4`, `%Q0101.4`).
One lock for every write: nothing is writable unless
`UnitelwayClient(writable={...})` names the ladder segment (`"%W"`), the variable (`"%W16.B"`) or the NC
object (`Object.MODE_SELECTION`); `ALL_LADDER_SEGMENTS` / `ALL_NC_OBJECTS` open everything. `write_object` for the other families is
unit-tested only.

File reading (938914 §4.13/§4.16), verified on the machine 2026-09-26: `read_directory` lists the part programmes in
the NC RAM (48, in four answers); `read_program`, `read_machine_parameters`, `read_plc_archive` upload one file as bytes
(open, segments of up to 122 bytes, close in every case; `%101`/`%35` byte-identical to the 2023 NCDat backup, the
parameters `.xpa` and the 111 KB ladder archive read without a resend). No download, no Delete-File.

## Usage

```python
import logging
from pyunitelway import UnitelwayClient

logging.basicConfig(level=logging.INFO)   # one line per exchange; DEBUG shows every wire byte
client = UnitelwayClient()                 # link address 0x01
client.connect_socket("10.1.70.202", 8234)
client.mirror([0x00])                      # True
client.read_mode()                         # <Mode.AUTO: 0>
client.read_ladder("%R1A.W")               # 9001 - the active programme
client.disconnect_socket()
```

```bash
poetry run listen        # receive only: which link addresses does the master poll?
poetry run test          # minimal tour: every request once; only writes are the mode round-trip, a scratch byte, a screen message
poetry run panel         # the operator panel (buttons, lamps, key switch, pots) as the PLC sees it; --watch 1
poetry run backup        # full backup: every part programme, machine parameters, PLC archive -> example/backup/<timestamp>/
poetry run pytest        # spec and hardware vectors, no machine needed
```

## Relevant documentation

* [Schneider Electric - UNI-TELWAY reference manual](https://download.schneider-electric.com/files?p_enDocType=User+guide&p_File_Name=35000789_K06_000_00.pdf&p_Doc_Ref=35000789K01000)
* [NUM 1060 - USE OF THE UNI-TE PROTOCOL - en-938914/0](https://shop.num.com/pi/Spezifische-Handbuecher/NUM-10xx-Power-Axium/Spezifische-Dokumentation/spezifische-dokumente-vers-e.html)
* [NUM 1020/1040/1060 - UNI-TELWAY INTEGRATION MANUAL - 0101938880/2](https://shop.num.com/pi/Spezifische-Handbuecher/NUM-10xx-Power-Axium/Spezifische-Dokumentation/spezifische-dokumente-vers-e.html)
* [NUM - AUTOMATIC CONTROL FUNCTION PROGRAMMING MANUAL LADDER LANGUAGE - 0101938846/8](https://shop.num.com/pi/Spezifische-Handbuecher/NUM-10xx-Power-Axium/NUMTool-Workshop/num-tool-workshop-handbcher.html)
* [NUM 1060 - PC MODULE - 0101938928/2](https://cncmanual.com/num-1060-pc-module-manual/)

## How to use ?

This library is designed to use a TCP-RS485 adapter. The adapter is connected to the PC or server which uses this lib via Ethernet or Wi-fi or anything else, and is connected to the NUM 1060 via RS232 on port COMM1 at the UC SII. Parameter
P112 has to be configured accordingly and the port has to be changed to "I-Port is private to PLC".

This library was developed using the USR-TCP232-306 adapter. It was not tested with another kind of connection.

![Setup explanation](docs/source/pyunitelway_setup_schema.png)

*Test setup*
