"""Minimal tour of the library against the NUM 1060: every request once, in the order you would use them.

Reads first. The writes at the end are the ones verified harmless on this machine: the mode round-trip, a
scratch byte on unnamed %V memory, a screen message. Physical actions stay commented out. Every exchange is
logged as one line with the decoded answer; DEBUG would show every wire byte. Run with the machine idle::

    poetry run test
"""

import logging
import time

from pyunitelway import UnitelwayClient
from pyunitelway.num_constants import Mode, Object

logging.basicConfig(level=logging.INFO)


def main():
    client = UnitelwayClient(writable={Object.MODE_SELECTION, "%V7800.B"})  # everything else stays locked
    client.connect_socket("10.1.70.202", 8234)  # USR-TCP232-306 -> COMM1; the master polls link address 0x01

    # link and NC status
    client.mirror([0x00])                          # True: the NC echoed our bytes
    client.get_unit_identification()               # {'text': 'NUM1060S2UCS2', ...}
    client.get_unit_status()                       # mode, programme, G list, NC/PLC status (segment 153 decoded)
    client.get_available_bytes_in_ram()            # free part-programme memory
    client.get_stations_managed_by_master()        # (count, [bool per station])
    client.get_unit_fault_history()

    # NC objects and ladder variables (938914 §4.1.3, 938846 §3.8)
    client.read_mode()                             # Mode.AUTO, ...
    client.read_object(Object.CURRENT_PROGRAMME_NUMBER)
    client.read_cycle_in_progress()                # %R3.2 E_CYCLE
    client.read_ladder("%R5.0")                    # bit -> bool: E_CNPRET CNC ready
    client.read_ladder("%R16.B")                   # byte -> int: MODCOUR current mode
    client.read_ladder("%R1A.W")                   # word: PROGCOUR active programme
    client.read_ladder("%R6.L")                    # long: AXMVT axes in motion
    client.read_ladder("%I0123.B", signed=False)   # feed pot 0-255
    client.read_vacuum_pump()                      # %Q0700.6 contactor; also read_extraction_hood/_long_workpiece/_wide_workpiece

    # files (938914 §4.13, §4.16); the NC has one transfer slot, upload() always closes it
    programs = client.read_directory()             # [Program(number, group, size), ...]
    client.read_program(programs[0].number, programs[0].group)  # bytes as stored, CRLF line ends
    client.read_machine_parameters()               # the .xpa text
    # client.read_plc_archive()                    # all ladder and C modules, 111 KB, about 3 minutes

    # writes: each needs its entry in writable=
    mode = client.read_mode()
    client.write_mode(Mode.MANUAL)                 # segment 180; read back over read_mode and %R16.B
    time.sleep(0.5)
    client.read_mode()
    client.write_mode(mode)
    old = client.read_ladder("%V7800.B")           # unnamed scratch byte, used by no ladder network
    client.write_ladder("%V7800.B", 0x52)
    client.read_ladder("%V7800.B")
    client.write_ladder("%V7800.B", old)
    client.write_message("PYUNITELWAY TEST")       # NC screen: E/A -> Fehlermeldungen -> Netz-Meldungen

    # physical actions: unlock deliberately, only with someone at the machine
    # client.write_vacuum_pump(True)               # writable={"%Q0700.6"}; write_extraction_hood/_long_workpiece/_wide_workpiece likewise
    # client.cycle_start()                         # writable={Action.CYCLE_START}: starts the selected programme or MDI block
    # client.feed_stop()                           # writable={Action.FEED_STOP}: never sent yet

    client.disconnect_socket()


if __name__ == "__main__":
    main()
