"""Answers captured from the real NUM 1060 Series II UC SII (Makerspace Darmstadt).

Captured 2026-09-22 with ``example/test.py`` at debug=2 (``example/logs/test-20260922-202236.log``):
USR-TCP232-306 at 10.1.70.202:8234, this client at link address 0x01 (the only address the master
polls), NC idle in AUTO, programme %9001 selected, PLC running. The mode round-trip vectors are from
``example/logs/test-20260922-220419.log`` (write MANUAL, read back, write AUTO); the panel bytes are
from ``example/logs/panel-20260922-221429.log`` (``poetry run panel``). Each vector is the complete
UNI-TELWAY frame as received, so these pin the whole unwrap + parse path against what the machine
actually sends - not against the manual.
"""

from pyunitelway.client import UnitelwayClient
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.num_constants import Mode
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_ladder_read_response,
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
# ladder reads on segment %R (0xA4), same session, NC idle in AUTO with %9001 selected
LADDER_R5_0 = frame("10 02 01 09 20 00 fe 00 00 00 66 00 80 20")  # %R5.0 E_CNPRET = 1
LADDER_R5_1 = frame("10 02 01 09 20 00 fe 00 00 00 66 01 00 a1")  # %R5.1 E_PROG = 0
LADDER_R16_B = frame("10 02 01 09 20 00 fe 00 00 00 66 40 00 e0")  # %R16.B MODCOUR = AUTO
LADDER_R1A_W = frame("10 02 01 0a 20 00 fe 00 00 00 66 41 29 23 2e")  # %R1A.W PROGCOUR = 9001
LADDER_R6_L = frame("10 02 01 0c 20 00 fe 00 00 00 66 42 00 00 00 00 e5")  # %R6.L AXMVT = 0
LADDER_R1A_W_X2 = frame("10 02 01 0c 20 00 fe 00 00 00 66 41 29 23 00 00 30")  # QUANTITY 2

# mode round-trip 22:04: write_mode(MANUAL) as sent (length 16 = DLE, doubled), its answer, the read-backs
WRITE_MODE_MANUAL_TX = frame("10 02 01 10 10 20 00 fe 00 00 00 37 00 b4 00 00 00 01 00 07 00 44")
WRITE_MODE_ANSWER = frame("10 02 01 07 20 00 fe 00 00 00 fe 36")  # Write-Object positive answer
READ_MODE_MANUAL = frame("10 02 01 0a 20 00 fe 00 00 00 66 00 07 00 a8")
LADDER_R16_B_MANUAL = frame("10 02 01 09 20 00 fe 00 00 00 66 40 07 e7")  # %R16.B MODCOUR = MANUAL

# operator panel 22:14: %I / %Q byte reads (segments 0xA8 / 0xA9, address = rack/card/byte as hex)
PANEL_I0101_B = frame("10 02 01 09 20 00 fe 00 00 00 66 40 20 00")  # bit 5 = key switch "Freigabe"
PANEL_Q0100_B = frame("10 02 01 09 20 00 fe 00 00 00 66 40 80 60")  # bit 7 = lamp "Achsenstopp quittiert"
PANEL_I0123_B = frame("10 02 01 09 20 00 fe 00 00 00 66 40 c5 a5")  # feed potentiometer, 197


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


def test_ladder_bit_reads():
    # a set bit comes back as 0x80, a clear one as 0x00; the specific byte (bit number) is echoed
    assert unwrap_unite_response(LADDER_R5_0) == [0x66, 0x00, 0x80]
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R5_0), "0") is True
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R5_1), "1") is False


def test_ladder_byte_word_long():
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R16_B), "B") == Mode.AUTO
    # 29 23 on the wire: little-endian, as 938914 §2 says - not the PLC's own MSB-first layout
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R1A_W), "W") == 9001
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R6_L), "L") == 0


def test_ladder_quantity_counts_objects():
    # QUANTITY 2 with specific 65 (word) -> 4 data bytes: %R1A.W = 9001, %R1C.W = 0
    unite = unwrap_unite_response(LADDER_R1A_W_X2)
    assert unite == [0x66, 65, 0x29, 0x23, 0x00, 0x00]


def test_write_mode_frame_as_sent_and_answered():
    # 938914 §4.1.2: 37 cat seg spec addr(LE) n(LE) data(LE); 35000789 §3.5: length 0x10 doubled on the wire
    c = UnitelwayClient()
    query = [0x37, 0x00, 0xB4, 0x00, 0x00, 0x00, 0x01, 0x00, 0x07, 0x00]
    assert c._xway_to_unitelway(c._unite_to_xway(query)) == WRITE_MODE_MANUAL_TX
    assert unwrap_unite_response(WRITE_MODE_ANSWER) == [0xFE]


def test_mode_read_back_after_write():
    unite = unwrap_unite_response(READ_MODE_MANUAL)
    assert unite == [0x66, 0x00, 0x07, 0x00]
    assert Mode(int.from_bytes(unite[2:], "little")) is Mode.MANUAL
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R16_B_MANUAL), "B") == Mode.MANUAL


def test_panel_io_bytes():
    # %I0101.B -> 0x20: the key switch sat in its middle position (%I0101.5, "Freigabe"), so bit n is
    # value bit n, LSB first - the same layout %R5.B = 1 / %R5.0 = True already implied
    assert parse_ladder_read_response(unwrap_unite_response(PANEL_I0101_B), "B") == 0x20
    assert parse_ladder_read_response(unwrap_unite_response(PANEL_Q0100_B), "B") == -128  # .B is signed
    assert parse_ladder_read_response(unwrap_unite_response(PANEL_Q0100_B), "B") & 0xFF == 0x80
    assert parse_ladder_read_response(unwrap_unite_response(PANEL_I0123_B), "B") & 0xFF == 197  # pot: unsigned
