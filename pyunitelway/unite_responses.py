from pyunitelway.constants import DELETE_STATUS, DOWNLOAD_STATUS, FILE_STATUS, LADDER_REQUEST
from pyunitelway.errors import (
    FileTransferError,
    OperationInProgrammeArea,
    UnexpectedAdditionalAwnserCode,
    UnexpectedDataLength,
    UnexpectedObjectTypeResponse,
)
from pyunitelway.num_constants import Mode, Program, symbol_bounds, symbol_low_byte_max, ladder_size
from pyunitelway.utils import read_byte, read_dword, read_word, read_bytes, read_int, ladder_specific_byte


def parse_mirror_result(received_data, sent_data):
    """Parse the ``MIRROR`` response.

    During a ``MIRROR``, the sender send an amount of bytes (``sent_data``), and the receiver must send the same bytes (``received_data``).
    This function check if the sent and the received data are the same.

    :param list[int] received_data: Received data in the response
    :param list[int] sent_data: Sent data during the request

    :returns: ``True`` if the sent and received data are the same
    :rtype: bool
    """
    return received_data == sent_data


def parse_unit_identification(received_data):
    """Parse the ``Unit Identification`` request.
    The response contains "product_type", "subtype", "product_version" and "text".

    :param list[int] received_data: Received data in the response

    :returns: Unit identification dict containing "product_type_code", "product_type", "subtype",
        "product_version" (index from the high half-byte) and "text".
    :rtype: dict[str: Any]
    """
    resp = list(received_data)

    data = {}

    # 938914 §4.3; this UC SII answers 102 ("NUM 1040") with text NUM1060S2UCS2 - trust ``text``
    product_type = resp[1]
    data["product_type_code"] = product_type
    match product_type:
        case 100:
            data["product_type"] = "NUM 1060"
        case 101:
            data["product_type"] = "NUM 1060 Series II"
        case 102:
            data["product_type"] = "NUM 1040"
        case 103:
            data["product_type"] = "NUM 1060-7"
        case _:
            data["product_type"] = f"unknown ({product_type})"

    subtype = chr(resp[2])
    data["subtype"] = subtype

    # 938914 §4.3: the first half-byte is the version index (H'30' -> index 3)
    data["product_version"] = resp[3] >> 4

    # 938914 §4.3: ASCII string beginning with a length byte
    length = resp[4]
    text = resp[5:5 + length]
    text = ''.join([chr(i) for i in text])
    data["text"] = text

    return data


def parse_unit_status(received_data):
    """Parse the ``Unit Status Data`` answer (938914 §4.4; segment 153 for the 22 programme-status bytes).

    :param list[int] received_data: Received data in the response

    :returns: Unit status dict. ``tool_direction`` holds ``+1`` / ``-1`` / ``0`` per axis,
        ``list_of_g_functions`` one ``0``/``1`` per G function, ``operator_panel_status`` and
        ``nc_status`` the named bits of ``%R3.B`` / ``%R5.B`` (938846 §3.8.1) plus the raw ``byte``,
        ``machine_error_number`` the ``%R18.B`` ERRMACH byte, ``plc_memory_field`` every byte after it.
    :rtype: dict[str: Any]
    """
    r = list(received_data)

    _answer_code = read_byte(r)

    result = dict()

    current_status = dict()
    current_status_bits = read_byte(r)
    current_status["system_inoperative"] = (current_status_bits & 0x01) != 0
    current_status["recoverable_error"] = (current_status_bits & 0x02) != 0
    current_status["unrecoverable_error"] = (current_status_bits & 0x04) != 0
    current_status["auxiliary_power_source"] = (current_status_bits & 0x08) != 0
    current_status["system_reset"] = (current_status_bits & 0x10) != 0
    current_status["critical_operation"] = (current_status_bits & 0x20) != 0
    current_status["halt"] = (current_status_bits & 0x40) != 0
    current_status["local_mode"] = (current_status_bits & 0x80) != 0
    result["current_status"] = current_status

    status_mask = dict()
    status_mask_bits = read_byte(r)
    status_mask["system_inoperative"] = (status_mask_bits & 0x01) != 0
    status_mask["recoverable_error"] = (status_mask_bits & 0x02) != 0
    status_mask["unrecoverable_error"] = (status_mask_bits & 0x04) != 0
    status_mask["auxiliary_power_source"] = (status_mask_bits & 0x08) != 0
    status_mask["system_reset"] = (status_mask_bits & 0x10) != 0
    status_mask["critical_operation"] = (status_mask_bits & 0x20) != 0
    status_mask["halt"] = (status_mask_bits & 0x40) != 0
    status_mask["local_mode"] = (status_mask_bits & 0x80) != 0
    result["status_mask"] = status_mask

    # segment 153: field order per 938846 §15.2 (G list first), sizes per 938914 §4.1.3 (todo.md A12)
    list_of_g_functions = dict()
    list_of_g_functions_bits = read_dword(r)
    # bit numbers per 938914 segment 153; bits 5, 22, 26 and 29 are not assigned
    g_functions = {
        "G00": 0,  # Linearinterpolation im Eilang
        "G01": 1,  # Linearinterpolation mit programmiertem Vorschub
        "G02": 2,  # Kreisinterpolation im Uhrzeigersinn mit programmiertem Vorschub
        "G03": 3,  # Kreisinterpolation gegen den Uhrzeigersinn mit programmiertem Vorschub
        "G04": 4,  # Programmierte Verweilzeit
        "G38": 6,  # ?
        "G09": 7,  # Genauhalt bei Satzende vor Übergang zum nächsten Satz
        "G17": 8,  # Wahl der Arbeitsebene XY
        "G19": 9,  # Wahl der Arbeitsebene YZ
        "G18": 10,  # Wahl der Arbeitsebene ZX
        "G90": 11,  # Absolutwertprogrammierung bezogen auf Werkstücknullpunkt
        "G91": 12,  # Kettenmaßprogrammierung bezogen auf den Startpunkt des Satzes
        "G70": 13,  # Programmierung in Zoll
        "G52": 14,  # Absolutwertprogrammierung der Verfahrwege bezogen auf den Maschinennullpunkt
        "G22": 15,  # ?
        "G40": 16,  # Aufhebung der Radiuskorrektur
        "G41": 17,  # Radiuskorrektur links von der Kontur
        "G42": 18,  # Radiuskorrektur rechts von der Kontur
        "G53": 19,  # Aufhebung der Nullpunktverschiebung NP-1 und NPV-1
        "G54": 20,  # Übernahme der Nullpunktverschiebung NP-1 und NPV-1
        "G29": 21,  # 3D-Werkzeugkorrektur (3 Achsen oder 5 Achsen)
        "G93": 23,  # Vorschub in Vorschub/Weg
        "G94": 24,  # Vorschub in Millimeter, Zoll oder Grad/Minute
        "G95": 25,  # Vorschub in Millimeter oder Zoll/Umdrehung
        "G96": 27,  # ?
        "G97": 28,  # Spindeldrehzahl in Umdrehungen pro Minute
        "G20": 30,  # ?
        "G21": 31,  # ?
    }

    for key in g_functions.keys():
        value = g_functions[key]
        list_of_g_functions[key] = (list_of_g_functions_bits & (1 << value)) >> value
    result["list_of_g_functions"] = list_of_g_functions

    # programme number x 10 + index (90010 = %9001; inferred from two captures)
    active_program = read_dword(r)
    result["active_program_number"] = active_program // 10
    result["active_program_index"] = active_program % 10
    result["active_block_number"] = read_word(r)
    result["program_error_number"] = read_word(r)
    result["errored_block_number"] = read_word(r)
    result["tool_number"] = read_word(r)

    # 938914 seg 153: high byte = positive, low byte = negative; bit 0 X, 1 Y, 2 Z
    tool_direction = dict()
    tool_direction_bits = read_word(r)
    for axis, bit in (("x", 0), ("y", 1), ("z", 2)):
        positive = (tool_direction_bits >> (8 + bit)) & 1
        negative = (tool_direction_bits >> bit) & 1
        tool_direction[axis] = positive - negative
    result["tool_direction"] = tool_direction

    result["tool_corrector"] = read_word(r)

    list_of_processes_remaining = dict()
    list_of_processes_remaining_bits = read_word(r)
    processes_remaining = {
        "function G79": 0,
        "end of external movement": 1,
        "encoded M function": 2,
        "M post-function": 3,
        "function G04": 4,
        "function G09": 5,
        "execution of a circle": 6,
        "execution of a line": 7,
        "JOG": 8,
        "FEED STOP": 11,
        "M pre-function": 13,
        "T function": 15
    }
    for key in processes_remaining.keys():
        value = processes_remaining[key]
        list_of_processes_remaining[key] = (list_of_processes_remaining_bits & (1 << value)) >> value
    result["list_of_processes_remaining"] = list_of_processes_remaining

    # 938914 §4.4 names the next bytes by their ladder images; bit meanings from 938846 §3.8.1
    operator_panel_status_bits = read_byte(r)  # %R3.B
    result["operator_panel_status"] = {
        "cnc_reset_in_progress": (operator_panel_status_bits & 0x01) != 0,  # E_RAZ
        "cycle_stop": (operator_panel_status_bits & 0x02) != 0,  # E_ARUS
        "cycle_in_progress": (operator_panel_status_bits & 0x04) != 0,  # E_CYCLE
        "axis_recall": (operator_panel_status_bits & 0x08) != 0,  # E_RAX
        "emergency_retract": (operator_panel_status_bits & 0x10) != 0,  # E_DGURG
        "cnc_fault": (operator_panel_status_bits & 0x40) != 0,  # E_DEFCN
        "program_stop": (operator_panel_status_bits & 0x80) != 0,  # E_OPER (M00 / M01)
        "byte": operator_panel_status_bits,
    }
    nc_status_bits = read_byte(r)  # %R5.B
    result["nc_status"] = {
        "cnc_ready": (nc_status_bits & 0x01) != 0,  # E_CNPRET
        "active_program": (nc_status_bits & 0x02) != 0,  # E_PROG: a part programme is executing
        "drip_feed_ready": (nc_status_bits & 0x20) != 0,  # E_PPP
        "transparent_mode": (nc_status_bits & 0x80) != 0,  # E_TRANSP
        "byte": nc_status_bits,
    }
    result["nc_mode"] = Mode(read_byte(r))  # %R16.B
    # %R18.B ERRMACH (938846 §3.8.1.10); 938914 §4.4 calls it "machine mode"
    result["machine_error_number"] = read_byte(r)
    result["current_program_number"] = read_word(r)  # %R1A.W PROGCOUR
    plc_status = read_byte(r)
    if plc_status == 0:
        result["plc_status"] = "no application"
    elif plc_status == 1:
        result["plc_status"] = "stopped"
    elif plc_status == 2:
        result["plc_status"] = "running"
    elif plc_status == 3:
        result["plc_status"] = "faulty"

    # 938914 §4.4: 16 bytes of the PLC memory field the ladder designates; this machine sends 19
    result["plc_memory_field"] = list(r)
    return result


def parse_available_bytes_in_ram(received_data):
    """Parse the ``Read-Memory-Free`` answer (938914, section 4.15).

    Answer layout: answer code ``H'F5'`` / additional answer code ``H'77'`` /
    status (1 byte) / number of available bytes (1 long word, low byte first).

    :param list[int] received_data: UNI-TE answer bytes, starting at the answer code

    :returns: Available bytes in RAM
    :rtype: int

    :raises UnexpectedAdditionalAwnserCode: The additional answer code is not ``H'77'``
    :raises OperationInProgrammeArea: Status ``H'02'``: operation in the programme area
    """
    r = list(received_data)

    if r[1] != 0x77:
        raise UnexpectedAdditionalAwnserCode(0x77, r[1])

    status = r[2]
    if status == 0x02:
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


def parse_write_result(response):
    """Parse a write answer: ``0xFE`` is the positive report (938914 §4.1.2).

    :param list[int] response: Response **with** UNI-TE response code

    :returns: ``True`` if response code is ``0xFE``
    :rtype: bool    
    """
    return response[0] == 0xFE


def parse_shutdown_result(response):
    """Parse the PCNC ``SHUTDOWN`` answer (938928 §10.4.10).

    Answer layout: answer code ``H'F5'`` / additional answer code ``H'96'`` / status
    (``H'00'`` shutdown started, ``H'1C'`` refused).

    :param list[int] response: Response **with** UNI-TE response code

    :returns: ``True`` if the status byte is ``H'00'``
    :rtype: bool
    """
    return response[2] == 0x00


def parse_unit_fault_history(response):
    """Parse get_unit_fault_history response

    :param list[int] response: Response **with** UNI-TE response code

    :returns: quadrouple of:
        * number of messages sent and not acknowledged,
        * number of messages sent and rejected,
        * number of messages received and not acknowledged,
        * number of messages received and rejected.
    :rtype: (int, int, int, int)
    """
    resp = list(response)
    r = resp[1:]
    return read_word(r), read_word(r), read_word(r), read_word(r)


def parse_stations_managed_by_master(response):
    """Parse get_stations_managed_by_master response

    :param list[int] response: Response **with** UNI-TE response code

    :returns: number of stations managed and their status (connected/unconnected as list of bool,
        index = rank; on the Darmstadt bus rank 0 is the single managed slave, link address 1)
    :rtype: (int, list[bool])
    """
    resp = list(response)
    r = resp[1:]
    num_stations = read_byte(r)
    # 938914 §4.7: 1 bit per station, rank = address; MSB-first (machine answered D3 01 80 as sole slave)
    status = [(r[i // 8] >> (7 - i % 8)) & 1 == 1 for i in range(num_stations)]
    return num_stations, status


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


def check_file_status(request, status, accepted=(0,)):
    """Raise ``FileTransferError`` unless ``status`` is one of ``accepted`` (938914 §4.13, §4.16)."""
    if status not in accepted:
        raise FileTransferError(request, status, FILE_STATUS.get(status, "undocumented status"))
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
    status = check_file_status("READ_UPLOAD", read_byte(r), (0, 15))
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
    check_file_status(request, status, (0, 15))
    if len(r) % 8:
        raise UnexpectedDataLength(len(r) - len(r) % 8, r)
    programs = []
    while r:
        index, size = read_dword(r), read_dword(r)
        programs.append(Program.from_index(index, size))
    return status, programs


def check_download_status(request, status, accepted=(0,)):
    """Raise ``FileTransferError`` unless ``status`` is one of ``accepted`` (938914 §4.12, ``DOWNLOAD_STATUS``)."""
    if status not in accepted:
        raise FileTransferError(request, status, DOWNLOAD_STATUS[request].get(status, "undocumented status"))
    return status


def parse_download_open(response):
    """Parse ``6A / status`` (938914 §4.12.1); only status 0 opened the file (1 = it exists, nothing is overwritten).

    :returns: 0
    :raises FileTransferError: Any other status
    """
    return check_download_status("OPEN_DOWNLOAD", response[1])


def parse_download_segment(response, number):
    """Parse ``6B / status / segment`` (938914 §4.12.2).

    :param int number: Segment number that was sent
    :returns: 0
    :raises FileTransferError: Other status, or the answer echoes another segment number
    """
    r = list(response[1:])
    status = check_download_status("WRITE_DOWNLOAD", read_byte(r))
    answered = read_word(r)
    if answered != number:
        raise FileTransferError("WRITE_DOWNLOAD", status, f"segment {answered} answered, {number} sent")
    return status


def parse_download_close(response):
    """Parse ``6C / status`` (938914 §4.12.3): 0 = stored, 4 = nothing was open; 11 = the NC deleted the file.

    :returns: 0 or 4
    :raises FileTransferError: 11 and every other status
    """
    return check_download_status("CLOSE_DOWNLOAD", response[1], (0, 4))


def parse_delete_file(response):
    """Parse ``F5 / 76 / status`` (938914 §4.14) after ``check_specific_answer``; only status 0 deleted the file.

    :returns: 0
    :raises FileTransferError: 2 (operation in the programme area), 5 (no such file), 10 (programme executing)
    """
    status = response[2]
    if status != 0:
        raise FileTransferError("DELETE_FILE", status, DELETE_STATUS.get(status, "undocumented status"))
    return status
