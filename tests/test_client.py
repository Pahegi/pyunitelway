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
    UnexpectedDataLength,
    UnexpectedUniteResponse,
    UniteRequestFailed,
    WriteNotAllowed,
)
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.constants import ALL_LADDER_SEGMENTS
from pyunitelway.num_constants import ALL_NC_OBJECTS, Mode, Object
from pyunitelway.utils import check_specific_answer, encode_ladder_value, is_valid_response_code

import test_hardware_vectors as hv
from test_conversion import wire_frame

# 938914 §4.15 layout: F5 / 77 / status 00 / 1 long word (little-endian)
MEMORY_FREE_ANSWER = [0xF5, 0x77, 0x00, 0xD0, 0x10, 0x01, 0x00]


def client_answering(answer, sent=None, **kwargs):
    """A client whose run_unite returns a canned UNI-TE answer and records the query."""
    c = UnitelwayClient(**kwargs)

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

    def test_unsigned_read(self):
        c = client_answering([0x66, 64, 0xC5])
        assert c.read_ladder("%I0123.B") == -59  # 938846 §4 convention
        assert c.read_ladder("%I0123.B", signed=False) == 197  # the feed-override pot


class TestWriteLadder:
    def test_default_client_writes_nothing(self):
        sent = []
        c = client_answering([0xFE], sent)
        for var in ("%V7800.B", "%W16.B", "%Q0100.B", "%M4004.W", "%S0.W"):
            with pytest.raises(WriteNotAllowed):
                c.write_ladder(var, 1)
        assert sent == []

    def test_unlocked_segment(self):
        sent = []
        c = UnitelwayClient(writable={"%V"})
        c.run_unite = lambda a, q, *args, **kw: sent.append(list(q)) or [0xFE]
        assert c.write_ladder("%V7800.B", 0x5A) is True
        assert sent == [[0x37, 0x00, 0xA0, 64, 0x00, 0x78, 0x01, 0x00, 0x5A]]
        with pytest.raises(WriteNotAllowed):
            c.write_ladder("%W16.B", 1)

    def test_unlocked_exact_variable_only(self):
        sent = []
        c = UnitelwayClient(writable={"%W0016.B"})  # spelled differently on purpose
        c.run_unite = lambda a, q, *args, **kw: sent.append(list(q)) or [0xFE]
        assert c.write_ladder("%W16.B", 1) is True  # MSG2
        assert sent == [[0x37, 0x00, 0xA5, 64, 0x16, 0x00, 0x01, 0x00, 0x01]]
        for var in ("%W3.2", "%W16.W", "%W17.B"):  # NC start, another size, the neighbour
            with pytest.raises(WriteNotAllowed):
                c.write_ladder(var, 1)
        assert len(sent) == 1

    def test_all_segments_and_bad_entries(self):
        c = UnitelwayClient(writable=ALL_LADDER_SEGMENTS)
        c.run_unite = lambda a, q, *args, **kw: [0xFE]
        assert c.write_ladder("%W3.B", 0) is True
        with pytest.raises(ValueError):
            UnitelwayClient(writable={"%X1.B"})

    def test_word_and_long_encoding_is_the_read_layout_in_reverse(self):
        # %R1A.W = 9001 came as 29 23; %I0100.L = 0x00200000 came as 00 00 20 00 (hardware vectors)
        assert encode_ladder_value("W", 9001) == [0x29, 0x23]
        assert encode_ladder_value("L", 0x00200000) == [0x00, 0x00, 0x20, 0x00]
        assert encode_ladder_value("W", -1) == [0xFF, 0xFF]

    def test_word_long_and_bit_writes(self):
        # verified 2026-09-23 on %V7800: count 1 writes the whole word; any non-zero data byte sets a bit
        sent = []
        c = client_answering([0xFE], sent, writable={"%V"})
        c.write_ladder("%V7800.W", 0x1234)
        c.write_ladder("%V7800.3", True)
        c.write_ladder("%V7800.3", False)
        assert sent[0] == [0x37, 0x00, 0xA0, 65, 0x00, 0x78, 0x01, 0x00, 0x34, 0x12]
        assert sent[1] == [0x37, 0x00, 0xA0, 3, 0x00, 0x78, 0x01, 0x00, 0x01]
        assert sent[2] == [0x37, 0x00, 0xA0, 3, 0x00, 0x78, 0x01, 0x00, 0x00]

    def test_value_range(self):
        sent = []
        c = client_answering([0xFE], sent, writable={"%V"})
        with pytest.raises(ValueError):
            c.write_ladder("%V0.B", 200)
        assert c.write_ladder("%V0.B", 200, signed=False) is True
        assert sent[-1][-1] == 0xC8
        with pytest.raises(ValueError):
            c.write_ladder("%V0.B", -1, signed=False)
        assert c.write_ladder("%V0.B", -1) is True
        assert sent[-1][-1] == 0xFF

    def test_address_refused_before_sending(self):
        sent = []
        c = client_answering([0xFE], sent, writable={"%V"})
        with pytest.raises(ValueError):
            c.write_ladder("%V7800.&", 0)
        assert sent == []

    def test_unexpected_answer_code(self):
        c = client_answering([0x66, 64, 0x00], writable={"%V"})
        with pytest.raises(UnexpectedUniteResponse):
            c.write_ladder("%V0.B", 1)


class TestWriteMessage:
    def test_one_line_padded_to_32(self):
        sent = []
        c = client_answering([0xF5, 0xFE], sent)
        assert c.write_message("PYUNITELWAY TEST") is True
        assert sent[0][:5] == [0xF5, 0x00, 0x4B, 0x00, 1]
        assert sent[0][5:] == [ord(ch) for ch in "PYUNITELWAY TEST".ljust(32)]

    def test_three_lines(self):
        sent = []
        c = client_answering([0xF5, 0x7B], sent)  # the §3.6 table's code is accepted too
        assert c.write_message(["A", "B" * 32, ""]) is True
        assert sent[0][4] == 3 and len(sent[0]) == 5 + 96
        assert c.write_message("one\ntwo") is True
        assert sent[1][4] == 2 and len(sent[1]) == 5 + 64

    def test_rejections_before_sending(self):
        sent = []
        c = client_answering([0xF5, 0xFE], sent)
        for bad in ("", "a\nb\nc\nd", "x" * 33, "tab\there", "umlaut ä"):
            with pytest.raises(ValueError):
                c.write_message(bad)
        assert sent == []

    def test_negative_report(self):
        c = client_answering([0xF5, 0xFD])
        with pytest.raises(UniteRequestFailed):
            c.write_message("x")


class TestObjects:
    def test_read_mode_decodes_segment_180(self):
        c = client_answering(unwrap_unite_response(hv.READ_MODE))  # 66 00 00 00
        assert c.read_mode() is Mode.AUTO

    def test_write_mode_builds_the_frame_captured_in_2025(self):
        sent = []
        c = client_answering([0xFE], sent, writable={Object.MODE_SELECTION})
        assert c.write_mode(Mode.MDI) is True
        assert sent == [[0x37, 0x00, 0xB4, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02, 0x00]]

    def test_nc_objects_are_locked_by_default(self):
        sent = []
        c = client_answering([0xFE], sent)
        with pytest.raises(WriteNotAllowed):
            c.write_mode(Mode.MDI)
        with pytest.raises(WriteNotAllowed):
            c.write_object(Object.CURRENT_PROGRAMME_NUMBER, 1)
        assert sent == []
        c = client_answering([0xFE], sent, writable=ALL_NC_OBJECTS)
        assert c.write_object(Object.CURRENT_PROGRAMME_NUMBER, 1) is True

    def test_read_only_object_refuses_to_write(self):
        sent = []
        c = client_answering([0xFE], sent, writable=ALL_NC_OBJECTS)
        with pytest.raises(ValueError):
            c.write_object(Object.AXIS_MEASUREMENT, [0] * 9)
        assert sent == []

    def test_read_object_checks_the_size(self):
        c = client_answering([0x66, 0x00, 0x00])  # one byte for a one-word object
        with pytest.raises(UnexpectedDataLength):
            c.read_object(Object.MODE_SELECTION)

    def test_longs_and_int(self):
        c = client_answering([0x66, 0x00] + list((-5).to_bytes(4, "little", signed=True)) * 9, writable=ALL_NC_OBJECTS)
        assert c.read_object(Object.AXIS_MEASUREMENT) == [-5] * 9
        sent = []
        c = client_answering([0xFE], sent, writable=ALL_NC_OBJECTS)
        c.write_object(Object.CURRENT_PROGRAMME_NUMBER, 9001)
        assert sent[0][-2:] == [0x29, 0x23]


class TestEncodeLadderValueRejectsNonIntegers:
    def test_float_and_str(self):
        c = client_answering([0xFE], writable={"%V"})
        for bad in (1.5, "1", None):
            with pytest.raises(ValueError):
                c.write_ladder("%V0.B", bad)
