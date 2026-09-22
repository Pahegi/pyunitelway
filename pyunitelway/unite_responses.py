from pyunitelway.constants import LADDER_REQUEST
from pyunitelway.errors import UnexpectedAdditionalAwnserCode, OperationInProgrammeArea
from pyunitelway.num_constants import Mode, symbol_bounds
from pyunitelway.utils import read_byte, read_dword, read_word, read_bytes, read_int


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

    # 938914 §4.3 table. The NUM 1060 Series II UC SII in Darmstadt answers 102 with the text
    # "NUM1060S2UCS2" (captured 2026-09-22), so trust ``text`` over this mapping.
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
        ``list_of_g_functions`` one ``0``/``1`` per G function.
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

    result["active_program_number"] = read_dword(r)  # TODO result is wrong
    result["active_block_number"] = read_word(r)  # TODO result is wrong
    result["program_error_number"] = read_word(r)
    result["errored_block_number"] = read_word(r)
    result["tool_number"] = read_word(r)

    # 938914 segment 153: the axis bit (0 = X, 1 = Y, 2 = Z) is set in the high byte for a
    # positive direction and in the low byte for a negative one -> +1 / -1 / 0 per axis
    tool_direction = dict()
    tool_direction_bits = read_word(r)
    for axis, bit in (("x", 0), ("y", 1), ("z", 2)):
        positive = (tool_direction_bits >> (8 + bit)) & 1
        negative = (tool_direction_bits >> bit) & 1
        tool_direction[axis] = positive - negative
    result["tool_direction"] = tool_direction

    result["tool_corrector"] = read_word(r)

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

    result["operator_panel_status"] = read_byte(r)
    result["nc_status"] = read_byte(r)
    result["nc_mode"] = Mode(read_byte(r))
    result["machine_mode"] = read_byte(r)
    result["current_program_number"] = read_word(r)
    plc_status = read_byte(r)
    if plc_status == 0:
        result["plc_status"] = "no application"
    elif plc_status == 1:
        result["plc_status"] = "stopped"
    elif plc_status == 2:
        result["plc_status"] = "running"
    elif plc_status == 3:
        result["plc_status"] = "faulty"

    result["plc_memory_field"] = read_bytes(r, 16)
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


def parse_ladder_variable(variable, debug=0):
    """Parses a ladder variable into symbol, symbol request code, logical number, size and index.
    Index fields are not supported yet.

    :param str variable: Ladder variable name in the format ``%SNNNN.S[I]`` with symbol S, logical number NNNN, size S and optional index I in square brackets.

        Possible values for symbol:

        * %M - saved common internal variables
        * %V - saved common variables
        * %I - I/O interface read variables
        * %Q - I/O interface write variables
        * %R - CNC I/O interface read variables
        * %W - CNC I/O interface write variables
        * %S - common word variables
        * %Y - local variables (not supported over UNITE)

        Possible values for size:

        * .n - bit (n = 0 to 7)
        * .B - signed integer (1 byte)
        * .W - signed integer (2 bytes, MSB at n, LSB at n+1)
        * .L - signed integer (4 bytes, MSB at n, LSB at n+3)
        * .& - address (4 bytes)

    :param int debug: :doc:`Debug mode </debug_levels>`
    :returns: (symbol, symbol request code, logical number, size, index)
    :rtype: Any

    :raises ValueError: Invalid symbol
    :raises ValueError: Invalid logical number
    :raises ValueError: Invalid size
    """
    print("client.py - parse_ladder_variable func: " + "Parsing ladder variable", flush=True)

    symbol = variable[:2]
    symbol_request = LADDER_REQUEST[symbol]
    if symbol not in ["%M", "%V", "%I", "%Q", "%R", "%W", "%S"]:
        raise ValueError("Invalid symbol")

    logical_number = int(variable[2:].split(".")[0], 16)
    bounds = symbol_bounds[symbol]
    if logical_number > bounds or logical_number < 0:
        raise ValueError(f"Invalid logical number {logical_number} for symbol {symbol}: must be between 0 and {bounds}")

    size = variable.split(".")[1][0]
    if size not in ["0", "1", "2", "4", "5", "6", "7", "B", "W", "L", "&"]:
        raise ValueError("Invalid size")

    # TODO handle index field
    if "[" in variable:
        raise NotImplementedError("Index fields are not supported yet")

    if debug > 2: print("symbol: " + symbol + ", logical_number: " + str(logical_number) + ", size: " + size + ", symbol request code: " + hex(symbol_request), flush=True)

    return symbol, symbol_request, logical_number, size, None


def parse_ladder_read_response(response, size):
    """Parse ladder read response
    Returns the value of the ladder variable as an integer or a boolean if the size is a bit.

    :param list[int] response: Response **with** UNI-TE response code
    :param str size: Size value of the ladder variable (``n`` in range [0,7], ``B``, ``W``, ``L``, ``&``)

    :returns: Value of the ladder variable
    :rtype: Union[int, bool]
    """
    resp = list(response)
    resp = resp[2:]  # first two characters are response code and object address
    if "0" <= size <= "7":
        read_byte(resp)
        return (resp[0] >> int(size)) & 1
    else:
        return read_int(resp[1:])


def parse_write_result(response):
    """Parse ``WRITE_XXX_XXX`` response.

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
    # 938914 §4.7: 1 bit per station, rank = station address. The manual does not give the bit
    # order; the NUM 1060 answered D3 01 80 while this client was connected as link address 1
    # (2026-09-22), so the bits run from the MSB: station i is bit 7 - i % 8 of byte i // 8.
    status = [(r[i // 8] >> (7 - i % 8)) & 1 == 1 for i in range(num_stations)]
    return num_stations, status

