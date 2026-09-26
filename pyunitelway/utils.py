"""Utilities functions module.
"""

import operator
import time

from .constants import *
from .num_constants import Mode, ladder_size, ladder_specific
from .errors import MalformedUnitelwayResponse, UnexpectedAdditionalAwnserCode, UnexpectedUniteResponse, UniteRequestFailed



def format_bytearray(ba):
    """Format ``bytearray`` bytes in hexadecimal.
    
    Bytes are space-separated.
    
    :param bytearray ba: Bytes to format
    :returns: Bytes as string
    :rtype: str
    """
    hex_s = ba.hex()

    result = ""
    for i, c in enumerate(hex_s):
        result += c

        if i % 2 == 1 and i < len(hex_s) - 1:
            result += ' '

    return result


def format_hex_list(list):
    """Format a list of bytes in hexadecimal.
    
    Bytes are space-separated.
    
    :param list[int] list: List of bytes
    :returns: Bytes as string
    :rtype: str
    """
    return format_bytearray(bytearray(list))


def get_response_code(query_code):
    """Return the UNI-TE response code that corresponds to a request code.
    
    | For reading and IO writing requests: response code = ``request code + 0x30``.
    | For other writing requests: response code = ``0xFE``.

    :param int query_code: Request code of which we want the response code

    :returns: The corresponding response code
    :rtype: Union[int, list[int]]
    """
    if query_code in RESPONSE_CODES.keys():
        return RESPONSE_CODES[query_code]

    return query_code + 0x30


def is_valid_response_code(query_code, resp_code):
    """Check if a UNI-TE response code is valid.

    A code is valid if it's ``0xFD`` (request failed), ``request code + 0x30`` or ``0xFE``.
    Other response codes can be received because of conflicts (e.g. receive response for another request).

    :param Union[int, list[int]] query_code: Request code
    :param Union[int, list[int]] resp_code: Received response code

    :returns: True if the code is valid
    :rtype: bool
    """
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
    """Validate the answer of a NUM specific request (938914 §3.6).

    These requests all use request code ``H'F5'`` and answer with ``H'F5'`` followed by
    an *additional answer code* that identifies the request (``ADDITIONAL_ANSWER_CODES``).
    An additional code of ``H'FD'`` is the negative report (938914 §4.17).

    :param list[int] response: UNI-TE answer bytes, starting at the answer code
    :param int additional_request: Additional request code that was sent (e.g. ``READ_MEMORY_FREE``)
    :param tuple[int] also_accept: Further additional answer codes to accept (manual contradictions)

    :raises UnexpectedUniteResponse: The answer code is not ``H'F5'``
    :raises UniteRequestFailed: Additional answer code ``H'FD'``
    :raises UnexpectedAdditionalAwnserCode: The additional answer code belongs to another request
    """
    if response[0] != SPECIFIC_REQUEST:
        raise UnexpectedUniteResponse(SPECIFIC_REQUEST, response[0])
    expected = ADDITIONAL_ANSWER_CODES[additional_request]
    got = response[1]
    if got == 0xFD:
        raise UniteRequestFailed()
    if got != expected and got not in also_accept:
        raise UnexpectedAdditionalAwnserCode(expected, got)



def split_list_n(list, n):
    """Split a list each ``n`` elements.

    :param list list: List to split
    :param int n: Number of elements in each sub-sequence

    :returns: Splitted list
    :rtype: list[list]
    """
    splitted = []
    word = []
    try:
        for i, b in enumerate(list):
            if i % n == 0:
                if len(word) > 0:
                    splitted.append(word)
                word = []
            word.append(b)
            if i == len(list) - 1:
                splitted.append(word)
    except Exception:
        raise (Exception("split_list_n function error !"))

    return splitted


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
    """Duplicate ``<DLE>``'s in a UNI-TELWAY request, before sending it.

    This function modifies directly the input message.

    ``<DLE>`` bytes (``0x10``) are duplicated if:

    * the message length (4th byte) equals ``<DLE>``
    * or ``<DLE>`` is contained in the data section.

    The length is calculated before duplicating ``<DLE>``'s.

    The ``start_index`` is the first data byte index. It's useful when the length equals ``<DLE>``, because all the message is shifted.

    :param list[int] unitelway: UNI-TELWAY bytes
    :param int start_index: First data byte index
    """
    i = start_index
    while i < len(unitelway):
        c = unitelway[i]
        if c == DLE:
            unitelway.insert(i, c)
            i += 1  # skip the duplicated DLE

        i += 1


def delete_dle(unitelway):
    """Delete duplicated ``<DLE>`` characters in a UNI-TELWAY response.

    :param list[int] unitelway: UNI-TELWAY bytes

    :returns: New UNI-TELWAY message without duplicated ``<DLE>``'s
    :rtype: list[int]    
    """
    result = unitelway[:3]
    bytes_length = len(unitelway)

    i = 3
    while i < bytes_length - 1:
        b = unitelway[i]
        if b != DLE:
            result.append(b)
        else:
            # Insert second DLE
            try:
                result.append(unitelway[i + 1])
            except:
                pass

            i += 1  # skip duplicated DLE

        i += 1

    result.append(unitelway[bytes_length - 1])

    return result


def compute_bcc(unitelway_bytes):
    """Compute a UNI-TELWAY message checksum.

    The checksum is the sum of all bytes modulo 256. It's computed after ``<DLE>``'s duplication.
    
    :param list[int] unitelway_bytes: UNI-TELWAY message
    
    :returns: Sum of all bytes modulo 256
    :rtype: int
    """
    return sum(unitelway_bytes) % 256


def check_unitelway(response):
    """Check if a received UNI-TELWAY message is valid using its checksum.
    
    This function computes the checksum, and checks if it equals the received message checksum.

    :param list[int] response: UNI-TELWAY message to check

    :returns: ``True`` if the checksum is good. ``False`` otherwise
    :rtype: bool
    """
    bcc = compute_bcc(response[:-1])
    return bcc == response[-1]


def read_byte(data):
    """Read a byte from a list of bytes.

    The byte is removed from the list.

    :param list[int] data: List of bytes

    :returns: Read byte as int
    :rtype: int
    """
    return data.pop(0)


def read_word(data):
    """Read a word (2 bytes) from a list of bytes.

    The word is removed from the list.

    :param list[int] data: List of bytes

    :returns: Read word as int
    :rtype: int
    """
    return data.pop(0) + data.pop(0) * 256


def read_dword(data):
    """Read a double word / long word (4 bytes) from a list of bytes.

    The double word is removed from the list.

    :param list[int] data: List of bytes

    :returns: Read double word as int
    :rtype: int
    """
    return data.pop(0) + data.pop(0) * 256 + data.pop(0) * 65536 + data.pop(0) * 16777216


def read_bytes(data, n):
    """Read a list of bytes from a list of bytes.

    The bytes are removed from the list.

    :param list[int] data: List of bytes
    :param int n: Number of bytes to read

    :returns: Read bytes
    :rtype: list[int]
    """
    result = []
    for _ in range(n):
        result.append(data.pop(0))

    return result


def read_int(data):
    """Read an integer with variable number of bytes from a list of bytes.

    :param list[int] data: List of bytes

    :returns: Read integer
    :rtype: int
    """
    return int.from_bytes(data, byteorder='little')
