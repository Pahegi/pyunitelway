"""Tests for the UNI-TE answer parsers (layouts per NUM 938914, little-endian)."""

import pytest

from pyunitelway.errors import OperationInProgrammeArea, UnexpectedAdditionalAwnserCode, UnexpectedDataLength, UnexpectedObjectTypeResponse
from pyunitelway.num_constants import Mode
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_ladder_read_response,
    parse_ladder_variable,
    parse_mirror_result,
    parse_shutdown_result,
    parse_stations_managed_by_master,
    parse_unit_fault_history,
    parse_unit_identification,
    parse_unit_status,
    parse_write_result,
)


class TestParseAvailableBytesInRam:
    # 938914 §4.15: H'F5' / H'77' / status / 1 long word

    def test_count_with_dle_byte_inside(self):
        # the 0x10 inside the long word must survive (old double dedup ate the next byte)
        r = [0xF5, 0x77, 0x00, 0xD0, 0x10, 0x01, 0x00]
        assert parse_available_bytes_in_ram(r) == 0x000110D0

    def test_plain_count(self):
        assert parse_available_bytes_in_ram([0xF5, 0x77, 0x00, 0x34, 0x12, 0x00, 0x00]) == 0x1234

    def test_wrong_additional_answer_code_raises(self):
        with pytest.raises(UnexpectedAdditionalAwnserCode):
            parse_available_bytes_in_ram([0xF5, 0x42, 0x00, 0x00, 0x00, 0x00, 0x00])

    def test_operation_in_programme_area_raises(self):
        with pytest.raises(OperationInProgrammeArea):
            parse_available_bytes_in_ram([0xF5, 0x77, 0x02, 0x00, 0x00, 0x00, 0x00])


def test_parse_mirror_result():
    assert parse_mirror_result([0x01, 0x10, 0x04], [0x01, 0x10, 0x04]) is True
    assert parse_mirror_result([0x01, 0x10, 0x05], [0x01, 0x10, 0x04]) is False


def test_parse_write_result():
    assert parse_write_result([0xFE]) is True
    assert parse_write_result([0x66]) is False


class TestParseLadderVariable:
    def test_fields(self):
        assert parse_ladder_variable("%R1A.W") == ("%R", 0xA4, 0x1A, "W", None)
        assert parse_ladder_variable("%R5.1") == ("%R", 0xA4, 0x05, "1", None)
        assert parse_ladder_variable("%V80.L") == ("%V", 0xA0, 0x80, "L", None)
        assert parse_ladder_variable("%R5.3")[3] == "3"

    def test_invalid_symbol_and_size_are_value_errors(self):
        with pytest.raises(ValueError):
            parse_ladder_variable("%Y10.B")
        with pytest.raises(ValueError):
            parse_ladder_variable("%R10.X")
        with pytest.raises(ValueError):
            parse_ladder_variable("%R10")

    def test_bounds(self):
        # 938914 §4.1.3.3: %R last object 0x0F7F, low byte <= 0x7F; %I/%Q low byte <= 0x3F
        with pytest.raises(ValueError):
            parse_ladder_variable("%R1000.B")
        with pytest.raises(ValueError):
            parse_ladder_variable("%R180.B")
        with pytest.raises(ValueError):
            parse_ladder_variable("%I40.B")
        parse_ladder_variable("%I3F.B")
        parse_ladder_variable("%R17F.B")

    def test_index_unsupported(self):
        with pytest.raises(NotImplementedError):
            parse_ladder_variable("%V10.W[2]")


class TestParseLadderReadResponse:
    # 938914 §4.1.1: answer code / echoed specific byte / data; §4.1.3.3: specific = bit n, 64, 65, 66

    def test_bit(self):
        assert parse_ladder_read_response([0x66, 0x01, 0x01], "1") is True
        assert parse_ladder_read_response([0x66, 0x00, 0x00], "0") is False

    def test_byte_is_signed(self):
        assert parse_ladder_read_response([0x66, 64, 0x2A], "B") == 42
        assert parse_ladder_read_response([0x66, 64, 0xFF], "B") == -1

    def test_word_little_endian_signed(self):
        assert parse_ladder_read_response([0x66, 65, 0x29, 0x23], "W") == 9001
        assert parse_ladder_read_response([0x66, 65, 0xFF, 0xFF], "W") == -1  # %R1A.W: no active programme

    def test_long_and_address(self):
        assert parse_ladder_read_response([0x66, 66, 0x00, 0x00, 0x00, 0x80], "L") == -2**31
        assert parse_ladder_read_response([0x66, 66, 0x00, 0x00, 0x00, 0x80], "&") == 0x80000000

    def test_wrong_specific_byte_raises(self):
        with pytest.raises(UnexpectedObjectTypeResponse):
            parse_ladder_read_response([0x66, 64, 0x2A], "W")

    def test_wrong_length_raises(self):
        with pytest.raises(UnexpectedDataLength):
            parse_ladder_read_response([0x66, 65, 0x29], "W")


def test_parse_unit_identification():
    # 938914 §4.3: type / subtype letter / version index in the high half-byte / length byte + ASCII
    r = [0x3F, 101, ord("A"), 0x30, 0x03, ord("N"), ord("U"), ord("M"), 0xAA]
    data = parse_unit_identification(r)
    assert data["product_type_code"] == 101
    assert data["product_type"] == "NUM 1060 Series II"
    assert data["subtype"] == "A"
    assert data["product_version"] == 3
    assert data["text"] == "NUM"  # the length byte bounds the string; the trailing 0xAA is not text


def test_parse_unit_fault_history():
    r = [0xD2, 0x01, 0x00, 0x02, 0x00, 0x03, 0x00, 0x04, 0x01]
    assert parse_unit_fault_history(r) == (1, 2, 3, 0x0104)


def test_parse_shutdown_result():
    # 938928 §10.4.10: F5 / 96 / status (00 done, 1C refused)
    assert parse_shutdown_result([0xF5, 0x96, 0x00]) is True
    assert parse_shutdown_result([0xF5, 0x96, 0x1C]) is False


class TestParseStationsManagedByMaster:
    # 938914 §4.7: H'D3' / number of stations / 1 bit per station, rank = link address.
    # The bit order is not in the manual; MSB-first is what the machine answered
    # (tests/test_hardware_vectors.py).

    def test_three_stations(self):
        assert parse_stations_managed_by_master([0xD3, 0x03, 0xA0]) == (3, [True, False, True])

    def test_more_than_eight_stations_span_bytes(self):
        n, status = parse_stations_managed_by_master([0xD3, 10, 0x80, 0x40])
        assert n == 10
        assert [i for i, connected in enumerate(status) if connected] == [0, 9]

    def test_no_stations(self):
        assert parse_stations_managed_by_master([0xD3, 0x00]) == (0, [])


class TestParseUnitStatus:
    # 938914 §4.4: H'61' / status / mask / 22 bytes segment 153 / panel / NC status / NC mode /
    # machine mode / programme number (word) / PLC status / 16 bytes PLC memory field

    @staticmethod
    def answer(g_functions=0, tool_direction=0, nc_mode=0):
        # field order per 938846 §15.2 (G functions first), sizes per 938914 §4.1.3
        segment_153 = (
            list(g_functions.to_bytes(4, "little"))
            + list((9000 * 10).to_bytes(4, "little"))  # active programme %9000, sent x10
            + [0x0A, 0x00]  # current block 10
            + [0x00, 0x00] + [0x00, 0x00]  # no programme error
            + [0x58, 0x02]  # tool 600
            + list(tool_direction.to_bytes(2, "little"))
            + [0x01, 0x00]  # corrector 1
            + [0x00, 0x00]  # nothing left to execute
        )
        assert len(segment_153) == 22
        # panel %R3.B = cycle in progress / NC status %R5.B = ready + programme active / mode /
        # ERRMACH / PROGCOUR 9000 / PLC running
        return [0x61, 0x00, 0x30] + segment_153 + [0x04, 0x03, nc_mode, 0x00, 0x28, 0x23, 0x02] + [0xFF] * 16

    def test_g90_is_bit_11(self):
        g = parse_unit_status(self.answer(g_functions=1 << 11))["list_of_g_functions"]
        assert g["G90"] == 1
        assert g["G91"] == 0 and g["G18"] == 0

    def test_g38_is_bit_6_and_bit_5_is_unused(self):
        g = parse_unit_status(self.answer(g_functions=1 << 6))["list_of_g_functions"]
        assert g["G38"] == 1 and g["G04"] == 0 and g["G09"] == 0
        g = parse_unit_status(self.answer(g_functions=1 << 5))["list_of_g_functions"]
        assert not any(g.values())

    def test_g29_is_bit_21_and_g93_stays_at_bit_23(self):
        g = parse_unit_status(self.answer(g_functions=(1 << 21) | (1 << 23)))["list_of_g_functions"]
        assert g["G29"] == 1 and g["G93"] == 1 and g["G54"] == 0

    def test_tool_direction_sign(self):
        # high byte = positive, low byte = negative; bit 0 = X, 1 = Y, 2 = Z
        assert parse_unit_status(self.answer(tool_direction=0x0100))["tool_direction"] == {"x": 1, "y": 0, "z": 0}
        assert parse_unit_status(self.answer(tool_direction=0x0001))["tool_direction"] == {"x": -1, "y": 0, "z": 0}
        assert parse_unit_status(self.answer(tool_direction=0x0402))["tool_direction"] == {"x": 0, "y": -1, "z": 1}

    def test_fixed_fields(self):
        s = parse_unit_status(self.answer(nc_mode=2))
        assert s["active_program_number"] == 9000 and s["active_program_index"] == 0
        assert s["active_block_number"] == 10
        assert s["tool_number"] == 600
        assert s["tool_corrector"] == 1
        assert s["operator_panel_status"]["cycle_in_progress"] is True
        assert s["nc_status"]["cnc_ready"] is True and s["nc_status"]["active_program"] is True
        assert s["nc_mode"] == Mode.MDI
        assert s["machine_error_number"] == 0
        assert s["current_program_number"] == 9000
        assert s["plc_status"] == "running"
        assert s["plc_memory_field"] == [0xFF] * 16
