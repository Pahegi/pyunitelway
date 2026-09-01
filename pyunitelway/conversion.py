"""UNI-TELWAY response unwrapping functions.

Unwraps a received buffer down to the UNI-TE response bytes:
UNI-TELWAY frame ``<DLE><STX><addr><length><data><BCC>`` -> X-WAY NPDU -> UNI-TE report.

References:

* Schneider UNI-TELWAY reference manual 35000789: link layer frame and
  ``<DLE>`` transparency (sections 3.5, 3.12), NPDU format (section 4.2)
* NUM 1060 "Use of the UNI-TE protocol" 938914: report format (section 2.2)
"""

from .errors import BadUnitelwayChecksum, MalformedUnitelwayResponse, RefusedUnitelwayMessage, UniteRequestFailed
from .utils import check_unitelway, compute_bcc, compute_response_length, delete_dle


def unitelway_to_xway(response):
    """Unwrap the X-WAY message from a UNI-TELWAY frame.

    The input must be exactly one **de-duplicated** UNI-TELWAY frame
    (``<DLE><STX><addr><length><data><BCC>``): 4 header bytes, then the data
    (the X-WAY NPDU), then the checksum.

    :param list[int] response: De-duplicated UNI-TELWAY frame

    :returns: X-WAY message (NPDU)
    :rtype: list[int]
    """
    return response[4:-1]


def xway_to_unite(response):
    """Unwrap the UNI-TE message from an X-WAY message.

    The first NPDU byte is the service code (manual 35000789, section 4.2):

    * ``0x20``: standard service format — code + 5 address bytes (``Net``,
      ``Sta``, ``Gate``, ``Ext1``, ``Ext2``), then the UNI-TE bytes
    * ``0x00``: simplified service format — code only, then the UNI-TE bytes
    * ``0x22``: refused UNI-TELWAY message
    * anything else is reserved, and treated as erroneous

    :param list[int] response: X-WAY message

    :returns: UNI-TE message
    :rtype: list[int]

    :raises RefusedUnitelwayMessage: The X-WAY service code is ``0x22``
    :raises MalformedUnitelwayResponse: The X-WAY service code is reserved/unknown
    """
    code = response[0]
    if code == 0x22:
        raise RefusedUnitelwayMessage()
    if code == 0x20:
        return response[6:]
    if code == 0x00:
        return response[1:]
    raise MalformedUnitelwayResponse(f"unknown X-WAY service code 0x{code:02X}")


def unwrap_unite_response(response):
    """Unwrap the UNI-TE response from a received buffer.

    It:

    * locates the end of the frame from the ``<length>`` field, so trailing
      bytes in the receive buffer (e.g. the master's next ``<DLE><ENQ><addr>``
      polling sequence) are ignored
    * checks the frame checksum — on the raw bytes, because the BCC is
      computed after ``<DLE>`` padding (manual 35000789, section 3.5)
    * deletes the duplicated ``<DLE>``'s
    * unwraps the X-WAY message, then the UNI-TE message
    * checks the UNI-TE answer code

    :param list[int] response: Received bytes, starting at the header ``<DLE>``

    :returns: UNI-TE bytes
    :rtype: list[int]

    :raises MalformedUnitelwayResponse: The buffer does not hold one complete, well-formed frame
    :raises BadUnitelwayChecksum: The frame checksum does not match
    :raises RefusedUnitelwayMessage: The X-WAY service code is ``0x22``
    :raises UniteRequestFailed: The UNI-TE answer code is ``0xFD`` (negative report)
    """
    frame = response[:compute_response_length(response)]

    if not check_unitelway(frame):
        raise BadUnitelwayChecksum(compute_bcc(frame[:-1]), frame[-1])

    frame = delete_dle(frame)

    xway_bytes = unitelway_to_xway(frame)

    unite_bytes = xway_to_unite(xway_bytes)

    # Negative report (938914, section 2.2)
    if unite_bytes[0] == 0xFD:
        raise UniteRequestFailed()

    return unite_bytes
