"""Byte helpers: framing, checksums, ladder and object encoding, file identification."""

import operator

from .constants import *
from .num_constants import Mode, ladder_size, ladder_specific
from .errors import MalformedUnitelwayResponse, UnexpectedAdditionalAnswerCode, UnexpectedUniteResponse, UniteRequestFailed



def format_hex_list(data):
    """``[0x10, 0x02]`` -> ``"10 02"``."""
    return " ".join(f"{b:02x}" for b in data)


def get_response_code(query_code):
    """Answer code of a request: ``RESPONSE_CODES`` or request code + 0x30 (938914 §3)."""
    return RESPONSE_CODES.get(query_code, query_code + 0x30)


def is_valid_response_code(query_code, resp_code):
    """``True`` for the request's answer code or the ``0xFD`` negative report."""
    return resp_code == 0xFD or resp_code == get_response_code(query_code)


def ladder_specific_byte(size):
    """Specific byte for a ladder object size: bit ``n`` -> ``n``, ``B`` 64, ``W`` 65, ``L``/``&`` 66 (938914 §4.1.3.3).

    :param str size: Size suffix of the variable
    :rtype: int
    """
    return int(size) if size.isdigit() else ladder_specific[size]


def encode_ladder_value(size, value, signed=True):
    """Encode a value for Write-Object: a bit as one byte (non-zero = set, verified 2026-09-23), ``.B``/``.W``/``.L``
    little-endian (938914 §2), so the first ladder byte is the MSB (938846 §4).

    :param str size: ``0``-``7``, ``B``, ``W`` or ``L``
    :param value: ``bool`` for a bit, else an ``int`` within the signed or unsigned range of the size
    :rtype: list[int]
    :raises ValueError: ``&``, non-integer, or out of range
    """
    if size.isdigit():
        return [0x01 if value else 0x00]
    if size == "&":
        raise ValueError("an address (.&) cannot be written")
    try:
        return list(operator.index(value).to_bytes(ladder_size[size], "little", signed=signed))
    except TypeError:
        raise ValueError(f"an integer is required, got {value!r}") from None
    except OverflowError:
        raise ValueError(f"{value} does not fit a{'n unsigned' if not signed else ' signed'} .{size}") from None


def encode_object(spec, value):
    """Encode a value for Write-Object per its ``ObjectSpec`` (little-endian, signed).

    :param ObjectSpec spec: Object layout
    :param value: ``Mode``, ``int``, list of long words, or raw bytes - per ``spec.kind``
    :rtype: list[int]
    :raises ValueError: Wrong number of long words / bytes
    """
    if spec.kind == "mode":
        return list(int(Mode(value)).to_bytes(spec.size, "little"))
    if spec.kind == "int":
        return list(int(value).to_bytes(spec.size, "little", signed=True))
    if spec.kind == "longs":
        values = list(value)
        if len(values) * 4 != spec.size:
            raise ValueError(f"expected {spec.size // 4} long words, got {len(values)}")
        return [b for v in values for b in int(v).to_bytes(4, "little", signed=True)]
    data = list(value)
    if len(data) != spec.size:
        raise ValueError(f"expected {spec.size} bytes, got {len(data)}")
    return data


def file_identification(file_type, identification=0):
    """The two long words of Open-Upload-Sequence (938914 §4.13.1), little-endian.

    Long word 1 carries the type in its high byte and the identification in the low three
    (§4.13.4.1: ``H'120005B5'`` = part programme %146.1); long word 2 is not significant.
    """
    if not 0 <= identification <= 0xFFFFFF:
        raise ValueError(f"identification 0x{identification:X} does not fit 3 bytes")
    long1 = (int(file_type) << 24) | identification
    return list(long1.to_bytes(4, "little")) + [0, 0, 0, 0]


def check_specific_answer(response, additional_request, also_accept=()):
    """Check a NUM specific answer ``F5 / additional code`` (938914 §3.6).

    :param int additional_request: The additional request code sent, e.g. ``READ_MEMORY_FREE``
    :param tuple[int] also_accept: Other additional answer codes to accept where the manual contradicts itself
    :raises UnexpectedUniteResponse: Answer code is not ``F5``
    :raises UniteRequestFailed: Additional code ``FD``, the negative report
    :raises UnexpectedAdditionalAnswerCode: Another request's code
    """
    if response[0] != SPECIFIC_REQUEST:
        raise UnexpectedUniteResponse(SPECIFIC_REQUEST, response[0])
    expected = ADDITIONAL_ANSWER_CODES[additional_request]
    got = response[1]
    if got == 0xFD:
        raise UniteRequestFailed()
    if got != expected and got not in also_accept:
        raise UnexpectedAdditionalAnswerCode(expected, got)


def compute_response_length(unitelway):
    """Total on-wire length of one UNI-TELWAY frame, in raw bytes.

    Follows the ``<DLE>`` padding rules of manual 35000789 §3.5/§3.12, so
    ``unitelway[:compute_response_length(unitelway)]`` is exactly one frame,
    whatever trails it in the receive buffer.

    :param list[int] unitelway: Received bytes, starting at the header ``<DLE>``
    :returns: Raw byte count of the frame (header, padding and BCC included)
    :rtype: int
    :raises MalformedUnitelwayResponse: No valid, complete frame at the buffer start
    """
    if len(unitelway) < 6:
        raise MalformedUnitelwayResponse(f"need at least 6 bytes for a frame, got {len(unitelway)}")
    if unitelway[0] != DLE or unitelway[1] != STX:
        raise MalformedUnitelwayResponse("frame does not start with <DLE><STX>")

    length = unitelway[3]
    i = 4
    if length == DLE:
        if unitelway[i] != DLE:
            raise MalformedUnitelwayResponse("<length> equals <DLE> but is not duplicated")
        i += 1
    if not 1 <= length <= 134:  # 134 = max NPDU size (35000789 §3.12)
        raise MalformedUnitelwayResponse(f"<length> {length} out of range [1..134]")

    for _ in range(length):
        if i >= len(unitelway):
            raise MalformedUnitelwayResponse("buffer ends inside <data>")
        if unitelway[i] == DLE:
            if i + 1 >= len(unitelway) or unitelway[i + 1] != DLE:
                raise MalformedUnitelwayResponse("<DLE> in <data> is not duplicated")
            i += 2
        else:
            i += 1

    if i >= len(unitelway):
        raise MalformedUnitelwayResponse("buffer ends before <BCC>")
    return i + 1


def duplicate_dle(unitelway, start_index):
    """Double every ``<DLE>`` from ``start_index`` on, in place (35000789 §3.5); the length byte is handled by the caller."""
    i = start_index
    while i < len(unitelway):
        if unitelway[i] == DLE:
            unitelway.insert(i, DLE)
            i += 1
        i += 1


def delete_dle(unitelway):
    """Undo the ``<DLE>`` doubling of a received frame; header and BCC are copied as they are."""
    result = unitelway[:3]
    i = 3
    while i < len(unitelway) - 1:
        result.append(unitelway[i])
        if unitelway[i] == DLE:
            i += 1  # skip the doubled one
        i += 1
    result.append(unitelway[-1])
    return result


def compute_bcc(unitelway_bytes):
    """Checksum: the sum of all bytes modulo 256, taken after the ``<DLE>`` doubling (35000789 §3.5)."""
    return sum(unitelway_bytes) % 256


def check_unitelway(response):
    """``True`` if the frame's last byte is its checksum."""
    return compute_bcc(response[:-1]) == response[-1]


def read_byte(data):
    """Pop one byte from the front of ``data``."""
    return data.pop(0)


def read_word(data):
    """Pop a little-endian word from the front of ``data``."""
    return read_int([read_byte(data) for _ in range(2)])


def read_dword(data):
    """Pop a little-endian long word from the front of ``data``."""
    return read_int([read_byte(data) for _ in range(4)])


def read_int(data):
    """Little-endian integer from a list of bytes."""
    return int.from_bytes(data, "little")
def program_blocks(text):
    """Split a part programme into blocks for Write-Download-Segment and refuse what the NC would refuse or store wrong
    (938914 §4.12.2-§4.12.3): printable ASCII only, every block ends with CR LF, no block over 120 characters, no empty
    block, no ``%`` header line (the number comes from the file identification). A ``str`` is normalised to CR LF line
    ends; ``bytes`` are taken as they are (a backup file, byte for byte).

    :returns: The blocks, each with its CR LF
    :rtype: list[bytes]
    :raises ValueError: Anything the NC would reject, or that would end in a deleted or wrong file
    """
    if isinstance(text, str):
        try:
            data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii")
        except UnicodeEncodeError as e:
            raise ValueError(f"not ASCII: {e}") from None
    else:
        data = bytes(text)
    if not data:
        raise ValueError("empty programme")
    if not data.endswith(b"\r\n"):
        raise ValueError("the last block must end with CR LF, else Close-Download-Sequence deletes the file (938914 §4.12.3)")
    blocks = [block + b"\r\n" for block in data[:-2].split(b"\r\n")]
    for n, block in enumerate(blocks, 1):
        body = block[:-2]
        if not body:
            raise ValueError(f"block {n} is empty")
        if any(not 0x20 <= byte <= 0x7E for byte in body):
            raise ValueError(f"block {n} has a byte outside printable ASCII")
        if len(body) > 120:
            raise ValueError(f"block {n} has {len(body)} characters, the NC takes 120 (938914 §4.12.2)")
        if body.startswith(b"%"):
            raise ValueError(f"block {n} is a %-header line; the programme number comes from the file identification")
    return blocks


def download_segments(blocks, limit=122):
    """Pack whole blocks into segments of at most ``limit`` bytes (938914 §4.12.2: 122 data bytes per request), so a
    sequence error can only cut between blocks.

    :rtype: list[bytes]
    """
    segments, current = [], b""
    for block in blocks:
        if len(current) + len(block) > limit:
            segments.append(current)
            current = b""
        current += block
    if current:
        segments.append(current)
    return segments
