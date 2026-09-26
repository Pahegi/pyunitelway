class UnitelwayError(Exception):
    pass


class BadUnitelwayChecksum(UnitelwayError):
    def __init__(self, expected, got):
        super().__init__(f"Bad UNI-TELWAY checksum: expected 0x{expected:02X}, got 0x{got:02X}")


class MalformedUnitelwayResponse(UnitelwayError):
    def __init__(self, message):
        super().__init__(f"Malformed UNI-TELWAY response: {message}")


class RefusedUnitelwayMessage(UnitelwayError):
    def __init__(self):
        super().__init__("Refused UNI-TELWAY message (X-WAY service code 0x22)")


class UniteRequestFailed(UnitelwayError):
    def __init__(self):
        super().__init__("UNI-TE request failed (answer 0xFD): unknown request, bad value or NC state")


class UnexpectedUniteResponse(UnitelwayError):
    def __init__(self, expected, got):
        super().__init__(f"Expected answer code 0x{expected:X}, got 0x{got:X}; is another slave using our link address?")


class UnexpectedAdditionalAnswerCode(UnitelwayError):
    def __init__(self, expected, got):
        super().__init__(f"Expected additional answer code 0x{expected:X}, got 0x{got:X}")


class UnexpectedObjectTypeResponse(UnexpectedUniteResponse):
    pass


class OperationInProgrammeArea(UnitelwayError):
    def __init__(self):
        super().__init__("Request rejected: operation in the programme area")


class NoPollingWindow(UnitelwayError):
    def __init__(self, address, timeout):
        super().__init__(f"The master never polled link address 0x{address:02X} within {timeout} s; "
                         "check the adapter address and that the NUM is on, and run `poetry run listen`")


class UnexpectedDataLength(UnitelwayError):
    def __init__(self, expected, data):
        super().__init__(f"Expected {expected} data byte(s), got {len(data)}: {' '.join(f'{b:02X}' for b in data)}")


class NoUniteResponse(UnitelwayError):
    def __init__(self, text, attempts):
        super().__init__(f"No answer to {text or 'the request'} after {attempts} attempt(s)")


class WriteNotAllowed(UnitelwayError):
    def __init__(self, target, allowed):
        # enums print as Action.CYCLE_START, variables as '%W16.B'
        shown = f"{type(target).__name__}.{target.name}" if hasattr(target, "name") else repr(target)
        super().__init__(f"{shown} is locked; unlock it with UnitelwayClient(writable={{{shown}, ...}})")


class FileTransferError(UnitelwayError):
    """A file request answered a status other than the accepted ones (938914 §4.12-§4.16)."""

    def __init__(self, request, status, meaning):
        self.status = status
        super().__init__(f"{request}: status {status}, {meaning}")


class ProgramRefused(UnitelwayError):
    """write_program or delete_program refused before sending anything."""

    def __init__(self, name, reason):
        super().__init__(f"{name} refused, nothing sent: {reason}")


class ProgramNotVerified(UnitelwayError):
    """The NC answered 0, but the directory or the read-back afterwards does not match."""

    def __init__(self, name, reason):
        super().__init__(f"{name}: {reason}")
