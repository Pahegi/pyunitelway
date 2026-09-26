class UnitelwayError(Exception):
    def __init__(self, message):
        super().__init__(message)


class BadUnitelwayChecksum(UnitelwayError):
    def __init__(self, expected, got):
        super().__init__(f"Bad UNI-TELWAY checksum: expected 0x{expected:02X}, got 0x{got:02X}")


class MalformedUnitelwayResponse(UnitelwayError):
    def __init__(self, message):
        super().__init__(f"Malformed UNI-TELWAY response: {message}")


class RefusedUnitelwayMessage(UnitelwayError):
    def __init__(self):
        super().__init__("Refused UNI-TELWAY message (X-WAY code = 0x22). See Notion for more details")


class UniteRequestFailed(UnitelwayError):
    def __init__(self):
        super().__init__("UNI-TE request failed (response: 0xFD). Possible causes: bad request code, bad values, ... See Notion for more details")


class BadReadBitsNumberParam(ValueError):
    def __init__(self, number):
        super().__init__(f"Number has to be a multiple of 8 (it is {number})")


class UnexpectedUniteResponse(UnitelwayError):
    def __init__(self, expected, got):
        super().__init__(f"Expected 0x{expected:X}, got 0x{got:X}. Check that the UnitelwayClient's link address is not used by another slave station")


class UnexpectedAdditionalAwnserCode(UnitelwayError):
    def __init__(self, expected, got):
        super().__init__(f"Expected 0x{expected:X}, got 0x{got:X}")


class UnexpectedObjectTypeResponse(UnexpectedUniteResponse):
    def __init__(self, expected, got):
        super().__init__(expected, got)


class OperationInProgrammeArea(UnitelwayError):
    def __init__(self):
        super().__init__("Request rejected: operation in the programme area")


class NoPollingWindow(UnitelwayError):
    def __init__(self, address, timeout):
        super().__init__(
            f"The master never polled link address 0x{address:02X} within {timeout} s. "
            "Check the adapter IP/port and that the NUM is powered on; run example/listen.py "
            "to see which link addresses the master actually polls"
        )


class UnexpectedDataLength(UnitelwayError):
    def __init__(self, expected, data):
        super().__init__(f"Expected {expected} data byte(s), got {len(data)}: {' '.join(f'{b:02X}' for b in data)}")


class NoUniteResponse(UnitelwayError):
    def __init__(self, text, attempts):
        super().__init__(f"No answer to {text or 'the request'} after {attempts} attempt(s)")


class WriteNotAllowed(UnitelwayError):
    def __init__(self, target, allowed):
        # enums print as Action.CYCLE_START / Object.MODE_SELECTION (the string form does not unlock them); variables as '%W16.B'
        shown = f"{type(target).__name__}.{target.name}" if hasattr(target, "name") else repr(target)
        super().__init__(f"{shown} is locked; unlock it with UnitelwayClient(writable={{{shown}, ...}})")


class FileTransferError(UnitelwayError):
    def __init__(self, request, status, meaning):
        self.status = status
        super().__init__(f"{request}: status {status}, {meaning}")


class ProgramRefused(UnitelwayError):
    """write_program() refused before Open-Download-Sequence: nothing was sent."""

    def __init__(self, name, reason):
        super().__init__(f"{name} refused, nothing sent: {reason}")


class ProgramNotVerified(UnitelwayError):
    """The programme was downloaded and closed, but the directory or the read-back does not match."""

    def __init__(self, name, reason):
        super().__init__(f"{name} downloaded but not verified: {reason}")
