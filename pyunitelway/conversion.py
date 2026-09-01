"""Conversion and response parsing functions.
"""

from pyunitelway.num_constants import Mode, symbol_bounds
from .constants import *
from .errors import BadUnitelwayChecksum, RefusedUnitelwayMessage, UniteRequestFailed, \
    OperationInProgrammeArea, UnexpectedAdditionalAwnserCode
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


def main():
    """Main function used for tests.

    Test parsing of ``READ_IO_CHANNEL`` response: ``[0x73, 0, 0, 1, 0, 1, 0, 2, 1, 0, 1, 1, 0, 0, 1, 0, 0xBC, 0]``
    """


if __name__ == "__main__":
    main()
