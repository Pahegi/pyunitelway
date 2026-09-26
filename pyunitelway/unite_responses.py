from pyunitelway.constants import LADDER_REQUEST, STATUS_MEANING
from pyunitelway.errors import (
    FileTransferError,
    OperationInProgrammeArea,
    UnexpectedAdditionalAnswerCode,
    UnexpectedDataLength,
    UnexpectedObjectTypeResponse,
)
from pyunitelway.num_constants import Mode, Program, symbol_bounds, symbol_low_byte_max, ladder_size
from pyunitelway.utils import ladder_specific_byte, read_byte, read_dword, read_word


def parse_mirror_result(received_data, sent_data):
    """Mirror (938914 §4.5): ``True`` if the NC echoed what was sent."""
    return received_data == sent_data


PRODUCT_TYPES = {100: "NUM 1060", 101: "NUM 1060 Series II", 102: "NUM 1040", 103: "NUM 1060-7"}  # 938914 §4.3


def parse_unit_identification(received_data):
    """Unit identification (938914 §4.3): product type code and name, subtype, version index, text.

    This UC SII answers type 102 ("NUM 1040") with the text ``NUM1060S2UCS2``; trust the text.
    """
    r = list(received_data)
    return {
        "product_type_code": r[1],
        "product_type": PRODUCT_TYPES.get(r[1], f"unknown ({r[1]})"),
        "subtype": chr(r[2]),
        "product_version": r[3] >> 4,  # high half-byte
        "text": bytes(r[5:5 + r[4]]).decode("latin-1"),
    }


# 938914 §4.4 status byte and mask, bits 0-7
STATUS_BITS = ("system_inoperative", "recoverable_error", "unrecoverable_error", "auxiliary_power_source",
               "system_reset", "critical_operation", "halt", "local_mode")
# segment 153 G list; bits 5, 22, 26 and 29 are not assigned
G_FUNCTION_BITS = {
    "G00": 0, "G01": 1, "G02": 2, "G03": 3, "G04": 4, "G38": 6, "G09": 7, "G17": 8, "G19": 9, "G18": 10, "G90": 11,
    "G91": 12, "G70": 13, "G52": 14, "G22": 15, "G40": 16, "G41": 17, "G42": 18, "G53": 19, "G54": 20, "G29": 21,
    "G93": 23, "G94": 24, "G95": 25, "G96": 27, "G97": 28, "G20": 30, "G21": 31,
}
PROCESS_BITS = {
    "function G79": 0, "end of external movement": 1, "encoded M function": 2, "M post-function": 3,
    "function G04": 4, "function G09": 5, "execution of a circle": 6, "execution of a line": 7, "JOG": 8,
    "FEED STOP": 11, "M pre-function": 13, "T function": 15,
}
# %R3.B and %R5.B (938846 §3.8.1): E_RAZ, E_ARUS, E_CYCLE, E_RAX, E_DGURG, E_DEFCN, E_OPER; E_CNPRET, E_PROG, E_PPP, E_TRANSP
PANEL_BITS = {"cnc_reset_in_progress": 0x01, "cycle_stop": 0x02, "cycle_in_progress": 0x04, "axis_recall": 0x08,
              "emergency_retract": 0x10, "cnc_fault": 0x40, "program_stop": 0x80}
NC_BITS = {"cnc_ready": 0x01, "active_program": 0x02, "drip_feed_ready": 0x20, "transparent_mode": 0x80}
PLC_STATUS = {0: "no application", 1: "stopped", 2: "running", 3: "faulty"}


def _flags(value, masks):
    return {name: bool(value & mask) for name, mask in masks.items()}


def parse_unit_status(received_data):
    """Unit status (938914 §4.4) as a dict. The 22 programme-status bytes are segment 153 in the field order of
    938846 §15.2 (G list first), which is what the machine sends.
    """
    r = list(received_data[1:])
    status_masks = {name: 1 << bit for bit, name in enumerate(STATUS_BITS)}
    result = {"current_status": _flags(read_byte(r), status_masks), "status_mask": _flags(read_byte(r), status_masks)}
    g = read_dword(r)
    result["list_of_g_functions"] = {name: g >> bit & 1 for name, bit in G_FUNCTION_BITS.items()}
    result["active_program_number"], result["active_program_index"] = divmod(read_dword(r), 10)  # number × 10 + index
    result["active_block_number"] = read_word(r)
    result["program_error_number"] = read_word(r)
    result["errored_block_number"] = read_word(r)
    result["tool_number"] = read_word(r)
    direction = read_word(r)  # high byte positive, low byte negative; bit 0 X, 1 Y, 2 Z
    result["tool_direction"] = {axis: (direction >> 8 + bit & 1) - (direction >> bit & 1) for bit, axis in enumerate("xyz")}
    result["tool_corrector"] = read_word(r)
    remaining = read_word(r)
    result["list_of_processes_remaining"] = {name: remaining >> bit & 1 for name, bit in PROCESS_BITS.items()}
    panel, nc = read_byte(r), read_byte(r)
    result["operator_panel_status"] = {**_flags(panel, PANEL_BITS), "byte": panel}  # %R3.B
    result["nc_status"] = {**_flags(nc, NC_BITS), "byte": nc}  # %R5.B
    result["nc_mode"] = Mode(read_byte(r))  # %R16.B
    result["machine_error_number"] = read_byte(r)  # %R18.B ERRMACH, "machine mode" in 938914
    result["current_program_number"] = read_word(r)  # %R1A.W PROGCOUR
    result["plc_status"] = PLC_STATUS.get(read_byte(r))
    result["plc_memory_field"] = r  # 16 bytes per 938914, 19 from this machine
    return result


def parse_available_bytes_in_ram(received_data):
    """Read-Memory-Free (938914 §4.15): ``F5 / 77 / status / long word``.

    :raises UnexpectedAdditionalAnswerCode: Not the ``77`` answer
    :raises OperationInProgrammeArea: Status 2
    """
    r = list(received_data)
    if r[1] != 0x77:
        raise UnexpectedAdditionalAnswerCode(0x77, r[1])
    if r[2] == 0x02:
        raise OperationInProgrammeArea()
    return read_dword(r[3:7])


def parse_ladder_variable(variable):
    """Split a ladder variable name into its request fields.

    :param str variable: ``%SNNNN.S`` - symbol ``%M %V %I %Q %R %W %S``, hex logical number, size
        ``.0``-``.7`` (bit), ``.B``, ``.W``, ``.L`` or ``.&``. Index fields (``[i]``) are not supported.
    :returns: (symbol, segment code, logical number, size, index) - index is always ``None``
    :rtype: (str, int, int, str, None)
    :raises ValueError: Invalid symbol, size or logical number (938914 §4.1.3.3 bounds)
    :raises NotImplementedError: Index field present
    """
    symbol = variable[:2]
    if symbol not in LADDER_REQUEST:
        raise ValueError(f"Invalid symbol {symbol!r} in {variable!r}")
    symbol_request = LADDER_REQUEST[symbol]

    if "[" in variable:
        raise NotImplementedError("Index fields are not supported yet")

    parts = variable[2:].split(".")
    if len(parts) != 2 or not parts[0]:
        raise ValueError(f"Invalid ladder variable {variable!r}: expected %SNNNN.S")
    logical_number = int(parts[0], 16)
    bounds = symbol_bounds[symbol]
    if not 0 <= logical_number <= bounds:
        raise ValueError(f"Invalid logical number {logical_number:#x} for {symbol}: must be between 0 and {bounds:#x}")
    low_max = symbol_low_byte_max.get(symbol, 0xFF)
    if logical_number & 0xFF > low_max:
        raise ValueError(f"Invalid logical number {logical_number:#x} for {symbol}: low byte must be <= {low_max:#x}")

    size = parts[1]
    if size not in [str(i) for i in range(8)] + list(ladder_size):
        raise ValueError(f"Invalid size {size!r} in {variable!r}")

    return symbol, symbol_request, logical_number, size, None


def ladder_variable_name(variable):
    """Canonical spelling of a ladder variable, so ``%W0016.B`` and ``%W16.B`` compare equal.

    :rtype: str
    :raises ValueError: Invalid variable
    """
    symbol, _segment, logical_number, size, _index = parse_ladder_variable(variable)
    return f"{symbol}{logical_number:X}.{size}"


def parse_ladder_read_response(response, size, signed=True):
    """Decode a ladder Read-Object answer: code / echoed specific byte / data (938914 §4.1.1).

    :param list[int] response: Answer bytes, starting at the answer code
    :param str size: Size suffix of the variable (``0``-``7``, ``B``, ``W``, ``L``, ``&``)
    :param bool signed: Decode ``.B``/``.W``/``.L`` as signed (938846 §4) or unsigned (I/O bytes, pots)
    :returns: ``bool`` for a bit, ``int`` for ``.B``/``.W``/``.L``, unsigned for ``.&``
    :raises UnexpectedObjectTypeResponse: Echoed specific byte differs from the one sent
    :raises UnexpectedDataLength: Data length does not match the size
    """
    specific = ladder_specific_byte(size)
    if response[1] != specific:
        raise UnexpectedObjectTypeResponse(specific, response[1])
    data = list(response[2:])
    expected = ladder_size.get(size, 1)
    if len(data) != expected:
        raise UnexpectedDataLength(expected, data)
    if size.isdigit():
        return bool(data[0])  # NC answers 0x80 for a set bit (2026-09-22), not 0x01
    # 938914 §2: little-endian; 938846 §4: .B/.W/.L signed by convention, .& an address
    return int.from_bytes(bytes(data), "little", signed=(size != "&" and signed))


def parse_unit_fault_history(response):
    """Read-CPT (938914 §4.6): messages sent and not acknowledged, sent and rejected, received and not acknowledged,
    received and rejected."""
    r = list(response[1:])
    return read_word(r), read_word(r), read_word(r), read_word(r)


def parse_stations_managed_by_master(response):
    """Etat-Station (938914 §4.7): ``(count, [connected, ...])`` by rank; MSB first, as the machine answered."""
    r = list(response[1:])
    count = read_byte(r)
    return count, [(r[i // 8] >> (7 - i % 8)) & 1 == 1 for i in range(count)]


def decode_object(spec, data):
    """Decode NC object bytes per its ``ObjectSpec`` (938914 §2: little-endian, signed).

    :param ObjectSpec spec: Object layout
    :param list[int] data: Object bytes
    :returns: ``Mode``, signed ``int``, ``list[int]`` of signed long words, or the raw bytes
    """
    if spec.kind == "mode":
        return Mode(int.from_bytes(bytes(data), "little"))
    if spec.kind == "int":
        return int.from_bytes(bytes(data), "little", signed=True)
    if spec.kind == "longs":
        return [int.from_bytes(bytes(data[i:i + 4]), "little", signed=True) for i in range(0, len(data), 4)]
    return list(data)


def check_status(request, status, accepted=(0,)):
    """Raise ``FileTransferError`` unless ``status`` is accepted; the meaning comes from ``STATUS_MEANING[request]``."""
    if status not in accepted:
        raise FileTransferError(request, status, STATUS_MEANING[request].get(status, "undocumented status"))
    return status


def parse_upload_segment(response, number):
    """Parse ``6E / status / segment / length / data`` (938914 §4.13.2).

    :param list[int] response: UNI-TE answer bytes, starting at the answer code
    :param int number: Segment number that was asked for
    :returns: (status, data) - status 0 = more data follows, 15 = last segment, file closed by the NC
    :rtype: (int, bytes)
    :raises FileTransferError: Other status, or the answer carries another segment number
    :raises UnexpectedDataLength: Data does not match the announced length
    """
    r = list(response[1:])
    status = check_status("READ_UPLOAD", read_byte(r), (0, 15))
    answered = read_word(r)
    if answered != number:
        raise FileTransferError("READ_UPLOAD", status, f"segment {answered} answered, {number} asked")
    length = read_word(r)
    if len(r) != length:
        raise UnexpectedDataLength(length, r)
    return status, bytes(r)


def parse_directory(response, request):
    """Parse ``F5 / code / status / (index, size) long word pairs`` (938914 §4.16.1, §4.16.2).

    :param list[int] response: UNI-TE answer bytes, starting at the answer code
    :param str request: Request name for the error message
    :returns: (status, programmes) - status 0 = more to read, 15 = list complete, closed by the NC
    :rtype: (int, list[Program])
    :raises OperationInProgrammeArea: Status 2
    :raises FileTransferError: Status 9 "buffer too small" or another rejection
    :raises UnexpectedDataLength: Data is not a whole number of pairs
    """
    r = list(response[2:])
    status = read_byte(r)
    if status == 2:
        raise OperationInProgrammeArea()
    check_status(request, status, (0, 15))
    if len(r) % 8:
        raise UnexpectedDataLength(len(r) - len(r) % 8, r)
    programs = []
    while r:
        index, size = read_dword(r), read_dword(r)
        programs.append(Program.from_index(index, size))
    return status, programs


def parse_download_segment(response, number):
    """Write-Download-Segment answer ``6B / status / segment`` (938914 §4.12.2): status 0 and the echoed number."""
    r = list(response[1:])
    status = check_status("WRITE_DOWNLOAD", read_byte(r))
    answered = read_word(r)
    if answered != number:
        raise FileTransferError("WRITE_DOWNLOAD", status, f"segment {answered} answered, {number} sent")
    return status
