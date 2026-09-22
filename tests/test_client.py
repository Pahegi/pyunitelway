"""Client-level tests that need no socket.

Answer validation of the NUM specific requests (938914 §3.6, §4.15; 938928 §10.4.10) and the
bounded wait for the master's polling window (35000789 §3.6).
"""

import socket

import pytest

from pyunitelway.client import UnitelwayClient
from pyunitelway.constants import (
    ADDITIONAL_ANSWER_CODES,
    READ_MEMORY_FREE,
    RESPONSE_CODES,
    SHUTDOWN,
    SPECIFIC_REQUEST,
    WRITE_MESSAGE,
)
from pyunitelway.errors import (
    NoPollingWindow,
    UnexpectedAdditionalAwnserCode,
    UnexpectedUniteResponse,
    UniteRequestFailed,
)
from pyunitelway.utils import check_specific_answer, is_valid_response_code

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
    """Replays canned recv() chunks, then behaves like a socket that timed out."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.timeout = "untouched"

    def settimeout(self, t):
        self.timeout = t

    def recv(self, n):
        if self.chunks:
            return self.chunks.pop(0)
        raise socket.timeout()


class TestIsMyTurnToTalk:
    def test_returns_once_our_address_is_polled(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket([b"\x10\x05\x02", b"\x10\x05\x01"])
        assert c.is_my_turn_to_talk(0x01, timeout=1) is True
        assert c.socket.timeout is None  # blocking mode restored afterwards

    def test_raises_when_only_other_addresses_are_polled(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket([b"\x10\x05\x02"] * 3)
        with pytest.raises(NoPollingWindow):
            c.is_my_turn_to_talk(0x01, timeout=1)
        assert c.socket.timeout is None

    def test_raises_on_a_silent_link(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket([])
        with pytest.raises(NoPollingWindow):
            c.is_my_turn_to_talk(0x01, timeout=1)

    def test_closed_connection_is_not_a_polling_problem(self):
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket([b""])
        with pytest.raises(ConnectionError):
            c.is_my_turn_to_talk(0x01, timeout=1)
