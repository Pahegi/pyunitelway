"""Conversion and response parsing functions.
"""

from pyunitelway.num import Mode, symbol_bounds
from .constants import *
from .errors import BadUnitelwayChecksum, RefusedUnitelwayMessage, UniteRequestFailed, \
    OperationInProgrammeArea
from .utils import check_unitelway, compute_bcc, delete_dle, read_byte, \
    read_word, read_dword, read_bytes, read_int


def keep_response_bytes(response):
    """Only keep UNI-TELWAY response bytes.

    When we receive a response, we get a lots of bytes, starting with the UNI-TELWAY response. This function only keeps
    the response bytes.
    
    :param list[int] response: Received response

    :returns: UNI-TELWAY bytes
    :rtype: list[int]
    """
    return response[:4] + [value for index, value in enumerate(response[4:]) if not value == response[4 + index - 1] == DLE]


def unwrap_unitelway_response(response):
    """Delete the duplicated ``<DLE>``'s in a UNI-TELWAY response.

    See ``utils.delete_dle`` for ``<DLE>`` duplication rules.

    :param list[int] response: UNI-TELWAY response
    
    :returns: UNI-TELWAY response without duplicated ``<DLE>``'s
    :rtype: list[int]
    """
    without_dle = delete_dle(response)

    length = without_dle[3]
    return without_dle[:4 + length + 1]


def unitelway_to_xway(response):
    """Unwrap the X-WAY message from a UNI-TELWAY response.

    This function just returns the X-WAY bytes, without checking anything.

    :param list[int] response: UNI-TELWAY response

    :returns: X-WAY message
    :rtype: list[int]
    """
    return response[4:-1]


def xway_to_unite(response):
    """Unwrap the UNI-TE message from a X-WAY message.

    This function also checks if the X-WAY message has been received.

    The X-WAY message is received if the type code (first response byte)
    is not ``0x22``, which means a refused UNI-TELWAY message.

    :param list[int] response: X-WAY response

    :returns: UNI-TE message
    :rtype: list[int]

    :raises RefusedUnitelwayMessage: The X-WAY type code (first byte) is ``0x22``. It means a refused UNI-TELWAY message
    """
    # Type code = 0x22 => X-WAY refused
    if response[0] == 0x22:
        raise RefusedUnitelwayMessage()

    return response[6:]


def unwrap_unite_response(response):
    """Unwrap the UNI-TE response from a received response.

    This function uses all the functions defined above, so don't use them alone.
    It:

    * only keeps UNI-TELWAY message bytes
    * checks the message using the checksum
    * unwrap the X-WAY message
    * unwrap the UNI-TE message
    * check the UNI-TE response code
    * only returns UNI-TE bytes

    :param list[int] response: Received response
    
    :returns: UNI-TE bytes
    :rtype: list[int]

    :raises BadUnitelwayChecksum, UniteRequestFailed: Bad checksum, or received ``0xFD`` (which means UNI-TE request fail)
    :raises UniteRequestFailed: Received ``0xFD`` (which means UNI-TE request fail)
    """
    if not check_unitelway(response):
        # print("Unitelway check failed!", flush=True)
        raise BadUnitelwayChecksum(response[-1], compute_bcc(response[:-1]))
    # print("Unitelway check succeeded!", flush=True)

    # print('[{}]'.format(','.join(f'{i:02X}'for i in response)), flush=True)
    response = keep_response_bytes(response)
    # print('[{}]'.format(','.join(f'{i:02X}'for i in response)), flush=True)

    # unitelway_bytes = unwrap_unitelway_response(response)
    unitelway_bytes = response

    xway_bytes = unitelway_to_xway(unitelway_bytes)

    unite_bytes = xway_to_unite(xway_bytes)

    code = unite_bytes[0]
    # Fail
    if code == 0xFD:
        raise UniteRequestFailed()

    return unite_bytes


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

    :returns: Unit identification dict containing "product_type", "subtype", "product_version" and "text".
    :rtype: dict[str: Any]
    """
    resp = delete_dle(received_data)

    data = {}

    product_type = resp[1]
    match product_type:
        case 100:
            data["product_type"] = "NUM 1060"
        case 101:
            data["product_type"] = "NUM 1060 Series II"
        case 102:
            data["product_type"] = "NUM 1040"
        case 103:
            data["product_type"] = "NUM 1060-7"

    subtype = chr(resp[2])
    data["subtype"] = subtype

    product_version = resp[3]
    data["product_version"] = product_version

    text = resp[5:]
    text = ''.join([chr(i) for i in text])
    data["text"] = text

    return data


def parse_unit_status(received_data):
    """Parse the ``Unit Status Data`` request.

    :param list[int] received_data: Received data in the response

    :returns: Unit status dict
    :rtype: dict[str: Any]
    """
    r = delete_dle(received_data)

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

    tool_direction = dict()
    tool_direction_bits = read_word(r)
    tool_direction["x"] = tool_direction_bits & 0x01
    tool_direction["y"] = tool_direction_bits & 0x02
    tool_direction["z"] = tool_direction_bits & 0x04
    result["tool_direction"] = tool_direction

    result["tool_corrector"] = read_word(r)

    list_of_g_functions = dict()
    list_of_g_functions_bits = read_dword(r)
    g_functions = {
        "G00": 0,  # Linearinterpolation im Eilang
        "G01": 1,  # Linearinterpolation mit programmiertem Vorschub
        "G02": 2,  # Kreisinterpolation im Uhrzeigersinn mit programmiertem Vorschub
        "G03": 3,  # Kreisinterpolation gegen den Uhrzeigersinn mit programmiertem Vorschub
        "G04": 4,  # Programmierte Verweilzeit
        "G38": 5,  # ?
        "G09": 6,  # Genauhalt bei Satzende vor Übergang zum nächsten Satz
        "G17": 7,  # Wahl der Arbeitsebene XY
        "G19": 8,  # Wahl der Arbeitsebene ZX
        "G18": 9,  # Wahl der Arbeitsebene YZ
        "G90": 10,  # Absolutwertprogrammierung bezogen auf Werkstücknullpunkt
        "G91": 11,  # Kettenmaßprogrammierung bezogen auf den Startpunkt des Satzes
        "G70": 12,  # Programmierung in Zoll
        "G52": 13,  # Absolutwertprogrammierung der Verfahrwege bezogen auf den Maschinennullpunkt
        "G22": 14,  # ?
        "G40": 15,  # Aufhebung der Radiuskorrektur
        "G41": 16,  # Radiuskorrektur links von der Kontur
        "G42": 17,  # Radiuskorrektur rechts von der Kontur
        "G53": 18,  # Aufhebung der Nullpunktverschiebung NP-1 und NPV-1
        "G54": 19,  # Übernahme der Nullpunktverschiebung NP-1 und NPV-1
        "G29": 20,  # 3D-Werkzeugkorrektur (3 Achsen oder 5 Achsen)
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
    """Parse the ``Get available bytes in RAM`` request.

    :param list[int] received_data: Received data in the response

    :returns: Available bytes in RAM
    :rtype: int

    :raises OperationInProgrammeArea: Operation in the programme area
    """
    r = delete_dle(received_data)

    status = r[2]
    if status == 0x02:
        raise OperationInProgrammeArea()

    return read_word(r[-4:])


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
    resp = delete_dle(response)
    resp = resp[2:]  # first two characters are response code and object address
    if chr(0) <= size <= chr(7):
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


def main():
    """Main function used for tests.

    Test parsing of ``READ_IO_CHANNEL`` response: ``[0x73, 0, 0, 1, 0, 1, 0, 2, 1, 0, 1, 1, 0, 0, 1, 0, 0xBC, 0]``
    """


if __name__ == "__main__":
    main()
