"""File reading: upload sequence (938914 §4.13) and NC memory directory (§4.16), no socket needed.

Frames follow the manual's examples: %146.1 (§4.13.4) and the %9xxx directory (§4.16.4).
"""

import pytest

from pyunitelway.client import UnitelwayClient
from pyunitelway.constants import CLOSE_UPLOAD, OPEN_UPLOAD, READ_UPLOAD, RESPONSE_CODES
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.errors import FileTransferError, OperationInProgrammeArea, UnexpectedDataLength, UnexpectedUniteResponse
from pyunitelway.num_constants import PLC_ALL_MODULES, FileType, Program, program_index
from pyunitelway.unite_responses import parse_upload_segment
from pyunitelway.utils import file_identification

from test_client import FakeSocket, POLL_01, client_answering
from test_conversion import wire_frame

OPEN_146_1 = [0x3D, 0x00, 0xB5, 0x05, 0x00, 0x12, 0x00, 0x00, 0x00, 0x00]  # §4.13.4.1: H'120005B5'
SEG1, SEG2, CLOSE = [0x3E, 0x00, 0x01, 0x00], [0x3E, 0x00, 0x02, 0x00], [0x3F, 0x00]
PART1, PART2 = bytes(range(121)), b"N100 M02\n" * 3 + b"XX"  # 121 + 35 bytes as in §4.13.4.2-3


def segment(status, number, data):
    return [0x6E, status, *number.to_bytes(2, "little"), *len(data).to_bytes(2, "little"), *data]


def scripted_client(answers, sent=None):
    """run_unite pops one canned answer per request, in order."""
    answers = list(answers)
    return client_answering(None, sent, run=lambda: answers.pop(0))


class TestFileIdentification:
    def test_manual_examples(self):
        assert file_identification(FileType.PART_PROGRAM, program_index(146, 1)) == OPEN_146_1[2:]
        assert file_identification(FileType.PLC_LADDER, PLC_ALL_MODULES << 16) == [0x00, 0x00, 0x10, 0x07, 0, 0, 0, 0]
        assert file_identification(FileType.MACHINE_PARAMETERS) == [0, 0, 0, 0x05, 0, 0, 0, 0]

    def test_bounds(self):
        with pytest.raises(ValueError):
            file_identification(FileType.PART_PROGRAM, 0x1000000)
        with pytest.raises(ValueError):
            program_index(9001, 10)
        with pytest.raises(ValueError):
            FileType(0x0C)  # drip feed is a download type

    def test_program_round_trip(self):
        assert program_index(9000) == 90000  # §4.16.4.1
        assert Program.from_index(90010, 2048) == Program(9001, 0, 2048)
        assert Program(146, 1, 5).name == "%146.1"

    def test_request_codes(self):
        assert (OPEN_UPLOAD, READ_UPLOAD, CLOSE_UPLOAD) == (0x3D, 0x3E, 0x3F)
        assert RESPONSE_CODES[READ_UPLOAD] == 0x6E


class TestUpload:
    def test_two_segments_then_close(self):
        sent = []
        c = scripted_client([[0x6D, 0], segment(0, 1, PART1), segment(15, 2, PART2), [0x6F, 4]], sent)
        assert c.read_program(146, 1) == PART1 + PART2
        assert sent == [OPEN_146_1, SEG1, SEG2, CLOSE]

    def test_empty_programme_is_closed_too(self):
        sent = []
        c = scripted_client([[0x6D, 15], [0x6F, 0]], sent)
        assert c.read_program(146, 1) == b""
        assert sent == [OPEN_146_1, CLOSE]

    def test_open_refused_sends_nothing_more(self):
        sent = []
        with pytest.raises(FileTransferError, match="status 5, no such programme"):
            scripted_client([[0x6D, 5]], sent).read_program(1)
        assert sent == [[0x3D, 0x00, 0x0A, 0x00, 0x00, 0x12, 0, 0, 0, 0]]

    @pytest.mark.parametrize("bad, error", [
        (segment(25, 1, b""), FileTransferError),  # sequence error
        (segment(0, 2, PART1), FileTransferError),  # another segment number
        ([0x6E, 0, 1, 0, 5, 0, 1, 2], UnexpectedDataLength),  # length 5, 2 bytes
        ([0xFE], UnexpectedUniteResponse),
    ])
    def test_bad_segment_still_closes(self, bad, error):
        sent = []
        with pytest.raises(error):
            scripted_client([[0x6D, 0], bad, [0x6F, 0]], sent).read_program(146, 1)
        assert sent[-1] == CLOSE

    def test_close_statuses(self):
        assert client_answering([0x6F, 0]).close_upload() is True
        assert client_answering([0x6F, 4]).close_upload() is False  # already closed
        with pytest.raises(FileTransferError, match="status 20"):
            client_answering([0x6F, 20]).close_upload()

    def test_typed_helpers_and_timeout(self):
        calls = []

        def run(address, query, timeout=None, text=""):
            calls.append((list(query), timeout))
            return {0x3D: [0x6D, 15], 0x3F: [0x6F, 0]}[query[0]]

        c = UnitelwayClient()
        c.run_unite = run
        assert c.read_machine_parameters(timeout=30) == b""
        assert c.read_plc_archive(timeout=30) == b""
        assert [q[2:6] for q, _ in calls if q[0] == 0x3D] == [[0, 0, 0, 0x05], [0, 0, 0x10, 0x07]]
        assert {t for _, t in calls} == {30}

    def test_full_segment_frame_on_the_wire(self):
        # 122 data bytes = the 128-byte NPDU limit (35000789 §4.2): length byte 134
        data = bytes(range(122))
        frame = wire_frame(0x01, [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00] + segment(0, 1, data))
        assert frame[3] == 134
        c = UnitelwayClient(slave_address=0x01)
        c.socket = FakeSocket(live=POLL_01 + bytes(frame))
        assert parse_upload_segment(unwrap_unite_response(c._read_frame(1)), 1) == (0, data)


def pairs(programs):
    out = []
    for p in programs:
        out += [*program_index(p.number, p.group).to_bytes(4, "little"), *p.size.to_bytes(4, "little")]
    return out


PAGE1 = [Program(9000 + i, 0, 100 + i) for i in range(15)]
PAGE2 = [Program(9990, 0, 7), Program(9993, 0, 8)]
OPEN_9000 = [0xF5, 0x00, 0x48, 0x90, 0x5F, 0x01, 0x00]  # §4.16.4.1: from 90000
NEXT, CLOSE_DIR = [0xF5, 0x00, 0x49], [0xF5, 0x00, 0x4A]


class TestDirectory:
    def test_two_pages_closed_by_the_nc(self):
        sent = []
        c = scripted_client([[0xF5, 0x78, 0] + pairs(PAGE1), [0xF5, 0x79, 15] + pairs(PAGE2)], sent)
        assert c.read_directory(9000) == PAGE1 + PAGE2
        assert sent == [OPEN_9000, NEXT]

    def test_single_page_from_zero(self):
        sent = []
        c = scripted_client([[0xF5, 0x78, 15] + pairs(PAGE2)], sent)
        assert c.read_directory() == PAGE2
        assert sent == [[0xF5, 0x00, 0x48, 0, 0, 0, 0]]

    def test_rejections(self):
        with pytest.raises(OperationInProgrammeArea):
            scripted_client([[0xF5, 0x78, 2]]).read_directory()
        with pytest.raises(FileTransferError, match="status 9, buffer too small"):
            scripted_client([[0xF5, 0x78, 9]]).read_directory()
        with pytest.raises(UnexpectedDataLength):
            scripted_client([[0xF5, 0x78, 15, 1, 2, 3]]).read_directory()

    def test_failure_mid_list_closes(self):
        sent = []
        with pytest.raises(FileTransferError):
            scripted_client([[0xF5, 0x78, 0] + pairs(PAGE1), [0xF5, 0x79, 9], [0xF5, 0x7A, 0]], sent).read_directory()
        assert sent == [[0xF5, 0x00, 0x48, 0, 0, 0, 0], NEXT, CLOSE_DIR]

    def test_close_statuses(self):
        assert client_answering([0xF5, 0x7A, 0]).close_directory() is True
        assert client_answering([0xF5, 0x7A, 4]).close_directory() is False
