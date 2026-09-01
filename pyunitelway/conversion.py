"""UNI-TELWAY response unwrapping: frame -> X-WAY NPDU -> UNI-TE report.

References: Schneider 35000789 (frame §3.5/§3.12, NPDU §4.2), NUM 938914 (report §2.2).
"""

from .errors import BadUnitelwayChecksum, MalformedUnitelwayResponse, RefusedUnitelwayMessage, UniteRequestFailed
from .utils import check_unitelway, compute_bcc, compute_response_length, delete_dle


def unitelway_to_xway(response):
    """Unwrap the X-WAY NPDU from one de-duplicated UNI-TELWAY frame.

    :param list[int] response: De-duplicated frame ``<DLE><STX><addr><length><data><BCC>``
    :returns: X-WAY message (NPDU)
    :rtype: list[int]
    """
    return response[4:-1]


def xway_to_unite(response):
    """Unwrap the UNI-TE message from an X-WAY message.

    Service codes per 35000789 §4.2: ``0x20`` standard (code + 5 address bytes),
    ``0x00`` simplified (code only), ``0x22`` refused, others reserved.

    :param list[int] response: X-WAY message
    :returns: UNI-TE message
    :rtype: list[int]
    :raises RefusedUnitelwayMessage: Service code ``0x22``
    :raises MalformedUnitelwayResponse: Reserved/unknown service code
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

    Truncates the buffer to one frame (trailing poll bytes ignored), checks the
    BCC on the raw padded bytes (35000789 §3.5), de-duplicates ``<DLE>``'s, then
    unwraps X-WAY and UNI-TE.

    :param list[int] response: Received bytes, starting at the header ``<DLE>``
    :returns: UNI-TE bytes
    :rtype: list[int]
    :raises MalformedUnitelwayResponse: No complete, well-formed frame
    :raises BadUnitelwayChecksum: Checksum mismatch
    :raises RefusedUnitelwayMessage: X-WAY service code ``0x22``
    :raises UniteRequestFailed: UNI-TE answer code ``0xFD`` (negative report)
    """
    frame = response[:compute_response_length(response)]

    if not check_unitelway(frame):
        raise BadUnitelwayChecksum(compute_bcc(frame[:-1]), frame[-1])

    frame = delete_dle(frame)

    xway_bytes = unitelway_to_xway(frame)

    unite_bytes = xway_to_unite(xway_bytes)

    # negative report (938914 §2.2)
    if unite_bytes[0] == 0xFD:
        raise UniteRequestFailed()

    return unite_bytes
