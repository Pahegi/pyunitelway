"""Answers captured from the real NUM 1060 Series II UC SII (Makerspace Darmstadt).

Captured 2026-09-22 with ``example/test.py`` at debug=2 (``example/logs/test-20260922-202236.log``):
USR-TCP232-306 at 10.1.70.202:8234, this client at link address 0x01 (the only address the master
polls), NC idle in AUTO, programme %9001 selected, PLC running. The mode round-trip vectors are from
``example/logs/test-20260922-220419.log`` (write MANUAL, read back, write AUTO); the panel bytes are
from ``example/logs/panel-20260922-221429.log`` (``poetry run panel``); the other-segment reads
from ``example/logs/test-20260922-222640.log`` (``poetry run test --read-only``). Each vector is the complete
UNI-TELWAY frame as received, so these pin the whole unwrap + parse path against what the machine
actually sends - not against the manual.
"""

from pyunitelway.client import UnitelwayClient
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.num_constants import Mode, Program
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_directory,
    parse_upload_segment,
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

# other segments 22:26: %V %W %M %S, word/long over the panel bytes, QUANTITY on bytes, an empty slot
LADDER_W4_6 = frame("10 02 01 09 20 00 fe 00 00 00 66 06 00 a6")  # DPAUS = key switch %I0101.3 = 0
LADDER_W202_B = frame("10 02 01 09 20 00 fe 00 00 00 66 40 c5 a5")  # AVPOTI2 = %I0123.B
LADDER_M4004_W = frame("10 02 01 0a 20 00 fe 00 00 00 66 41 40 00 22")  # 64
LADDER_S0_W = frame("10 02 01 0a 20 00 fe 00 00 00 66 41 00 00 e2")  # common word 0
LADDER_V80_L = frame("10 02 01 0c 20 00 fe 00 00 00 66 42 00 20 00 11 16")  # %V80.0 %V80.4 %V82.5 set
LADDER_I0100_L = frame("10 02 01 0c 20 00 fe 00 00 00 66 42 00 00 20 00 05")  # %I0101 = 0x20
LADDER_Q0100_W = frame("10 02 01 0a 20 00 fe 00 00 00 66 41 01 00 e3")  # %Q0101 = 0x01
LADDER_I0600_B = frame("10 02 01 09 20 00 fe 00 00 00 66 40 00 e0")  # slot 6 has no card: 0, no error
LADDER_I0100_B_X5 = frame("10 02 01 0d 20 00 fe 00 00 00 66 40 00 20 00 00 00 04")  # QUANTITY 5 bytes

# first ladder write 2026-09-23 15:20 (example/logs/write-checks-20260923-152044.log): MSG2 %W16.B 0 -> 1 -> 0
WRITE_MSG2_TX = frame("10 02 01 0f 20 00 fe 00 00 00 37 00 a5 40 16 00 01 00 01 74")
WRITE_MSG2_ANSWER = frame("10 02 01 07 20 00 fe 00 00 00 fe 36")
WRITE_MESSAGE_TX = frame("10 02 01 2b 20 00 fe 00 00 00 f5 00 4b 00 01 50 59 55 4e 49 54 45 4c 57 41 59 20 54 45 53 54 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 20 68")
WRITE_MESSAGE_ANSWER = frame("10 02 01 08 20 00 fe 00 00 00 f5 fe 2c")  # F5 FE: the UC SII implements §4.17

# bit and word writes 2026-09-23 15:23 on unnamed %V7800/%V7801 (example/logs/write-experiments-20260923-152306.log)
LADDER_V7800_B_52 = frame("10 02 01 09 20 00 fe 00 00 00 66 40 52 32")  # pattern written, bit 3 clear
LADDER_V7800_B_5A = frame("10 02 01 09 20 00 fe 00 00 00 66 40 5a 3a")  # after bit 3 <- 0x01, and after <- 0x80
LADDER_V7800_B_12 = frame("10 02 01 09 20 00 fe 00 00 00 66 40 12 f2")  # after %V7800.W <- 0x1234, count 1
LADDER_V7801_B_34 = frame("10 02 01 09 20 00 fe 00 00 00 66 40 34 14")
LADDER_V7800_W_1234 = frame("10 02 01 0a 20 00 fe 00 00 00 66 41 34 12 28")

# mode round-trip 2026-09-23 15:26 from HOMING (example/logs/test-20260923-152646.log)
READ_MODE_HOMING = frame("10 02 01 0a 20 00 fe 00 00 00 66 00 08 00 a9")
LADDER_R16_B_HOMING = frame("10 02 01 09 20 00 fe 00 00 00 66 40 08 e8")


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


def test_other_segments_answer():
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_W4_6), "6") is False
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_W202_B), "B") & 0xFF == 0xC5  # = %I0123.B
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_M4004_W), "W") == 64
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_S0_W), "W") == 0
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_I0600_B), "B") == 0


def test_word_and_long_take_the_first_byte_as_msb():
    # 938846 §4: %I0100.L = %I0100 (MSB) .. %I0103 (LSB); the NC sends that value little-endian (938914 §2)
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_I0100_L), "L") == 0x00200000
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_Q0100_W), "W") == 0x0001
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_V80_L), "L") == 0x11002000


def test_quantity_counts_bytes_too():
    assert unwrap_unite_response(LADDER_I0100_B_X5) == [0x66, 64, 0x00, 0x20, 0x00, 0x00, 0x00]


def test_first_ladder_write_and_supervisor_message():
    c = UnitelwayClient(writable={"%W16.B"})
    assert c._xway_to_unitelway(c._unite_to_xway([0x37, 0x00, 0xA5, 64, 0x16, 0x00, 0x01, 0x00, 0x01])) == WRITE_MSG2_TX
    assert unwrap_unite_response(WRITE_MSG2_ANSWER) == [0xFE]
    query = [0xF5, 0x00, 0x4B, 0x00, 1] + [ord(ch) for ch in "PYUNITELWAY TEST".ljust(32)]
    assert c._xway_to_unitelway(c._unite_to_xway(query)) == WRITE_MESSAGE_TX
    assert unwrap_unite_response(WRITE_MESSAGE_ANSWER) == [0xF5, 0xFE]


def test_bit_and_word_writes_settled():
    # any non-zero data byte sets a bit (0x01 and 0x80 both gave 0x5A), 0x00 clears it
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_V7800_B_52), "B") == 0x52
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_V7800_B_5A), "B") == 0x5A
    # a word write with count 1 wrote both bytes, first byte MSB (938846 §4)
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_V7800_B_12), "B") == 0x12
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_V7801_B_34), "B") == 0x34
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_V7800_W_1234), "W") == 0x1234


def test_mode_homing_read_back():
    unite = unwrap_unite_response(READ_MODE_HOMING)
    assert Mode(int.from_bytes(unite[2:], "little")) is Mode.HOMING
    assert parse_ladder_read_response(unwrap_unite_response(LADDER_R16_B_HOMING), "B") == Mode.HOMING

# 2026-09-26 18:10, ``poetry run backup --directory`` (``example/logs/backup-20260926-181034.log``): the NC memory
# directory (938914 §4.16), 48 programmes in four answers, no resend. Full pages are 123 UNI-TE bytes (length 0x81)
# and carry doubled 0x10 data bytes.
DIRECTORY_OPEN_TX = frame("10 02 01 0d 20 00 fe 00 00 00 f5 00 48 00 00 00 00 7b")
DIRECTORY_NEXT_TX = frame("10 02 01 09 20 00 fe 00 00 00 f5 00 49 78")
DIRECTORY_PAGE1 = frame(
    "10 02 01 81 20 00 fe 00 00 00 f5 78 00 32 00 00 00 e4 17 00 00 3c 00 00 00 52 06 00 00 50 00 00 00 9a 02 00 00 "
    "5a 00 00 00 4a 11 00 00 64 00 00 00 54 04 00 00 6e 00 00 00 6c 05 00 00 78 00 00 00 0c 03 00 00 8c 00 00 00 "
    "4a 09 00 00 2c 01 00 00 58 01 00 00 36 01 00 00 10 10 0c 00 00 40 01 00 00 00 1a 00 00 4a 01 00 00 c6 14 00 00 "
    "54 01 00 00 62 10 10 00 00 5e 01 00 00 b8 00 00 00 2a 03 00 00 8a 03 00 00 93"
)
DIRECTORY_PAGE2 = frame(
    "10 02 01 81 20 00 fe 00 00 00 f5 79 00 3e 03 00 00 0c 11 00 00 52 03 00 00 32 0d 00 00 5c 03 00 00 88 11 00 00 "
    "7a 03 00 00 1c 10 10 00 00 8e 03 00 00 d8 12 00 00 98 03 00 00 2c 09 00 00 a2 03 00 00 f8 19 00 00 b6 03 00 00 "
    "90 08 00 00 ca 03 00 00 f0 00 00 00 d4 03 00 00 3c 0c 00 00 e8 03 00 00 26 01 00 00 f2 03 00 00 90 00 00 00 "
    "56 04 00 00 b6 02 00 00 84 17 00 00 4a 00 00 00 8e 17 00 00 e2 01 00 00 07"
)
DIRECTORY_PAGE3 = frame(
    "10 02 01 81 20 00 fe 00 00 00 f5 79 00 ca 17 00 00 1c 00 00 00 90 5f 01 00 62 04 00 00 9a 5f 01 00 b6 20 00 00 "
    "a4 5f 01 00 62 10 10 00 00 c2 82 01 00 ea 00 00 00 cc 82 01 00 14 09 00 00 81 83 01 00 1c 00 00 00 d8 85 01 00 "
    "d0 0e 00 00 e2 85 01 00 20 02 00 00 ec 85 01 00 e6 0e 00 00 f6 85 01 00 16 03 00 00 3c 86 01 00 16 07 00 00 "
    "5a 86 01 00 f8 01 00 00 64 86 01 00 66 05 00 00 6e 86 01 00 8c 10 10 00 00 f7"
)
DIRECTORY_PAGE4 = frame("10 02 01 21 20 00 fe 00 00 00 f5 79 0f 78 86 01 00 3c 01 00 00 82 86 01 00 e2 10 10 00 00 96 86 01 00 e0 1f 00 00 32")


def test_directory_of_the_nc_ram():
    c = UnitelwayClient()
    assert c._xway_to_unitelway(c._unite_to_xway([0xF5, 0x00, 0x48, 0, 0, 0, 0])) == DIRECTORY_OPEN_TX
    assert c._xway_to_unitelway(c._unite_to_xway([0xF5, 0x00, 0x49])) == DIRECTORY_NEXT_TX
    pages = [parse_directory(unwrap_unite_response(f), "DIRECTORY") for f in
             (DIRECTORY_PAGE1, DIRECTORY_PAGE2, DIRECTORY_PAGE3, DIRECTORY_PAGE4)]
    assert [status for status, _ in pages] == [0, 0, 0, 15]  # the NC closed the read itself
    programs = [p for _, page in pages for p in page]
    assert len(programs) == 48
    assert programs[0] == Program(5, 0, 6116)
    assert Program(31, 0, 3088) in programs  # its size 0x0C10 arrives as 10 10 0c
    assert Program(101, 0, 144) in programs
    assert Program(9920, 1, 28) in programs  # the only programme in axis group 1
    assert programs[-1] == Program(9999, 0, 8160)
    assert programs == sorted(programs, key=lambda p: (p.number, p.group))

# 2026-09-26 18:13, ``poetry run backup --program 101`` (``example/logs/backup-20260926-181337.log``): part programme
# %101.0 uploaded in one segment (938914 §4.13), byte-identical to the 2023 NCDat backup. The open request is a
# 16-byte NPDU, so its length byte 0x10 goes out doubled; status 15 on the segment = the NC closed the file itself,
# and the close afterwards answers 4 "already closed".
UPLOAD_OPEN_TX = frame("10 02 01 10 10 20 00 fe 00 00 00 3d 00 f2 03 00 12 00 00 00 00 95")
UPLOAD_OPEN_ANSWER = frame("10 02 01 08 20 00 fe 00 00 00 6d 00 a6")
UPLOAD_SEG1_TX = frame("10 02 01 0a 20 00 fe 00 00 00 3e 00 01 00 7a")
UPLOAD_SEG1 = frame(
    "10 02 01 6a 20 00 fe 00 00 00 6e 0f 01 00 5e 00 4e 31 30 4c 31 36 30 3d 32 35 30 30 4c 31 36 31 3d 35 35 30 4c "
    "31 36 32 3d 31 30 0d 0a 4e 32 30 47 58 32 36 30 30 0d 0a 47 34 46 38 0d 0a 4e 33 30 47 31 47 39 31 58 2d 31 30 "
    "30 0d 0a 4e 34 30 47 34 46 38 0d 0a 4e 35 30 47 37 37 4e 33 30 4e 34 30 53 32 30 0d 0a 4e 36 30 4d 32 0d 0a 4a"
)
UPLOAD_CLOSE_TX = frame("10 02 01 08 20 00 fe 00 00 00 3f 00 78")
UPLOAD_CLOSE_ANSWER = frame("10 02 01 08 20 00 fe 00 00 00 6f 04 ac")
PROGRAM_101 = (b"N10L160=2500L161=550L162=10\r\nN20GX2600\r\nG4F8\r\nN30G1G91X-100\r\nN40G4F8\r\n"
               b"N50G77N30N40S20\r\nN60M2\r\n")


def test_part_programme_upload():
    c = UnitelwayClient()
    assert c._xway_to_unitelway(c._unite_to_xway([0x3D, 0x00, 0xF2, 0x03, 0x00, 0x12, 0, 0, 0, 0])) == UPLOAD_OPEN_TX
    assert c._xway_to_unitelway(c._unite_to_xway([0x3E, 0x00, 0x01, 0x00])) == UPLOAD_SEG1_TX
    assert c._xway_to_unitelway(c._unite_to_xway([0x3F, 0x00])) == UPLOAD_CLOSE_TX
    assert unwrap_unite_response(UPLOAD_OPEN_ANSWER) == [0x6D, 0x00]
    assert parse_upload_segment(unwrap_unite_response(UPLOAD_SEG1), 1) == (15, PROGRAM_101)
    assert len(PROGRAM_101) == 94  # the directory said 144: NC block overhead, not text
    assert unwrap_unite_response(UPLOAD_CLOSE_ANSWER) == [0x6F, 0x04]

# 2026-09-26 18:29, ``poetry run backup --program 35`` (``example/logs/backup-20260926-182958.log``): %35.0 in two
# segments, 122 + 12 bytes, byte-identical to the 2023 backup. The first answer has the maximum length byte 134
# (35000789 §4.2: 128-byte NPDU + 6) and carries status 0 "data remaining"; the second carries 15.
UPLOAD_35_SEG1 = frame(
    "10 02 01 86 20 00 fe 00 00 00 6e 00 01 00 7a 00 28 20 4b 72 65 69 73 74 61 73 63 68 65 20 66 72 61 65 73 65 6e "
    "20 29 0d 0a 28 30 30 33 35 20 20 56 31 2e 32 20 20 33 31 2e 30 31 2e 39 36 20 29 0d 0a 50 55 53 48 20 4c 31 32 "
    "30 2d 4c 31 32 32 0d 0a 20 20 20 20 20 4c 31 32 30 3d 4c 31 32 32 20 4c 31 32 31 3d 4c 31 32 32 20 4c 31 32 32 "
    "3d 4c 31 32 32 2f 32 0d 0a 20 20 20 20 20 47 37 37 20 48 33 34 0d 0a 50 55 4c 4c 37"
)
UPLOAD_35_SEG2_TX = frame("10 02 01 0a 20 00 fe 00 00 00 3e 00 02 00 7b")
UPLOAD_35_SEG2 = frame("10 02 01 18 20 00 fe 00 00 00 6e 0f 02 00 0c 00 20 4c 31 32 30 2d 4c 31 32 32 0d 0a f8")


def test_two_segment_upload_at_the_maximum_frame_size():
    assert UPLOAD_35_SEG1[3] == 134 and len(UPLOAD_35_SEG1) == 4 + 134 + 1  # length byte = 6 X-WAY + 128 UNI-TE
    status, part1 = parse_upload_segment(unwrap_unite_response(UPLOAD_35_SEG1), 1)
    assert (status, len(part1)) == (0, 122)
    c = UnitelwayClient()
    assert c._xway_to_unitelway(c._unite_to_xway([0x3E, 0x00, 0x02, 0x00])) == UPLOAD_35_SEG2_TX
    status, part2 = parse_upload_segment(unwrap_unite_response(UPLOAD_35_SEG2), 2)
    assert (status, part2) == (15, b" L120-L122\r\n")
    assert (part1 + part2).startswith(b"( Kreistasche fraesen )\r\n(0035  V1.2  31.01.96 )\r\n")
    assert len(part1 + part2) == 134

# 2026-09-26 18:40, ``poetry run backup --parameters`` (``example/logs/backup-20260926-184000.log``): machine parameters
# (file type H'05') in 88 segments, no resend, 12 s. For this type the NC sends 120 data bytes per segment, not the
# 122 of §4.13.2 (part programmes did use 122); the last segment carries status 15, so the NC auto-closes this type
# too and the close answers 4. 10521 bytes, the .xpa text of the IPC's UPLF 5 0 0; two parameters differ from 2007.
PARAMS_OPEN_TX = frame("10 02 01 10 10 20 00 fe 00 00 00 3d 00 00 00 00 05 00 00 00 00 93")
PARAMS_SEG1 = frame(
    "10 02 01 84 20 00 fe 00 00 00 6e 00 01 00 78 00 25 31 32 32 30 35 30 30 30 3b 30 39 0d 0a 50 30 4e 30 3a 74 36 "
    "6e 31 3b 30 39 0d 0a 23 30 30 30 30 30 30 32 37 3b 30 39 0d 0a 50 31 4e 30 3a 74 36 6e 32 3b 30 39 0d 0a 23 30 "
    "30 30 30 30 30 30 30 20 30 30 30 30 30 30 30 30 3b 31 32 0d 0a 50 32 4e 30 3a 74 36 6e 31 3b 30 39 0d 0a 23 30 "
    "30 30 30 30 30 32 37 3b 30 39 0d 0a 50 33 4e 30 3a 74 36 6e 31 3b 30 39 0d b9"
)
PARAMS_SEG88_TX = frame("10 02 01 0a 20 00 fe 00 00 00 3e 00 58 00 d1")
PARAMS_SEG88 = frame(
    "10 02 01 5d 20 00 fe 00 00 00 6e 0f 58 00 51 00 50 31 31 33 4e 30 3a 74 39 6e 32 3b 30 42 0d 0a 23 30 2e 30 30 "
    "30 30 30 30 45 2b 30 30 20 30 2e 30 30 30 30 30 30 45 2b 30 30 3b 31 41 0d 0a 50 31 31 34 4e 30 3a 74 35 6e 33 "
    "3b 30 42 0d 0a 23 31 30 20 30 20 30 3b 30 37 0d 0a 13 3b 30 31 0d 0a 54"
)


def test_machine_parameter_upload():
    c = UnitelwayClient()
    assert c._xway_to_unitelway(c._unite_to_xway([0x3D, 0x00, 0, 0, 0, 0x05, 0, 0, 0, 0])) == PARAMS_OPEN_TX
    status, first = parse_upload_segment(unwrap_unite_response(PARAMS_SEG1), 1)
    assert (status, len(first)) == (0, 120)
    assert first.startswith(b"%12205000;09\r\nP0N0:t6n1;09\r\n#00000027;09\r\n")
    assert c._xway_to_unitelway(c._unite_to_xway([0x3E, 0x00, 88, 0x00])) == PARAMS_SEG88_TX
    status, last = parse_upload_segment(unwrap_unite_response(PARAMS_SEG88), 88)
    assert (status, len(last)) == (15, 81)
    assert last.endswith(b"P114N0:t5n3;0B\r\n#10 0 0;07\r\n\x13;01\r\n")  # P84 timeout line is earlier; DC3 ends the file
    assert 87 * 120 + 81 == 10521

# 2026-09-26 18:44-18:47, ``poetry run backup --archive --timeout 10`` (``example/logs/backup-20260926-184449.log``):
# all ladder and C modules (file type H'07', module type 16) in 912 segments of 122 bytes + 89, no resend, 111231 bytes.
# The file id carries a 0x10 byte and so do the segment numbers 16/272/528/784, doubled on the wire both ways.
# Status 15 on the last segment, but the close answered 0, not 4: the NC does NOT auto-close this file type.
ARCHIVE_OPEN_TX = frame("10 02 01 10 10 20 00 fe 00 00 00 3d 00 00 00 10 10 07 00 00 00 00 b5")
ARCHIVE_SEG16_TX = frame("10 02 01 0a 20 00 fe 00 00 00 3e 00 10 10 00 99")
ARCHIVE_SEG16 = frame(
    "10 02 01 86 20 00 fe 00 00 00 6e 00 10 10 00 7a 00 fb 81 70 00 00 29 d8 24 48 2f 08 4e bb 81 70 00 00 25 2c 4f "
    "ef 00 0c 2f 0a 4e bb 81 70 00 00 23 bc 58 8f b0 bb 81 70 00 00 29 b0 66 04 42 43 60 18 36 3c ff ff 60 12 48 78 "
    "00 0a 4e bb 81 70 00 00 21 6a 58 8f 53 82 6e 94 30 03 4c ee 04 0c ff 74 4e 5e 4e 75 4e 56 ff f8 48 e7 30 3c 24 "
    "2e 00 08 26 2e 00 0c 24 6e 00 14 26 6e 00 10 10 49 ee ff f8 2a 4c 52 8d 4a b3 2c 00 66 23"
)
ARCHIVE_SEG912_TX = frame("10 02 01 0a 20 00 fe 00 00 00 3e 00 90 03 0c")
ARCHIVE_SEG912 = frame(
    "10 02 01 65 20 00 fe 00 00 00 6e 0f 90 03 59 00 eb 00 00 07 c0 e2 0f 64 06 08 ab 00 00 07 c0 e2 0f 64 06 08 eb "
    "00 01 07 c0 e2 0f 64 06 08 ab 00 01 07 c0 e2 0f 55 c0 ef eb 01 81 00 00 4e 75 7e f6 00 00 80 69 00 00 00 00 00 "
    "00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 9c 3c cc"
)
ARCHIVE_CLOSE_ANSWER = frame("10 02 01 08 20 00 fe 00 00 00 6f 00 a8")


def test_plc_archive_upload_with_dle_in_file_id_and_segment_number():
    c = UnitelwayClient()
    assert c._xway_to_unitelway(c._unite_to_xway([0x3D, 0x00, 0, 0, 0x10, 0x07, 0, 0, 0, 0])) == ARCHIVE_OPEN_TX
    assert c._xway_to_unitelway(c._unite_to_xway([0x3E, 0x00, 16, 0x00])) == ARCHIVE_SEG16_TX
    status, data = parse_upload_segment(unwrap_unite_response(ARCHIVE_SEG16), 16)
    assert (status, len(data)) == (0, 122)
    assert b"\x26\x6e\x00\x10\x49" in data  # the data byte 0x10 came doubled (10 10) and was folded back
    assert c._xway_to_unitelway(c._unite_to_xway([0x3E, 0x00, 0x90, 0x03])) == ARCHIVE_SEG912_TX
    status, data = parse_upload_segment(unwrap_unite_response(ARCHIVE_SEG912), 912)
    assert (status, len(data)) == (15, 89)
    assert 911 * 122 + 89 == 111231
    assert unwrap_unite_response(ARCHIVE_CLOSE_ANSWER) == [0x6F, 0x00]  # a real close, unlike the other types
