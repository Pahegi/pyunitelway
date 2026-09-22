"""Client-level tests that need no socket.

Answer validation of the NUM specific requests (938914 §3.6, §4.15; 938928 §10.4.10) and the
bounded wait for the master's polling window (35000789 §3.6).
"""

import socket

import pytest

from pyunitelway.client import UnitelwayClient
from pyunitelway.constants import (
    ADDITIONAL_ANSWER_CODES,
    MAX_RETRIES,
    READ_MEMORY_FREE,
    RESPONSE_CODES,
    SHUTDOWN,
    SPECIFIC_REQUEST,
    WRITE_MESSAGE,
)
from pyunitelway.errors import (
    NoPollingWindow,
    NoUniteResponse,
    UnexpectedAdditionalAwnserCode,
    UnexpectedUniteResponse,
    UniteRequestFailed,
)
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.utils import check_specific_answer, is_valid_response_code

import test_hardware_vectors as hv
from test_conversion import wire_frame

# 938914 §4.15 layout: F5 / 77 / status 00 / 1 long word (little-endian)
MEMORY_FREE_ANSWER = [0xF5, 0x77, 0x00, 0xD0, 0x10, 0x01, 0x00]


def client_answering(answer, sent=None):
    """A client whose run_unite returns a canned UNI-TE answer and records the query."""
    c = UnitelwayClient()

    def fake_run_unite(address, query, *args, **kwargs):
        if sent is not None:
            sent.append(list(query))
        return list(answer)

    c.run_unite = fake_run_unite
    return c


class TestSpecificRequestCodes:
    def test_f5_answers_with_f5(self):
        assert RESPONSE_CODES[SPECIFIC_REQUEST] == 0xF5
        assert is_valid_response_code(SPECIFIC_REQUEST, 0xF5)

    def test_additional_answer_is_additional_request_plus_0x30(self):
        # 938914 §3.6 table; 938928 §10.4.10 / §10.4.11
        for req, ans in ADDITIONAL_ANSWER_CODES.items():
            assert ans == req + 0x30

    def test_the_three_client_requests_are_distinct(self):
        # they used to be the same integer 0xF5 and collided as dict keys
        assert (READ_MEMORY_FREE, WRITE_MESSAGE, SHUTDOWN) == (0x47, 0x4B, 0x66)


class TestCheckSpecificAnswer:
    def test_accepts_matching_additional_code(self):
        check_specific_answer(MEMORY_FREE_ANSWER, READ_MEMORY_FREE)

    def test_rejects_non_f5_answer_code(self):
        with pytest.raises(UnexpectedUniteResponse):
            check_specific_answer([0xFE], READ_MEMORY_FREE)

    def test_rejects_other_requests_additional_code(self):
        with pytest.raises(UnexpectedAdditionalAwnserCode):
            check_specific_answer([0xF5, 0x96, 0x00], READ_MEMORY_FREE)

    def test_additional_fd_is_the_negative_report(self):
        # 938914 §4.17: F5 / FD = request unknown
        with pytest.raises(UniteRequestFailed):
            check_specific_answer([0xF5, 0xFD], WRITE_MESSAGE)

    def test_also_accept_covers_the_write_message_contradiction(self):
        # §3.6 table says H'7B', the §4.17 body says H'FE'
        check_specific_answer([0xF5, 0x7B], WRITE_MESSAGE, also_accept=(0xFE,))
        check_specific_answer([0xF5, 0xFE], WRITE_MESSAGE, also_accept=(0xFE,))


class TestGetAvailableBytesInRam:
    def test_sends_f5_00_47_and_returns_the_count(self):
        sent = []
        c = client_answering(MEMORY_FREE_ANSWER, sent)
        assert c.get_available_bytes_in_ram() == 0x000110D0
        assert sent == [[0xF5, 0x00, 0x47]]

    def test_write_answer_code_is_rejected(self):
        with pytest.raises(UnexpectedUniteResponse):
            client_answering([0xFE]).get_available_bytes_in_ram()


class TestShutdown:
    def test_sends_f5_00_66_00_and_reads_the_status(self):
        sent = []
        c = client_answering([0xF5, 0x96, 0x00], sent)
        assert c.shutdown() is True
        assert sent == [[0xF5, 0x00, 0x66, 0x00]]

    def test_refused_status(self):
        assert client_answering([0xF5, 0x96, 0x1C]).shutdown() is False


class FakeSocket:
    """``stale`` is what is already buffered (drained non-blocking); ``live`` arrives afterwards."""

    def __init__(self, live=b"", stale=b"", closed=False):
        self.live = bytearray(live)
        self.stale = bytearray(stale)
        self.closed = closed
        self.sent = bytearray()
        self.blocking = True
        self.timeout = "untouched"

    def settimeout(self, t):
        self.timeout = t

    def setblocking(self, flag):
        self.blocking = flag

    def recv(self, n):
        if not self.blocking:
            if not self.stale:
                raise BlockingIOError()
            out = bytes(self.stale[:n])
            del self.stale[:n]
            return out
        if not self.live:
            if self.closed:
                return b""
            raise socket.timeout()
        out = bytes(self.live[:n])
        del self.live[:n]
        return out

    def sendall(self, data):
        self.sent += data


POLL_01, POLL_02 = b"\x10\x05\x01", b"\x10\x05\x02"


class TestIsMyTurnToTalk:
    def test_waits_for_a_fresh_poll(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket(live=POLL_02 + POLL_01, stale=POLL_01 * 5)
        assert c.is_my_turn_to_talk(0x01, timeout=1) is True
        assert c.socket.stale == b""  # buffered polls were discarded, not used
        assert c.socket.live == b""
        assert c.socket.timeout is None  # blocking mode restored afterwards

    def test_raises_when_only_other_addresses_are_polled(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket(live=POLL_02 * 3)
        with pytest.raises(NoPollingWindow):
            c.is_my_turn_to_talk(0x01, timeout=1)
        assert c.socket.timeout is None

    def test_raises_on_a_silent_link(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket()
        with pytest.raises(NoPollingWindow):
            c.is_my_turn_to_talk(0x01, timeout=1)

    def test_closed_connection_is_not_a_polling_problem(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket(closed=True)
        with pytest.raises(ConnectionError):
            c.is_my_turn_to_talk(0x01, timeout=1)


class TestReadFrame:
    # 35000789 §3.5/§3.12: <DLE><STX><addr><len>[<DLE>]<data with DLEs doubled><BCC>

    @staticmethod
    def read(wire):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket(live=wire)
        return c._read_frame(1)

    def test_skips_polls_and_ack(self):
        assert self.read(POLL_01 + b"\x06" + POLL_01 + bytes(hv.MIRROR)) == hv.MIRROR

    def test_dle_enq_inside_data_is_kept(self):
        # the old loop deleted every <DLE><ENQ> pair it saw, even inside a frame (todo.md B3)
        frame = wire_frame(0x01, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0xFB, 0x10, 0x05])
        assert self.read(bytes(frame)) == frame
        assert unwrap_unite_response(frame) == [0xFB, 0x10, 0x05]

    def test_length_equal_to_dle_is_doubled(self):
        frame = wire_frame(0x01, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00] + list(range(10)))  # 16-byte NPDU
        assert frame[3:5] == [0x10, 0x10]
        assert self.read(bytes(frame)) == frame
        assert unwrap_unite_response(frame) == list(range(10))

    def test_other_stations_frame_is_skipped(self):
        other = wire_frame(0x02, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0xFB])
        assert self.read(bytes(other) + bytes(hv.MIRROR)) == hv.MIRROR

    def test_nak_and_timeout_give_none(self):
        assert self.read(b"\x15") is None
        assert self.read(POLL_01 * 4) is None

    def test_captured_frames_between_polls(self):
        for frame in (hv.STATUS, hv.IDENTIFICATION, hv.LADDER_R1A_W_X2):
            assert self.read(POLL_01 + bytes(frame) + POLL_01) == frame


class TestRetries:
    def test_gives_up_after_max_retries(self):
        c = UnitelwayClient(VPN_Mode=True)  # no polling window needed
        c.socket = FakeSocket()
        with pytest.raises(NoUniteResponse):
            c._unite_query_until_response(0x01, [0xFA, 0x00], timeout=0.01, text="MIRROR")
        assert c.socket.sent.count(b"\x10\x02\x01") == MAX_RETRIES


class TestReadLadder:
    def test_sends_specific_byte_for_the_size_and_decodes(self):
        sent = []
        c = client_answering([0x66, 65, 0x29, 0x23], sent)
        assert c.read_ladder("%R1A.W") == 9001
        # 36 / cat / segment %R / specific 65 = word / address 0x001A / quantity 1
        assert sent == [[0x36, 0x00, 0xA4, 65, 0x1A, 0x00, 0x01, 0x00]]

    def test_bit_read_sends_the_bit_number(self):
        sent = []
        c = client_answering([0x66, 0x01, 0x01], sent)
        assert c.read_ladder("%R5.1") is True
        assert sent[0][3] == 1

    def test_write_ladder_raises_before_sending(self):
        sent = []
        c = client_answering([0xFE], sent)
        with pytest.raises(NotImplementedError):
            c.write_ladder("%W3.2", 1)
        assert sent == []
