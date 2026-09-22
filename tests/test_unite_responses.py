"""Tests for the UNI-TE answer parsers (layouts per NUM 938914, little-endian)."""

import pytest

from pyunitelway.errors import OperationInProgrammeArea, UnexpectedAdditionalAwnserCode
from pyunitelway.num_constants import Mode
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_ladder_read_response,
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


class TestParseLadderReadResponse:
    # pins the current contract: [answer code, object type, object bytes...]

    def test_bit_set(self):
        assert parse_ladder_read_response([0x66, 0xA0, 0x00, 0b00000010], "1") == 1

    def test_bit_clear(self):
        assert parse_ladder_read_response([0x66, 0xA0, 0x00, 0b00000010], "0") == 0

    def test_word(self):
        assert parse_ladder_read_response([0x66, 0xA0, 0x01, 0x34, 0x12], "W") == 0x1234


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
        segment_153 = (
            [0x28, 0x23, 0x00, 0x00]  # active programme 9000
            + [0x0A, 0x00]  # active block 10
            + [0x00, 0x00] + [0x00, 0x00]  # no programme error
            + [0x58, 0x02]  # tool 600
            + list(tool_direction.to_bytes(2, "little"))
            + [0x01, 0x00]  # corrector 1
            + list(g_functions.to_bytes(4, "little"))
            + [0x00, 0x00]  # nothing left to execute
        )
        assert len(segment_153) == 22
        return [0x61, 0x00, 0x30] + segment_153 + [0x00, 0x01, nc_mode, 0x00, 0x28, 0x23, 0x02] + [0xFF] * 16

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
        assert s["tool_number"] == 600
        assert s["nc_mode"] == Mode.MDI
        assert s["current_program_number"] == 9000
        assert s["plc_status"] == "running"
