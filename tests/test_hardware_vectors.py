"""Answers captured from the real NUM 1060 Series II UC SII (Makerspace Darmstadt).

Captured 2026-09-22 with ``example/test.py`` at debug=2 (``example/logs/test-20260922-202236.log``):
USR-TCP232-306 at 10.1.70.202:8234, this client at link address 0x01 (the only address the master
polls), NC idle in AUTO, programme %9001 selected, PLC running. Each vector is the complete
UNI-TELWAY frame as received, so these pin the whole unwrap + parse path against what the machine
actually sends - not against the manual.
"""

from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.num_constants import Mode
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_mirror_result,
    parse_stations_managed_by_master,
    parse_unit_fault_history,
    parse_unit_identification,
    parse_unit_status,
)


def frame(hex_string):
    return [int(x, 16) for x in hex_string.split()]


MIRROR = frame("10 02 01 08 20 00 fe 00 00 00 fb 00 34")
IDENTIFICATION = frame("10 02 01 18 20 00 fe 00 00 00 3f 66 48 20 0d 4e 55 4d 31 30 36 30 53 32 55 43 53 32 bc")
STATUS = frame(
    "10 02 01 39 20 00 fe 00 00 00 61 00 30 02 09 11 11 9a 5f 01 00 00 00 00 00 00 00 00 00 04 00 00 00 "
    "00 00 00 01 00 00 29 23 02 00 00 00 ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff 65"
)
MEMORY_FREE = frame("10 02 01 0d 20 00 fe 00 00 00 f5 77 00 02 3d 04 00 ed")
READ_MODE = frame("10 02 01 0a 20 00 fe 00 00 00 66 00 00 00 a1")
STATIONS = frame("10 02 01 09 20 00 fe 00 00 00 d3 01 80 8e")
READ_CPT = frame("10 02 01 0f 20 00 fe 00 00 00 d2 00 00 00 00 00 00 00 00 12")


def test_mirror():
    assert parse_mirror_result(unwrap_unite_response(MIRROR)[1:], [0x00]) is True


def test_identification():
    ident = parse_unit_identification(unwrap_unite_response(IDENTIFICATION))
    # product type 102 is "NUM 1040" in the 938914 table, yet the text names the UC SII
    assert ident["product_type_code"] == 102
    assert ident["subtype"] == "H"
    assert ident["product_version"] == 2
    assert ident["text"] == "NUM1060S2UCS2"


def test_status():
    unite = unwrap_unite_response(STATUS)
    # 51 UNI-TE bytes, not the 48 of 938914 §4.4: the machine sends 19 bytes of PLC memory field
    assert len(unite) == 51
    status = parse_unit_status(unite)
    assert not any(status["current_status"].values())
    assert status["status_mask"]["system_reset"] and status["status_mask"]["critical_operation"]
    # the idle NC's power-on modal set - only readable with the G functions first (938846 §15.2
    # order, not 938914 §4.1.3) and the corrected bit numbering; the old numbering gives G19 G91 G41 G29
    assert [g for g, on in status["list_of_g_functions"].items() if on] == ["G01", "G17", "G90", "G40", "G54", "G94", "G97"]
    assert status["active_program_number"] == 9001  # on the wire: 90010
    assert status["active_block_number"] == 0
    assert status["program_error_number"] == 0
    assert status["tool_number"] == 0
    assert status["tool_direction"] == {"x": 0, "y": 0, "z": -1}  # vertical machine: tool axis Z-
    assert not any(status["list_of_processes_remaining"].values())
    assert status["operator_panel_status"]["cycle_in_progress"] is False
    assert status["nc_status"]["cnc_ready"] is True and status["nc_status"]["active_program"] is False
    assert status["nc_mode"] == Mode.AUTO
    assert status["machine_error_number"] == 0
    assert status["current_program_number"] == 9001
    assert status["plc_status"] == "running"
    assert status["plc_memory_field"] == [0, 0, 0] + [0xFF] * 16


def test_memory_free():
    unite = unwrap_unite_response(MEMORY_FREE)
    assert unite[:2] == [0xF5, 0x77]
    assert parse_available_bytes_in_ram(unite) == 277762


def test_read_mode_quantity_one_returns_one_word():
    # segment 180 (mode selection), QUANTITY 1 -> two data bytes: QUANTITY counts objects, not bytes
    unite = unwrap_unite_response(READ_MODE)
    assert unite == [0x66, 0x00, 0x00, 0x00]
    assert int.from_bytes(unite[2:], "little") == Mode.AUTO


def test_stations():
    # one managed station (this client, link address 1), reported in the MSB
    assert parse_stations_managed_by_master(unwrap_unite_response(STATIONS)) == (1, [True])


def test_read_cpt():
    assert parse_unit_fault_history(unwrap_unite_response(READ_CPT)) == (0, 0, 0, 0)
