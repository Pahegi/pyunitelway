"""UNI-TELWAY slave client for the NUM 1060 Series II.

Framing per Schneider 35000789, requests per NUM 938914 (UNI-TE) and 938846 §15 (ladder objects).
"""

import logging
import socket
import time

from pyunitelway.constants import *
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.errors import (NoPollingWindow, NoUniteResponse, ProgramNotVerified, ProgramRefused, UnexpectedDataLength,
                                UnexpectedUniteResponse, UniteRequestFailed, WriteNotAllowed)
from pyunitelway.num_constants import (Action, CYCLE_IN_PROGRESS, CYCLE_STOPPED, EXTRACTION_HOOD, IMA_PROGRAM_NUMBERS, LONG_WORKPIECE,
                                       OBJECT_SPEC, PLC_ALL_MODULES, PROGRAM_NUMBER_MAX, VACUUM_PUMP, WIDE_WORKPIECE, FileType, Mode,
                                       Object, program_index)
from pyunitelway.unite_responses import (
    check_status,
    decode_object,
    ladder_variable_name,
    parse_available_bytes_in_ram,
    parse_directory,
    parse_download_segment,
    parse_ladder_read_response,
    parse_ladder_variable,
    parse_mirror_result,
    parse_stations_managed_by_master,
    parse_unit_fault_history,
    parse_unit_identification,
    parse_unit_status,
    parse_upload_segment,
)
from pyunitelway.utils import (
    check_specific_answer,
    compute_bcc,
    download_segments,
    duplicate_dle,
    encode_ladder_value,
    encode_object,
    file_identification,
    format_hex_list,
    get_response_code,
    is_valid_response_code,
    ladder_specific_byte,
    program_blocks,
)

log = logging.getLogger(__name__)


class UnitelwayClient:
    """UNI-TELWAY slave client: this PC is a slave, the NUM 1060 is the master.

    On the NUM 1060 Series II UC SII in Darmstadt the master polls one link address, ``0x01``
    (``example/listen.py``), and answers with the defaults below.

    :param int slave_address: Our link address
    :param int category_code: UNI-TE category code (0-7)
    :param int xway_network: X-WAY network
    :param int xway_station: X-WAY station
    :param int xway_gate: X-WAY gate
    :param int xway_ext1: X-WAY ext1 (5/6-level addressing, 35000789 p.55)
    :param int xway_ext2: X-WAY ext2
    :param bool VPN_Mode: Skip the polling window, the ACK and the answer timeout (tunnelled links only)
    :param writable: What may be written: ladder segments (``"%W"``), variables (``"%W16.B"``), NC objects
        (``Object.MODE_SELECTION``); ``ALL_LADDER_SEGMENTS`` / ``ALL_NC_OBJECTS``. Default: nothing
    """

    def __init__(self, slave_address=0x01, category_code=0x00, xway_network=0x00, xway_station=0xFE, xway_gate=0x00, xway_ext1=0x00, xway_ext2=0x00, VPN_Mode=False,
                 writable=()):
        self._unitelway_start = [DLE, STX, slave_address]
        self._xway_start = [0x20, xway_network, xway_station, xway_gate, xway_ext1, xway_ext2]  # 0x20: standard NPDU
        self.category_code = category_code
        self.link_address = slave_address
        self.VPN_Mode = VPN_Mode
        self.writable = frozenset(self._writable_entry(w) for w in writable)  # write guard
        self.socket = None

    @staticmethod
    def _writable_entry(entry):
        if isinstance(entry, (Object, Action)):
            return entry
        if isinstance(entry, str) and entry in LADDER_REQUEST:
            return entry
        if isinstance(entry, str):
            return ladder_variable_name(entry)
        raise ValueError(f"not an Object, ladder segment or ladder variable: {entry!r}")

    # ------- socket -------

    def connect_socket(self, ip, port, connection_query=None):
        """Connect to the TCP-serial adapter (USR-TCP232-306 in TCP server mode).

        :param str ip: Adapter IPv4
        :param int port: Adapter port
        :param list[int] connection_query: Optional bytes to send right after connecting
        """
        log.info("connecting to %s:%d", ip, port)
        self.socket = socket.create_connection((ip, port), timeout=2)
        self.socket.settimeout(None)
        if connection_query is not None:
            self._unitelway_query(connection_query, "connection query")
        log.info("connected to %s:%d", ip, port)

    def disconnect_socket(self):
        """Close the socket."""
        log.info("disconnecting")
        try:
            self.socket.close()
        except Exception:
            log.warning("socket did not close cleanly", exc_info=True)

    # ------- framing (35000789 §3.5, §3.12, §4.2) -------

    def _unite_to_xway(self, unite_bytes):
        """Prepend the X-WAY header."""
        return list(self._xway_start) + list(unite_bytes)

    def _xway_to_unitelway(self, xway_bytes):
        """Frame an X-WAY message: header, length (doubled if ``DLE``), data with each ``DLE`` doubled, BCC."""
        frame = list(self._unitelway_start)
        length = len(xway_bytes)
        if length == DLE:
            frame.append(DLE)
        frame.append(length)
        data_start = len(frame)
        frame += list(xway_bytes)
        duplicate_dle(frame, data_start)
        frame.append(compute_bcc(frame))
        return frame

    def _unite_to_unitelway(self, unite_bytes):
        """Wrap a UNI-TE request into a UNI-TELWAY frame."""
        return self._xway_to_unitelway(self._unite_to_xway(unite_bytes))

    def _unitelway_query(self, query, text=""):
        """Send raw UNI-TELWAY bytes."""
        log.debug("tx %s%s", f"{text} " if text else "", format_hex_list(query))
        self.socket.sendall(bytearray(query))

    def _unite_query(self, query, text=""):
        """Send a UNI-TE request."""
        self._unitelway_query(self._unite_to_unitelway(query), text)

    # ------- receive (35000789 §3.5, §3.6, §3.12) -------

    def _recv_exact(self, n, deadline):
        """Read exactly ``n`` bytes before ``deadline`` (a ``time.time()`` value, ``None`` = no limit)."""
        data = bytearray()
        while len(data) < n:
            if deadline is None:
                self.socket.settimeout(None)
            else:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise socket.timeout()
                self.socket.settimeout(remaining)
            chunk = self.socket.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Adapter closed the connection")
            data += chunk
        return data

    def _drain(self):
        """Discard buffered bytes so the next poll we act on is a fresh one."""
        self.socket.setblocking(False)
        dropped = 0
        try:
            while True:
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise ConnectionError("Adapter closed the connection")
                dropped += len(chunk)
        except (BlockingIOError, socket.timeout):
            pass
        finally:
            self.socket.setblocking(True)
        if dropped:
            log.debug("drained %d stale byte(s)", dropped)

    def is_my_turn_to_talk(self, address, timeout=POLLING_TIMEOUT_SEC):
        """Wait for a fresh ``<DLE><ENQ><address>`` poll.

        :raises NoPollingWindow: No poll for ``address`` within ``timeout`` seconds
        :raises ConnectionError: The adapter closed the connection
        """
        self._drain()
        deadline = time.time() + timeout
        try:
            while True:
                if self._recv_exact(1, deadline)[0] != DLE:
                    continue
                if self._recv_exact(1, deadline)[0] != ENQ:
                    continue
                polled = self._recv_exact(1, deadline)[0]
                if polled == address:
                    log.debug("polled at 0x%02X", address)
                    return True
                log.debug("poll for 0x%02X", polled)
        except socket.timeout:
            raise NoPollingWindow(address, timeout)
        finally:
            self.socket.settimeout(None)

    def _read_frame(self, timeout):
        """Read the next frame addressed to us: ``<DLE><STX><addr><len>[<DLE>]<data, DLEs doubled><BCC>``.

        Polls, ACKs and other stations' frames are skipped.

        :param float timeout: Seconds, ``None`` for no limit
        :returns: Raw frame bytes, or ``None`` on NAK or timeout
        """
        deadline = None if timeout is None else time.time() + timeout
        try:
            while True:
                b = self._recv_exact(1, deadline)[0]
                if b == ACK:
                    log.debug("rx ACK")
                    continue
                if b == NAK:
                    log.warning("rx NAK: the master rejected our frame")
                    return None
                if b != DLE:
                    log.debug("rx stray %02X", b)
                    continue
                b = self._recv_exact(1, deadline)[0]
                if b == ENQ:
                    log.debug("rx poll for 0x%02X", self._recv_exact(1, deadline)[0])
                    continue
                if b != STX:
                    log.debug("rx stray 10 %02X", b)
                    continue
                frame = [DLE, STX, *self._recv_exact(2, deadline)]
                length = frame[3]
                if length == DLE:
                    frame += self._recv_exact(1, deadline)  # doubled length byte
                read = 0
                while read < length:
                    frame += self._recv_exact(1, deadline)
                    read += 1
                    if frame[-1] == DLE:
                        frame += self._recv_exact(1, deadline)  # doubled data DLE, not counted
                frame += self._recv_exact(1, deadline)  # BCC
                if frame[2] != self.link_address:
                    log.debug("rx frame for 0x%02X ignored: %s", frame[2], format_hex_list(frame))
                    continue
                log.debug("rx %s", format_hex_list(frame))
                return frame
        except socket.timeout:
            log.warning("no answer%s", f" within {timeout:.1f} s" if timeout is not None else "")
            return None
        finally:
            self.socket.settimeout(None)

    def _unite_query_until_response(self, address, query, timeout=TIMEOUT_SEC, text=""):
        """Send a request in a polling window and read its answer frame; up to ``MAX_RETRIES`` attempts.

        :returns: Raw UNI-TELWAY answer frame
        :raises NoUniteResponse: No answer after ``MAX_RETRIES`` attempts
        """
        for attempt in range(1, MAX_RETRIES + 1):
            if not self.VPN_Mode:
                self.is_my_turn_to_talk(address)
            self._unite_query(query, text)
            frame = self._read_frame(None if self.VPN_Mode else timeout)
            if frame is not None:
                return frame
            log.warning("%s: attempt %d/%d failed", text, attempt, MAX_RETRIES)
        raise NoUniteResponse(text, MAX_RETRIES)

    def run_unite(self, address, query, timeout=TIMEOUT_SEC, text=""):
        """Send a UNI-TE request and return the UNI-TE answer bytes.

        :param int address: Our link address
        :param list[int] query: UNI-TE request
        :param float timeout: Seconds to wait for the answer per attempt
        :param str text: Request name for the log
        :rtype: list[int]
        :raises NoPollingWindow: The master never polled ``address``
        :raises NoUniteResponse: No answer after ``MAX_RETRIES`` attempts
        :raises BadUnitelwayChecksum: Bad BCC
        :raises RefusedUnitelwayMessage: X-WAY service code ``0x22``
        :raises UniteRequestFailed: UNI-TE answer ``0xFD``
        """
        frame = self._unite_query_until_response(address, query, timeout, text)
        if not self.VPN_Mode:
            self._unitelway_query([ACK])  # 35000789 §3.6
        unite = unwrap_unite_response(frame)
        log.info("%s -> %s", text, format_hex_list(unite))
        return unite

    def _request(self, code, payload, text, timeout=TIMEOUT_SEC):
        """Send ``code / category / payload``; return the answer once its code matches ``code``."""
        resp = self.run_unite(self.link_address, [code, self.category_code, *payload], timeout, text=text)
        if not is_valid_response_code(code, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(code), resp[0])
        return resp

    def _specific(self, code, payload, text, timeout=TIMEOUT_SEC, also_accept=()):
        """Send a NUM specific request ``F5 / category / code / payload`` (938914 §3.6); return the checked answer."""
        query = [SPECIFIC_REQUEST, self.category_code, code, *payload]
        resp = self.run_unite(self.link_address, query, timeout, text=text)
        check_specific_answer(resp, code, also_accept)
        return resp

    # ------- objects (938914 §4.1) -------

    def _read_objects(self, segment, specific, start_address, number):
        """Read-Object (938914 §4.1.1): the raw answer ``66 / specific / data``.

        :param int segment: ``Object`` value or ``LADDER_REQUEST`` code
        :param int specific: Size byte for ladder segments (938914 §4.1.3.3), 0 for NC objects
        :param int start_address: First object
        :param int number: Objects, not bytes
        :rtype: list[int]
        """
        payload = [segment, specific, *start_address.to_bytes(2, "little"), *number.to_bytes(2, "little")]
        text = f"READ_OBJECTS seg=0x{segment:02X} spec={specific} @0x{start_address:04X} n={number}"
        return self._request(READ_OBJECTS, payload, text)

    def _write_objects(self, segment, specific, start_address, number, data):
        """Write-Object (938914 §4.1.2). Live. Returns ``True`` once the NC answered ``FE``.

        :param list[int] data: Object bytes, little-endian
        """
        if isinstance(data, int):
            data = [data]
        payload = [segment, specific, *start_address.to_bytes(2, "little"), *number.to_bytes(2, "little"), *data]
        text = f"WRITE_OBJECTS seg=0x{segment:02X} spec={specific} @0x{start_address:04X} data={format_hex_list(data)}"
        self._request(WRITE_OBJECTS, payload, text)
        return True

    def read_object(self, obj, address=0):
        """Read one NC object, decoded per ``OBJECT_SPEC`` (938914 §4.1.3).

        :param Object obj: Object family
        :param int address: Index in the family (axis group, tool, E parameter, ...)
        :returns: ``Mode``, signed ``int``, ``list[int]`` of long words, or raw bytes
        """
        spec = OBJECT_SPEC[obj]
        data = self._read_objects(obj, 0, address, 1)[2:]
        if len(data) != spec.size:
            raise UnexpectedDataLength(spec.size, data)
        return decode_object(spec, data)

    def write_object(self, obj, value, address=0):
        """Write one NC object. Live; needs ``obj`` in ``writable``.

        :param Object obj: Object family, writable per 938914 §4.1.3
        :param value: ``Mode``, ``int``, list of long words or raw bytes, per the spec
        """
        obj = Object(obj)
        if obj not in self.writable:
            raise WriteNotAllowed(obj, self.writable)
        spec = OBJECT_SPEC[obj]
        if not spec.writable:
            raise ValueError(f"{obj.name} is read-only (938914 §4.1.3)")
        return self._write_objects(obj, 0, address, 1, encode_object(spec, value))

    # ------- this machine: IMA BIMA Quadroform C80/280 -------

    def read_mode(self):
        """NC mode (segment 180) as ``Mode``."""
        return self.read_object(Object.MODE_SELECTION)

    def write_mode(self, mode):
        """Select the NC mode (segment 180). Live; needs ``Object.MODE_SELECTION`` in ``writable``."""
        return self.write_object(Object.MODE_SELECTION, Mode(mode))

    def _nc_request(self, action, code, text, refusal):
        """Run or Stop (938914 §4.9, §4.10), locked like a write: ``True`` on ``FE``, ``False`` on the ``FD`` refusal."""
        if action not in self.writable:
            raise WriteNotAllowed(action, self.writable)
        try:
            resp = self.run_unite(self.link_address, [code, self.category_code], text=text)
        except UniteRequestFailed:
            resp = [0xFD]
        if resp[0] == 0xFD:
            log.info("%s refused: %s", text, refusal)
            return False
        if not is_valid_response_code(code, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(code), resp[0])
        return True

    def read_cycle_in_progress(self):
        """``%R3.2`` ``E_CYCLE`` "cycle in progress" (938846 §3.8.1)."""
        return self.read_ladder(CYCLE_IN_PROGRESS)

    def cycle_start(self):
        """CYCLE START: the Run request (938914 §4.9). Live; needs ``Action.CYCLE_START`` in ``writable``.

        Starts the selected programme or MDI block in the current mode, past the ladder's start memory (``%SP11``).
        Only the NC's own state check remains: ``False`` on its ``FD`` refusal, also once the MDI block is used up.
        """
        return self._nc_request(Action.CYCLE_START, RUN, "RUN", "NC status incompatible with a cycle start (938914 §4.9)")

    def read_cycle_stopped(self):
        """``%R3.1`` ``E_ARUS`` "cycle stop" (938846 §3.8.1): held by Cycle Stop until the next CYCLE START."""
        return self.read_ladder(CYCLE_STOPPED)

    def cycle_stop(self):
        """CYCLE STOP: the Stop request (938914 §4.10 "FEED STOP"). Live; needs ``Action.CYCLE_STOP`` in ``writable``.

        The CYHLD machining stop: feed stops, the spindle keeps turning, :meth:`cycle_start` resumes. Not an
        emergency stop.
        """
        return self._nc_request(Action.CYCLE_STOP, STOP, "STOP", "NC status incompatible with feed stop (938914 §4.10)")

    feed_stop = cycle_stop  # the request's name in 938914

    def read_vacuum_pump(self):
        """``%Q0700.6`` ``QK_VakpEin__``: the vacuum pump contactor."""
        return self.read_ladder(VACUUM_PUMP)

    def write_vacuum_pump(self, on):
        """Start or stop the vacuum pump. Live; needs ``"%Q0700.6"`` or ``"%Q"`` in ``writable``.

        The ladder only touches ``%Q0700.6`` from the panel key (``%SP24/00``), so the value holds. The coolant pump
        runs with it.
        """
        return self.write_ladder(VACUUM_PUMP, bool(on))

    def read_extraction_hood(self):
        """``%Q0100.3`` ``QLBABFSAKT`` "Absaugung Frässpindel": the hood latch (lamp = state)."""
        return self.read_ladder(EXTRACTION_HOOD)

    def write_extraction_hood(self, on):
        """Lift or lower the spindle extraction hood. Live; needs ``"%Q0100.3"`` or ``"%Q"`` in ``writable``.

        ``%SP43/04`` drives the lift valves ``%Q0800.2/.3`` only while the latch is on and a height was programmed
        (M201-M203): ``False`` lowers the hood, ``True`` lifts it to that height. A tool change needs it up.
        """
        return self.write_ladder(EXTRACTION_HOOD, bool(on))

    def read_long_workpiece(self):
        """``%Q0100.4`` ``QLBL_WKEIN`` "Langes Werkstück": the long-part latch (lamp = state)."""
        return self.read_ladder(LONG_WORKPIECE)

    def write_long_workpiece(self, on):
        """Select long-workpiece mode (Langteil). Live; needs ``"%Q0100.4"`` or ``"%Q"`` in ``writable``.

        Read by 34 networks: clamping, stops, template valves, tool magazine side, ``E40028``. A programme's M table
        (``E30081``) can force it; fault 215 if a programme needs it and it is off.
        """
        return self.write_ladder(LONG_WORKPIECE, bool(on))

    def read_wide_workpiece(self):
        """``%Q0101.4`` ``QLBB_WKEIN`` "Überbreites Werkstück": the wide-part latch (lamp = state)."""
        return self.read_ladder(WIDE_WORKPIECE)

    def write_wide_workpiece(self, on):
        """Select wide-workpiece mode (Breitteil). Live; needs ``"%Q0101.4"`` or ``"%Q"`` in ``writable``.

        The panel key only works outside a cycle; a write ignores that gate. With it on and a machining side set,
        the tool magazine moves to the other side (``%SP44/02-03``). Never together with the long latch (fault 198).
        """
        return self.write_ladder(WIDE_WORKPIECE, bool(on))

    # ------- ladder variables (938914 §4.1.3.3, 938846 §15) -------

    def read_ladder(self, variable, signed=True):
        """Read one ladder variable.

        :param str variable: ``%SNNNN.S``: symbol ``%M %V %I %Q %R %W %S``, hex number, size ``.0``-``.7`` (bit),
            ``.B``, ``.W``, ``.L`` or ``.&``; no index fields
        :param bool signed: ``.B``/``.W``/``.L`` signed (938846 §4) or unsigned (I/O bytes, potentiometers)
        :returns: ``bool`` for a bit, ``int`` otherwise
        """
        (_symbol, segment, address, size, _index) = parse_ladder_variable(variable)
        resp = self._read_objects(segment, ladder_specific_byte(size), address, 1)
        return parse_ladder_read_response(resp, size, signed)

    def write_ladder(self, variable, value, signed=True):
        """Write one ladder variable. Live; needs the variable or its segment in ``writable``. Trace the address
        with ``trace_signal.py`` first: ``%W3.2`` is NC start.

        :param str variable: As for :meth:`read_ladder`
        :param value: ``bool`` for a bit, else an ``int`` in the signed or unsigned range of the size
        :returns: ``True`` on the ``FE`` answer
        """
        (symbol, segment, address, size, _index) = parse_ladder_variable(variable)
        name = ladder_variable_name(variable)
        if symbol not in self.writable and name not in self.writable:
            raise WriteNotAllowed(name, self.writable)
        data = encode_ladder_value(size, value, signed)
        return self._write_objects(segment, ladder_specific_byte(size), address, 1, data)

    # ------- general purpose requests (938914 §4.3-§4.8) -------

    def get_unit_identification(self):
        """Product type, version and name (§4.3) as a dict."""
        return parse_unit_identification(self._request(IDENTIFICATION, [], "IDENTIFICATION"))

    def get_unit_status(self, axis_group_index=0):
        """NC and PLC state plus the programme status of one axis group (§4.4) as a dict."""
        return parse_unit_status(self._request(STATUS, [axis_group_index], "STATUS"))

    def mirror(self, data):
        """Link test (§4.5): ``True`` if the NC echoes ``data`` (up to 126 bytes)."""
        if len(data) > 126:
            raise ValueError("mirror data is limited to 126 bytes (938914 §4.5)")
        return parse_mirror_result(self._request(MIRROR, data, "MIRROR")[1:], data)

    def get_unit_fault_history(self):
        """Link error counters (§4.6): sent/not acknowledged, sent/rejected, received/not acknowledged, received/rejected."""
        return parse_unit_fault_history(self._request(READ_CPT, [], "READ_CPT"))

    def get_stations_managed_by_master(self):
        """Stations the master manages and whether each is connected (§4.7): ``(count, [bool, ...])``."""
        return parse_stations_managed_by_master(self._request(ETAT_STATION, [], "ETAT_STATION"))

    # ------- NUM specific requests (938914 §3.6) -------

    def get_available_bytes_in_ram(self):
        """Free part-programme RAM in bytes (§4.15)."""
        return parse_available_bytes_in_ram(self._specific(READ_MEMORY_FREE, [], "READ_MEMORY_FREE"))

    def write_message(self, message):
        """Show a supervisor message on the NC screen (§4.17, under E/A → Fehlermeldungen → Netz-Meldungen). Live.

        :param message: One to three lines of up to 32 printable ASCII characters: a ``str`` with ``\\n`` or a list
        :returns: ``True``
        """
        lines = message.split("\n") if isinstance(message, str) else list(message)
        if not 1 <= len(lines) <= 3:
            raise ValueError(f"1 to 3 message lines, got {len(lines)}")
        if not any(line.strip() for line in lines):
            raise ValueError("empty message")
        data = []
        for line in lines:
            if len(line) > 32:
                raise ValueError(f"line longer than 32 characters: {line!r}")
            if any(not 0x20 <= ord(c) <= 0x7F for c in line):
                raise ValueError(f"non-printable character in {line!r}")
            data += [ord(c) for c in line.ljust(32)]
        # index byte 0; the NC answers FE where the §3.6 table says 7B
        self._specific(WRITE_MESSAGE, [0x00, len(lines), *data], f"WRITE_MESSAGE {len(lines)} line(s)", also_accept=(0xFE,))
        return True

    # ------- files: upload and directory (938914 §4.13, §4.16) -------

    def upload(self, file_type, identification=0, timeout=TIMEOUT_SEC):
        """Read a file from the NC (§4.13): open, segments, close. The close goes out on every exit, because the NC
        has one transfer slot and does not close every type itself.

        :param FileType file_type: What to read
        :param int identification: Low three bytes of the file id (programme index, ladder module)
        :param float timeout: Answer wait per attempt
        :rtype: bytes
        :raises FileTransferError: A status other than 0/15, or a segment out of sequence
        """
        name = f"{FileType(file_type).name} 0x{identification:06X}"
        resp = self._request(OPEN_UPLOAD, file_identification(file_type, identification), f"OPEN_UPLOAD {name}", timeout)
        status = check_status("OPEN_UPLOAD", resp[1], (0, 15))  # 15: empty programme
        data = bytearray()
        try:
            number = 1
            while status == 0:
                resp = self._request(READ_UPLOAD, number.to_bytes(2, "little"), f"READ_UPLOAD {name} #{number}", timeout)
                status, segment = parse_upload_segment(resp, number)
                data += segment
                number += 1
        finally:
            self.close_upload(timeout)
        return bytes(data)

    def close_upload(self, timeout=TIMEOUT_SEC):
        """Close-Upload-Sequence (§4.13.3): ``True`` if a file was open, ``False`` on status 4 "already closed"."""
        resp = self._request(CLOSE_UPLOAD, [], "CLOSE_UPLOAD", timeout)
        return check_status("CLOSE_UPLOAD", resp[1], (0, 4)) == 0

    def read_program(self, number, group=0, timeout=TIMEOUT_SEC):
        """Part programme ``%number.group`` (type H'12') as stored: CR LF line ends, no ``%`` line."""
        return self.upload(FileType.PART_PROGRAM, program_index(number, group), timeout)

    def read_machine_parameters(self, timeout=TIMEOUT_SEC):
        """Machine parameters (type H'05'): the ``.xpa`` text of the IPC's ``UPLF 5 0 0``."""
        return self.upload(FileType.MACHINE_PARAMETERS, 0, timeout)

    def read_plc_archive(self, timeout=TIMEOUT_SEC):
        """All ladder and C modules (type H'07', module type 16): the ``.xar`` of ``UPLF 7 16 0``, about 111 KB."""
        return self.upload(FileType.PLC_LADDER, PLC_ALL_MODULES << 16, timeout)

    def read_macros(self, timeout=TIMEOUT_SEC):
        """Resident macros (type H'03'): one 29-byte record per protected area 1-3 (938818 P95); all empty here."""
        return self.upload(FileType.MACROS, 0, timeout)

    def read_axis_calibration(self, timeout=TIMEOUT_SEC):
        """Axis calibration (type H'02') in the ``.xpa`` text format; header and trailer only on this machine."""
        return self.upload(FileType.AXIS_CALIBRATION, 0, timeout)

    def read_directory(self, start=0, group=0):
        """Part programmes in the NC RAM from ``%start.group`` upward (§4.16) as ``Program`` tuples, NC order."""
        payload = program_index(start, group).to_bytes(4, "little")
        status, programs = parse_directory(self._specific(OPEN_DIRECTORY, payload, f"OPEN_DIRECTORY from %{start}.{group}"), "OPEN_DIRECTORY")
        try:
            while status == 0:
                status, more = parse_directory(self._specific(DIRECTORY, [], "DIRECTORY"), "DIRECTORY")
                programs += more
        finally:
            if status == 0:  # 15: the NC closed it itself
                self.close_directory()
        return programs

    def close_directory(self):
        """Close-Directory (§4.16.3): ``True`` if a listing was open, ``False`` on status 4 "already closed"."""
        return check_status("CLOSE_DIRECTORY", self._specific(CLOSE_DIRECTORY, [], "CLOSE_DIRECTORY")[2], (0, 4)) == 0

    # ------- files: download and delete (938914 §4.12, §4.14), part programmes only -------

    def _program_target(self, action, number, group):
        """The refusals write_program and delete_program share; returns ``(name, index)``."""
        if action not in self.writable:
            raise WriteNotAllowed(action, self.writable)
        name = f"%{number}.{group}"
        if not 1 <= number <= PROGRAM_NUMBER_MAX or number in IMA_PROGRAM_NUMBERS:
            raise ProgramRefused(name, f"IMA's programmes and %{PROGRAM_NUMBER_MAX + 1} upward are never touched")
        status = self.get_unit_status()
        mode, running = status["nc_mode"], status["nc_status"]["active_program"]
        if running or mode is Mode.EDIT:
            raise ProgramRefused(name, f"NC not idle (programme running={running}, mode={mode.name})")
        if status["current_program_number"] == number:
            raise ProgramRefused(name, "it is the active programme (%R1A.W)")
        return name, program_index(number, group)

    def _directory_sizes(self):
        """``{programme index: size}`` from a fresh directory read."""
        return {program_index(p.number, p.group): p.size for p in self.read_directory()}

    def write_program(self, number, text, group=0, timeout=TIMEOUT_SEC):
        """Store a part programme in the NC RAM (§4.12) and read it back. Live; needs ``Action.WRITE_PROGRAM``.

        The only download here: type H'12', never to an existing number (the NC refuses those with status 1 too).
        Refused before anything is sent: IMA's numbers and ``%9000`` upward, a running or editing NC, the active
        programme, a listed number, too little RAM, and text the NC would reject (``program_blocks``).

        :param int number: 1 to ``PROGRAM_NUMBER_MAX``
        :param text: Programme body without its ``%`` line: ``str`` (line ends normalised) or ``bytes`` (as is)
        :returns: Size in the directory afterwards
        :raises ProgramRefused: A check failed, nothing was sent
        :raises FileTransferError: The NC answered a status other than 0
        :raises ProgramNotVerified: Stored, but the directory or the read-back differs
        """
        name, index = self._program_target(Action.WRITE_PROGRAM, number, group)
        blocks = program_blocks(text)
        data = b"".join(blocks)
        segments = download_segments(blocks)
        if index in self._directory_sizes():
            raise ProgramRefused(name, "already in the NC RAM, nothing is overwritten")
        free = self.get_available_bytes_in_ram()
        if free < len(data) + 128:
            raise ProgramRefused(name, f"{free} bytes free, {len(data) + 128} needed")
        log.info("write_program %s: %d blocks, %d bytes, %d segment(s)", name, len(blocks), len(data), len(segments))
        resp = self._request(OPEN_DOWNLOAD, file_identification(FileType.PART_PROGRAM, index), f"OPEN_DOWNLOAD {name}", timeout)
        check_status("OPEN_DOWNLOAD", resp[1])
        try:
            for n, segment in enumerate(segments, 1):
                payload = [*n.to_bytes(2, "little"), *len(segment).to_bytes(2, "little"), *segment]
                parse_download_segment(self._request(WRITE_DOWNLOAD, payload, f"WRITE_DOWNLOAD {name} #{n}", timeout), n)
        finally:
            self.close_download(timeout)
        listed = self._directory_sizes()
        if index not in listed:
            raise ProgramNotVerified(name, "not in the directory after the close")
        back = self.read_program(number, group, timeout)
        if back != data:
            raise ProgramNotVerified(name, f"read back {len(back)} bytes, sent {len(data)}")
        return listed[index]

    def close_download(self, timeout=TIMEOUT_SEC):
        """Close-Download-Sequence (§4.12.3): ``True`` if a file was open, ``False`` on status 4. Status 11 raises:
        the last block had no LF and the NC deleted the file."""
        resp = self._request(CLOSE_DOWNLOAD, [], "CLOSE_DOWNLOAD", timeout)
        return check_status("CLOSE_DOWNLOAD", resp[1], (0, 4)) == 0

    def delete_program(self, number, group=0, timeout=TIMEOUT_SEC):
        """Delete a part programme from the NC RAM: Delete-File (§4.14). Live; needs ``Action.DELETE_PROGRAM``.

        Same refusals as :meth:`write_program`, and the number must be listed; afterwards it must be gone.

        :returns: Size the directory listed before
        """
        name, index = self._program_target(Action.DELETE_PROGRAM, number, group)
        listed = self._directory_sizes()
        if index not in listed:
            raise ProgramRefused(name, "not in the NC RAM")
        log.info("delete_program %s: %d bytes in the directory", name, listed[index])
        resp = self._specific(DELETE_FILE, file_identification(FileType.PART_PROGRAM, index)[:4], f"DELETE_FILE {name}", timeout)
        check_status("DELETE_FILE", resp[2])
        if index in self._directory_sizes():
            raise ProgramNotVerified(name, "still in the directory after status 0")
        return listed[index]
