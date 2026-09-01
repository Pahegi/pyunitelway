"""Tests for the UNI-TE answer parsers (layouts per NUM 938914, little-endian)."""

import pytest

from pyunitelway.errors import OperationInProgrammeArea, UnexpectedAdditionalAwnserCode
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_ladder_read_response,
    parse_mirror_result,
    parse_unit_fault_history,
    parse_unit_identification,
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
    r = [0x3F, 101, ord("A"), 3, 0x00, ord("N"), ord("U"), ord("M")]
    data = parse_unit_identification(r)
    assert data["product_type"] == "NUM 1060 Series II"
    assert data["subtype"] == "A"
    assert data["product_version"] == 3
    assert data["text"] == "NUM"


def test_parse_unit_fault_history():
    r = [0xD2, 0x01, 0x00, 0x02, 0x00, 0x03, 0x00, 0x04, 0x01]
    assert parse_unit_fault_history(r) == (1, 2, 3, 0x0104)
