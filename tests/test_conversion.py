"""Frame-level tests for the UNI-TELWAY response unwrapping.

Wire vectors: manual 35000789 §6.2/§6.3 mirror examples and a response
captured from the NUM 1060 (docs/source/debug_levels.rst).
"""

import pytest

from pyunitelway.conversion import unwrap_unite_response, xway_to_unite
from pyunitelway.errors import (
    BadUnitelwayChecksum,
    MalformedUnitelwayResponse,
    RefusedUnitelwayMessage,
    UniteRequestFailed,
)
from pyunitelway.utils import compute_bcc, compute_response_length, delete_dle

DLE, STX, ENQ = 0x10, 0x02, 0x05

# 35000789 §6.3: mirror request with duplicated data DLE
MIRROR_REQUEST = [0x10, 0x02, 0x01, 0x05, 0x00, 0xFA, 0x01, 0x10, 0x10, 0x04, 0x37]
# 35000789 §6.3: the matching mirror answer
MIRROR_ANSWER = [0x10, 0x02, 0x01, 0x04, 0x00, 0xFB, 0x10, 0x10, 0x04, 0x36]
# 35000789 §6.2: mirror answer without DLE in data
MIRROR_ANSWER_PLAIN = [0x10, 0x02, 0x01, 0x03, 0x00, 0xFB, 0x05, 0x16]
# captured NUM 1060 READ_INTERNAL_BIT answer (docs/source/debug_levels.rst)
NUM_RESPONSE = [0x10, 0x02, 0x02, 0x09, 0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x30, 0x00, 0x00, 0x6B]
# master polling sequence that may trail a frame in the receive buffer
TRAILING_POLL = [DLE, ENQ, 0x02]


def wire_frame(addr, npdu):
    """Independent on-wire frame builder per 35000789 §3.5/§3.12."""
    frame = [DLE, STX, addr, len(npdu)]
    if len(npdu) == DLE:
        frame.append(DLE)
    for b in npdu:
        frame.append(b)
        if b == DLE:
            frame.append(DLE)
    frame.append(sum(frame) % 256)
    return frame


def test_wire_frame_matches_manual_vectors():
    assert wire_frame(0x01, [0x00, 0xFA, 0x01, 0x10, 0x04]) == MIRROR_REQUEST
    assert wire_frame(0x01, [0x00, 0xFB, 0x10, 0x04]) == MIRROR_ANSWER
    assert wire_frame(0x01, [0x00, 0xFB, 0x05]) == MIRROR_ANSWER_PLAIN
    assert wire_frame(0x02, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x30, 0x00, 0x00]) == NUM_RESPONSE


def test_compute_bcc_manual_vectors():
    for frame in (MIRROR_REQUEST, MIRROR_ANSWER, MIRROR_ANSWER_PLAIN, NUM_RESPONSE):
        assert compute_bcc(frame[:-1]) == frame[-1]


class TestComputeResponseLength:
    def test_exact_frames(self):
        for frame in (MIRROR_REQUEST, MIRROR_ANSWER, MIRROR_ANSWER_PLAIN, NUM_RESPONSE):
            assert compute_response_length(frame) == len(frame)

    def test_ignores_trailing_bytes(self):
        for frame in (MIRROR_REQUEST, MIRROR_ANSWER, NUM_RESPONSE):
            assert compute_response_length(frame + TRAILING_POLL) == len(frame)

    def test_length_equal_to_dle_is_duplicated(self):
        # 16 data bytes -> <length> = <DLE>, duplicated on the wire
        npdu = [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00] + list(range(0x30, 0x3A))
        assert len(npdu) == DLE
        frame = wire_frame(0x01, npdu)
        assert frame[3] == frame[4] == DLE
        assert compute_response_length(frame + TRAILING_POLL) == len(frame)

    def test_consecutive_dles_in_data(self):
        for run in (2, 3):
            npdu = [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x66] + [DLE] * run
            frame = wire_frame(0x01, npdu)
            assert compute_response_length(frame + TRAILING_POLL) == len(frame)

    def test_bcc_equal_to_dle_not_duplicated(self):
        # NPDU chosen so that BCC = 0x10
        frame = wire_frame(0x02, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x30, 0x00, 0xA5])
        assert frame[-1] == DLE
        assert compute_response_length(frame + TRAILING_POLL) == len(frame)

    def test_incomplete_frame_raises(self):
        with pytest.raises(MalformedUnitelwayResponse):
            compute_response_length(NUM_RESPONSE[:8])

    def test_unduplicated_data_dle_raises(self):
        bad = [0x10, 0x02, 0x01, 0x03, 0x00, 0x10, 0x05, 0x2B]  # lone <DLE> in <data>
        with pytest.raises(MalformedUnitelwayResponse):
            compute_response_length(bad)

    def test_not_a_frame_raises(self):
        with pytest.raises(MalformedUnitelwayResponse):
            compute_response_length([DLE, ENQ, 0x01, 0x00, 0x00, 0x00])


class TestDeleteDle:
    def test_manual_vectors(self):
        assert delete_dle(MIRROR_ANSWER) == [0x10, 0x02, 0x01, 0x04, 0x00, 0xFB, 0x10, 0x04, 0x36]
        assert delete_dle(MIRROR_ANSWER_PLAIN) == MIRROR_ANSWER_PLAIN

    def test_consecutive_dles_in_data(self):
        npdu = [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x66, DLE, DLE]
        frame = wire_frame(0x01, npdu)
        assert delete_dle(frame) == [0x10, 0x02, 0x01, len(npdu)] + npdu + [frame[-1]]


class TestUnwrapUniteResponse:
    def test_captured_num_response(self):
        assert unwrap_unite_response(list(NUM_RESPONSE)) == [0x30, 0x00, 0x00]

    def test_trailing_poll_is_ignored(self):
        assert unwrap_unite_response(NUM_RESPONSE + TRAILING_POLL) == [0x30, 0x00, 0x00]

    def test_simplified_service_format(self):
        # 35000789 §6.3: simplified NPDU (code 0x00)
        assert unwrap_unite_response(list(MIRROR_ANSWER)) == [0xFB, 0x10, 0x04]

    def test_consecutive_dles_in_unite_data(self):
        npdu = [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x66, DLE, DLE, 0x30]
        frame = wire_frame(0x01, npdu)
        assert unwrap_unite_response(frame + TRAILING_POLL) == [0x66, DLE, DLE, 0x30]

    def test_length_equal_to_dle(self):
        npdu = [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00] + list(range(0x30, 0x3A))
        frame = wire_frame(0x01, npdu)
        assert unwrap_unite_response(frame + TRAILING_POLL) == npdu[6:]

    def test_refused_xway_message(self):
        frame = wire_frame(0x01, [0x22, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x30])
        with pytest.raises(RefusedUnitelwayMessage):
            unwrap_unite_response(frame)

    def test_unite_negative_report(self):
        frame = wire_frame(0x01, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0xFD])
        with pytest.raises(UniteRequestFailed):
            unwrap_unite_response(frame)

    def test_bad_checksum_raises_with_both_values(self):
        corrupted = NUM_RESPONSE[:-1] + [0x6C]
        with pytest.raises(BadUnitelwayChecksum) as exc:
            unwrap_unite_response(corrupted)
        assert "0x6B" in str(exc.value) and "0x6C" in str(exc.value)

    def test_unknown_xway_code_raises(self):
        frame = wire_frame(0x01, [0x21, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x30])
        with pytest.raises(MalformedUnitelwayResponse):
            unwrap_unite_response(frame)


def test_xway_to_unite_header_sizes():
    unite = [0x66, 0x01, 0x02]
    assert xway_to_unite([0x20, 0x00, 0xFE, 0x00, 0x00, 0x00] + unite) == unite  # standard
    assert xway_to_unite([0x00] + unite) == unite  # simplified
