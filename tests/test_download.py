"""Download of a part programme (938914 §4.12): validator, segmenter, parsers and write_program(), no socket needed.

Frames follow the manual's example %32.1 (§4.12.4). Nothing here has been sent to the machine (todo.md K).
"""

import pytest

from pyunitelway.client import UnitelwayClient
from pyunitelway.constants import ALL_LADDER_SEGMENTS, CLOSE_DOWNLOAD, OPEN_DOWNLOAD, RESPONSE_CODES, WRITE_DOWNLOAD
from pyunitelway.errors import FileTransferError, ProgramNotVerified, ProgramRefused, WriteNotAllowed
from pyunitelway.num_constants import ALL_NC_OBJECTS, IMA_PROGRAM_NUMBERS, Action, Mode, Program
from pyunitelway.unite_responses import parse_download_close, parse_download_open, parse_download_segment
from pyunitelway.utils import download_segments, file_identification, program_blocks

from test_client import client_answering

OPEN_32_1 = [0x3A, 0x00, 0x41, 0x01, 0x00, 0x12, 0x00, 0x00, 0x00, 0x00]  # §4.12.4.1: H'12000141' = %32.1
PROGRAM = "N10 G4 F1\nN20 M2\n"
PROGRAM_BYTES = b"N10 G4 F1\r\nN20 M2\r\n"


def idle(running=False, mode=Mode.AUTO, current=9001):
    return {"nc_mode": mode, "nc_status": {"active_program": running}, "current_program_number": current}


def download_client(answers=None, sent=None, directory_before=(), directory_after=None, free=100000, back=PROGRAM_BYTES,
                    status=None, writable=(Action.WRITE_PROGRAM,)):
    """write_program()'s collaborators canned: unit status, directory before/after, free RAM, read-back."""
    answers = dict(answers or {0x3A: [0x6A, 0], 0x3B: None, 0x3C: [0x6C, 0]})
    pages = [list(directory_before), list(directory_after if directory_after is not None else directory_before)]

    def run(address, query, *args, **kwargs):
        if sent is not None:
            sent.append(list(query))
        if query[0] == WRITE_DOWNLOAD and answers[0x3B] is None:
            return [0x6B, 0, query[2], query[3]]  # echo the segment number
        return list(answers[query[0]])

    c = UnitelwayClient(writable=set(writable))
    c.run_unite = run
    c.get_unit_status = lambda axis_group_index=0: status or idle()
    c.read_directory = lambda start=0, group=0: pages.pop(0)
    c.get_available_bytes_in_ram = lambda: free
    c.read_program = lambda number, group=0, timeout=None: back
    return c


class TestProgramBlocks:
    def test_str_is_normalised_bytes_are_strict(self):
        assert program_blocks(PROGRAM) == [b"N10 G4 F1\r\n", b"N20 M2\r\n"]
        assert program_blocks("N10 G4 F1\r\nN20 M2\r\n") == program_blocks(PROGRAM)
        assert program_blocks(PROGRAM_BYTES) == program_blocks(PROGRAM)
        with pytest.raises(ValueError):
            program_blocks(b"N10 G4 F1\nN20 M2\n")  # bare LF: 0x0A inside a block

    @pytest.mark.parametrize("bad", [
        "", b"", "N10 M2", b"N10 M2\r", "N10 M2\n\n", "%32.1\nN10 M2\n", "N10 G4 F1\n%32.1\n", "N10 M\x00\n", "N10 Ö\n",
        "N10 " + "X" * 117 + "\n",  # 121 characters
    ])
    def test_refusals(self, bad):
        with pytest.raises(ValueError):
            program_blocks(bad)

    def test_120_characters_pass(self):
        block = "N10 " + "X" * 116  # 120 characters
        assert program_blocks(block + "\n") == [block.encode() + b"\r\n"]

    def test_segments_hold_whole_blocks(self):
        blocks = [b"N%03d G4 F1\r\n" % n for n in range(20)]  # 12 bytes each: 10 per 122-byte segment
        segments = download_segments(blocks)
        assert [len(s) for s in segments] == [120, 120]
        assert [len(s) for s in download_segments(blocks[:11])] == [120, 12]
        assert b"".join(segments) == b"".join(blocks)
        assert all(len(s) <= 122 for s in segments)
        one = b"N10 " + b"X" * 116 + b"\r\n"  # exactly 122
        assert download_segments([one, one]) == [one, one]


class TestParsers:
    def test_codes_and_file_id(self):
        assert (OPEN_DOWNLOAD, WRITE_DOWNLOAD, CLOSE_DOWNLOAD) == (0x3A, 0x3B, 0x3C)
        assert (RESPONSE_CODES[OPEN_DOWNLOAD], RESPONSE_CODES[WRITE_DOWNLOAD], RESPONSE_CODES[CLOSE_DOWNLOAD]) == (0x6A, 0x6B, 0x6C)
        assert file_identification(0x12, 321) == OPEN_32_1[2:]

    def test_open(self):
        assert parse_download_open([0x6A, 0]) == 0
        with pytest.raises(FileTransferError, match="file already exists"):
            parse_download_open([0x6A, 1])
        with pytest.raises(FileTransferError, match="128 bytes"):
            parse_download_open([0x6A, 3])

    def test_segment(self):
        assert parse_download_segment([0x6B, 0, 0x02, 0x00], 2) == 0  # §4.12.4.3
        with pytest.raises(FileTransferError, match="segment 1 answered, 2 sent"):
            parse_download_segment([0x6B, 0, 0x01, 0x00], 2)
        with pytest.raises(FileTransferError, match="120 characters"):
            parse_download_segment([0x6B, 11, 0x01, 0x00], 1)
        with pytest.raises(FileTransferError, match="sequence error"):
            parse_download_segment([0x6B, 25, 0x01, 0x00], 1)

    def test_close(self):
        assert parse_download_close([0x6C, 0]) == 0
        assert parse_download_close([0x6C, 4]) == 4
        with pytest.raises(FileTransferError, match="deleted"):
            parse_download_close([0x6C, 11])


class TestWriteProgram:
    def test_manual_example_on_the_wire(self):
        # the manual's %32.1 itself is refused: 32 is one of IMA's programmes (IMA_PROGRAM_NUMBERS); %777.1 instead
        sent = []
        c = download_client(sent=sent, directory_after=[Program(777, 1, 60)])
        text = "N10 X0 Y0\nN20 X-140\nN30 Y-60\n"
        c.read_program = lambda number, group=0, timeout=None: b"".join(program_blocks(text))
        assert c.write_program(777, text, group=1) == 60
        assert sent[0] == [0x3A, 0x00] + file_identification(0x12, 7771)
        with pytest.raises(ProgramRefused):
            download_client(sent=sent).write_program(32, text, group=1)
        assert sent[1] == [0x3B, 0x00, 0x01, 0x00, 32, 0x00] + list(b"N10 X0 Y0\r\nN20 X-140\r\nN30 Y-60\r\n")
        assert sent[2] == [0x3C, 0x00]

    def test_segments_are_numbered_from_one(self):
        sent = []
        text = "".join(f"N{n:03d} G4 F1\n" for n in range(20))
        data = b"".join(program_blocks(text))
        c = download_client(sent=sent, directory_after=[Program(7777, 0, 300)], back=data)
        assert c.write_program(7777, text) == 300
        writes = [q for q in sent if q[0] == WRITE_DOWNLOAD]
        assert [q[2] | q[3] << 8 for q in writes] == [1, 2]
        assert [q[4] | q[5] << 8 for q in writes] == [120, 120]
        assert b"".join(bytes(q[6:]) for q in writes) == data

    def test_locked_even_with_everything_else_open(self):
        for writable in [set(), ALL_LADDER_SEGMENTS | ALL_NC_OBJECTS, {Action.CYCLE_START}]:
            sent = []
            c = download_client(sent=sent, writable=writable)
            with pytest.raises(WriteNotAllowed):
                c.write_program(7777, PROGRAM)
            assert sent == []

    @pytest.mark.parametrize("number", [0, 9000, 9001, 9997, 5, 101, 609, 8999 + 1])
    def test_protected_numbers_send_nothing(self, number):
        sent = []
        with pytest.raises(ProgramRefused, match="never written"):
            download_client(sent=sent).write_program(number, PROGRAM)
        assert sent == []
        assert 5 in IMA_PROGRAM_NUMBERS and 9997 not in IMA_PROGRAM_NUMBERS  # 9997 falls to the range check

    @pytest.mark.parametrize("kwargs, reason", [
        (dict(status=idle(running=True)), "not idle"),
        (dict(status=idle(mode=Mode.EDIT)), "not idle"),
        (dict(status=idle(current=7777)), "active programme"),
        (dict(directory_before=[Program(7777, 0, 50)]), "already in the NC RAM"),
        (dict(free=100), "bytes free"),
    ])
    def test_machine_state_refusals_send_nothing(self, kwargs, reason):
        sent = []
        with pytest.raises(ProgramRefused, match=reason):
            download_client(sent=sent, **kwargs).write_program(7777, PROGRAM)
        assert sent == []

    def test_bad_text_sends_nothing(self):
        sent = []
        with pytest.raises(ValueError):
            download_client(sent=sent).write_program(7777, "%7777\nN10 M2\n")
        assert sent == []

    def test_open_refused_sends_no_segment_and_no_close(self):
        sent = []
        c = download_client(answers={0x3A: [0x6A, 1], 0x3B: None, 0x3C: [0x6C, 0]}, sent=sent)
        with pytest.raises(FileTransferError, match="file already exists"):
            c.write_program(7777, PROGRAM)
        assert [q[0] for q in sent] == [OPEN_DOWNLOAD]

    def test_segment_failure_still_closes(self):
        sent = []
        c = download_client(answers={0x3A: [0x6A, 0], 0x3B: [0x6B, 25, 0x01, 0x00], 0x3C: [0x6C, 0]}, sent=sent)
        with pytest.raises(FileTransferError, match="sequence error"):
            c.write_program(7777, PROGRAM)
        assert [q[0] for q in sent] == [OPEN_DOWNLOAD, WRITE_DOWNLOAD, CLOSE_DOWNLOAD]

    def test_close_deleted_the_file(self):
        c = download_client(answers={0x3A: [0x6A, 0], 0x3B: None, 0x3C: [0x6C, 11]})
        with pytest.raises(FileTransferError, match="deleted"):
            c.write_program(7777, PROGRAM)

    def test_verification(self):
        with pytest.raises(ProgramNotVerified, match="not in the directory"):
            download_client(directory_after=[]).write_program(7777, PROGRAM)
        with pytest.raises(ProgramNotVerified, match="read back 5 bytes, sent 19"):
            download_client(directory_after=[Program(7777, 0, 40)], back=b"N10\r\n").write_program(7777, PROGRAM)

    def test_full_segment_request_frame(self):
        # 122 data bytes + 6-byte request header = 128 bytes, the UNI-TE maximum: length byte 134, and a segment
        # number of 16 (0x10) is doubled on the wire (35000789 §3.5)
        c = UnitelwayClient()
        segment = bytes([0x41] * 122)
        query = [0x3B, 0x00, 0x10, 0x00, 122, 0x00] + list(segment)
        frame = c._xway_to_unitelway(c._unite_to_xway(query))
        assert frame[3] == 134
        assert frame[4:14] == [0x20, 0x00, 0xFE, 0x00, 0x00, 0x00, 0x3B, 0x00, 0x10, 0x10]
        assert len(frame) == 4 + 134 + 1 + 1  # start, header+data, one doubled DLE, BCC


DELETE_44_1 = [0xF5, 0x00, 0x46, 0xB9, 0x01, 0x00, 0x12]  # §4.14 example: %44.1 = H'120001B9'


def delete_client(answer=(0xF5, 0x76, 0), sent=None, directory_before=(Program(7777, 0, 28),), directory_after=(),
                  status=None, writable=(Action.DELETE_PROGRAM,)):
    pages = [list(directory_before), list(directory_after)]

    def run(address, query, *args, **kwargs):
        if sent is not None:
            sent.append(list(query))
        return list(answer)

    c = UnitelwayClient(writable=set(writable))
    c.run_unite = run
    c.get_unit_status = lambda axis_group_index=0: status or idle()
    c.read_directory = lambda start=0, group=0: pages.pop(0)
    return c


class TestDeleteProgram:
    def test_manual_example_on_the_wire(self):
        sent = []
        c = delete_client(sent=sent, directory_before=[Program(44, 1, 300)])
        assert c.delete_program(44, group=1) == 300
        assert sent == [DELETE_44_1]

    def test_locked_even_with_everything_else_open(self):
        for writable in [set(), ALL_LADDER_SEGMENTS | ALL_NC_OBJECTS, {Action.WRITE_PROGRAM}]:
            sent = []
            with pytest.raises(WriteNotAllowed):
                delete_client(sent=sent, writable=writable).delete_program(7777)
            assert sent == []

    @pytest.mark.parametrize("number", [0, 9000, 9001, 9997, 5, 101, 609])
    def test_protected_numbers_send_nothing(self, number):
        sent = []
        with pytest.raises(ProgramRefused, match="never deleted"):
            delete_client(sent=sent, directory_before=[Program(number, 0, 10)]).delete_program(number)
        assert sent == []

    @pytest.mark.parametrize("kwargs, reason", [
        (dict(status=idle(running=True)), "not idle"),
        (dict(status=idle(mode=Mode.EDIT)), "not idle"),
        (dict(status=idle(current=7777)), "active programme"),
        (dict(directory_before=[]), "not in the NC RAM"),
    ])
    def test_machine_state_refusals_send_nothing(self, kwargs, reason):
        sent = []
        with pytest.raises(ProgramRefused, match=reason):
            delete_client(sent=sent, **kwargs).delete_program(7777)
        assert sent == []

    @pytest.mark.parametrize("status, reason", [(5, "no such file"), (10, "being executed"), (2, "programme area")])
    def test_nc_rejections(self, status, reason):
        with pytest.raises(FileTransferError, match=reason):
            delete_client(answer=(0xF5, 0x76, status)).delete_program(7777)

    def test_negative_report_and_verification(self):
        with pytest.raises(Exception):  # F5 FD: the specific request's negative report (utils.check_specific_answer)
            delete_client(answer=(0xF5, 0xFD)).delete_program(7777)
        with pytest.raises(ProgramNotVerified, match="still in the directory"):
            delete_client(directory_after=[Program(7777, 0, 28)]).delete_program(7777)
