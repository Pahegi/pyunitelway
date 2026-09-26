"""UNI-TELWAY slave client for the NUM 1060 Series II.

Framing per Schneider 35000789, requests per NUM 938914 (UNI-TE) and 938846 §15 (ladder objects).
"""

import logging
import socket
import time

from pyunitelway.constants import *
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.errors import (NoPollingWindow, NoUniteResponse, UnexpectedDataLength, UnexpectedUniteResponse,
                                UniteRequestFailed, WriteNotAllowed)
from pyunitelway.num_constants import (Action, EXTRACTION_HOOD, LONG_WORKPIECE, OBJECT_SPEC, PLC_ALL_MODULES, VACUUM_PUMP,
                                       WIDE_WORKPIECE, FileType, Mode, Object, program_index)
from pyunitelway.unite_responses import (
    check_file_status,
    decode_object,
    ladder_variable_name,
    parse_available_bytes_in_ram,
    parse_directory,
    parse_ladder_read_response,
    parse_ladder_variable,
    parse_mirror_result,
    parse_shutdown_result,
    parse_stations_managed_by_master,
    parse_unit_fault_history,
    parse_unit_identification,
    parse_unit_status,
    parse_upload_segment,
    parse_write_result,
)
from pyunitelway.utils import (
    check_specific_answer,
    compute_bcc,
    duplicate_dle,
    encode_ladder_value,
    encode_object,
    file_identification,
    format_hex_list,
    get_response_code,
    is_valid_response_code,
    ladder_specific_byte,
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

    # ------- objects (938914 §4.1) -------

    def _read_objects(self, segment, specific, start_address, number):
        """Send Read-Object and return the raw answer ``code / specific / data`` (938914 §4.1.1).

        :param int segment: Object family: an ``Object`` value or a ``LADDER_REQUEST`` code
        :param int specific: Object size for ladder segments (938914 §4.1.3.3), else 0
        :param int start_address: First object in the family
        :param int number: Number of objects (not bytes)
        :rtype: list[int]
        :raises UnexpectedUniteResponse: Answer code is not ``0x66``
        """
        query = [READ_OBJECTS, self.category_code, segment, specific]
        query += list(start_address.to_bytes(2, "little")) + list(number.to_bytes(2, "little"))
        text = f"READ_OBJECTS seg=0x{segment:02X} spec={specific} @0x{start_address:04X} n={number}"
        resp = self.run_unite(self.link_address, query, text=text)
        if not is_valid_response_code(READ_OBJECTS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_OBJECTS), resp[0])
        return resp

    def _write_objects(self, segment, specific, start_address, number, data):
        """Send Write-Object (938914 §4.1.2). **Live on the machine.**

        :param int segment: Object family
        :param int specific: Object size for ladder segments, else 0
        :param int start_address: First object to write
        :param int number: Number of objects
        :param list[int] data: Object bytes, little-endian
        :returns: ``True`` on the ``0xFE`` answer
        :raises UnexpectedUniteResponse: Answer code is not ``0xFE``
        """
        if isinstance(data, int):
            data = [data]
        query = [WRITE_OBJECTS, self.category_code, segment, specific]
        query += list(start_address.to_bytes(2, "little")) + list(number.to_bytes(2, "little")) + list(data)
        text = f"WRITE_OBJECTS seg=0x{segment:02X} spec={specific} @0x{start_address:04X} data={format_hex_list(data)}"
        resp = self.run_unite(self.link_address, query, text=text)
        if not is_valid_response_code(WRITE_OBJECTS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(WRITE_OBJECTS), resp[0])
        return parse_write_result(resp)

    def read_object(self, obj, address=0):
        """Read one NC object and decode it per ``OBJECT_SPEC`` (938914 §4.1.3).

        :param Object obj: Object family
        :param int address: Object index in the family (axis group, tool, E parameter, ...)
        :returns: ``Mode``, signed ``int``, ``list[int]`` of signed long words, or the raw bytes
        :raises UnexpectedDataLength: Answer size differs from the spec
        """
        spec = OBJECT_SPEC[obj]
        resp = self._read_objects(obj, 0, address, 1)
        data = resp[2:]
        if len(data) != spec.size:
            raise UnexpectedDataLength(spec.size, data)
        return decode_object(spec, data)

    def write_object(self, obj, value, address=0):
        """Write one NC object. **Live on the machine.**

        :param Object obj: Object family, must be writable per 938914 §4.1.3
        :param value: ``Mode``, ``int``, list of long words or raw bytes, per the spec
        :param int address: Object index in the family
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: ``obj`` not unlocked on this client
        :raises ValueError: Read-only object or malformed value
        """
        obj = Object(obj)
        if obj not in self.writable:
            raise WriteNotAllowed(obj, self.writable)
        spec = OBJECT_SPEC[obj]
        if not spec.writable:
            raise ValueError(f"{obj.name} is read-only (938914 §4.1.3)")
        return self._write_objects(obj, 0, address, 1, encode_object(spec, value))

    # ------- this machine (IMA BIMA Quadroform C80/280) -------
    
    def read_mode(self):
        """Current NC mode, segment 180.

        :rtype: Mode
        """
        return self.read_object(Object.MODE_SELECTION)

    def write_mode(self, mode):
        """Select the NC mode, segment 180. **Live**; needs ``Object.MODE_SELECTION`` in ``writable``.

        :param Mode mode: Mode to select
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: Segment 180 not unlocked on this client
        """
        return self.write_object(Object.MODE_SELECTION, Mode(mode))

    def cycle_start(self):
        """CYCLE START over the bus: the Run request (938914 §4.9). **Live - it starts the selected programme or the
        MDI block in the current mode.** Needs ``Action.CYCLE_START`` in ``writable``; ``ALL_NC_OBJECTS`` and
        ``ALL_LADDER_SEGMENTS`` do not include it.

        The request goes to the NC directly, past the ladder's start memory (``%SP11``: Not-Aus quittiert, mode,
        feed authorised, selected = active programme, valid work-list data, clamped workpiece side). What stays:
        the NC's own state check - ``0xFD`` "NC status incompatible with a cycle start" - and the PLC's feed
        authorisation ``%W4.0`` AUTAV on every movement. Verified 2026-09-26 in MDI (todo.md G): a ``G4 F2`` block ran
        (``%R3.2`` E_CYCLE high for 1.9 s), a repeat on the consumed block answered ``0xFD``, ``G0 X2000`` moved the X axis.

        :returns: ``True`` on ``0xFE``, ``False`` on the ``0xFD`` refusal
        :raises WriteNotAllowed: ``Action.CYCLE_START`` not unlocked on this client
        """
        if Action.CYCLE_START not in self.writable:
            raise WriteNotAllowed(Action.CYCLE_START, self.writable)
        try:
            resp = self.run_unite(self.link_address, [RUN, self.category_code], text="RUN")
        except UniteRequestFailed:
            log.info("RUN refused: NC status incompatible with a cycle start (938914 §4.9)")
            return False
        if resp[0] == 0xFD:
            log.info("RUN refused: NC status incompatible with a cycle start (938914 §4.9)")
            return False
        if not is_valid_response_code(RUN, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(RUN), resp[0])
        return True

    def read_vacuum_pump(self):
        """Is the vacuum pump contactor on? Reads ``%Q0700.6`` (``QK_VakpEin__``).

        :rtype: bool
        """
        return self.read_ladder(VACUUM_PUMP)

    def write_vacuum_pump(self, on):
        """Switch the vacuum pump on or off. **Live**; needs ``"%Q0700.6"`` or ``"%Q"`` in ``writable``.

        Writes ``%Q0700.6`` (``QK_VakpEin__`` "KR Vakuumpumpe einschalten"). The PLC only sets and resets that
        output from the panel key in ``%SP24/00``, so the written value holds until the key is pressed. Verified
        2026-09-23: ``True`` started the pump, ``False`` stopped it. The spindle coolant pump runs with it; the panel
        lamp ``%Q0100.5`` is not touched.

        :param bool on: ``True`` starts the pump, ``False`` stops it
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: ``%Q0700.6`` not unlocked on this client
        """
        return self.write_ladder(VACUUM_PUMP, bool(on))

    def read_extraction_hood(self):
        """Is the "Absaugung Frässpindel" toggle on? Reads ``%Q0100.3`` (``QLBABFSAKT``, lamp = latch).

        :rtype: bool
        """
        return self.read_ladder(EXTRACTION_HOOD)

    def write_extraction_hood(self, on):
        """Lift or lower the spindle extraction hood. **Live**; needs ``"%Q0100.3"`` or ``"%Q"`` in ``writable``.

        Writes the panel latch ``%Q0100.3`` (``QLBABFSAKT`` "Absaugung Frässpindel"), toggled by key ``%I0103.3`` in
        ``%SP43/01``. ``%SP43/04`` drives the lift valves ``%Q0800.2`` (50 mm) / ``%Q0800.3`` (160 mm) only while the
        latch is on, from the height memory ``%V942.0/.1`` set by M200-M203. ``False`` therefore lowers the hood
        fully; ``True`` lifts it to the last programmed height (nothing if that is M200). A tool change needs the
        hood up (both end switches), else feed stop ``%V80.7``. Untested.

        :param bool on: ``False`` = hood down, ``True`` = hood at the programmed height
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: ``%Q0100.3`` not unlocked on this client
        """
        return self.write_ladder(EXTRACTION_HOOD, bool(on))

    def read_long_workpiece(self):
        """Is "Langes Werkstück" selected? Reads ``%Q0100.4`` (``QLBL_WKEIN``, lamp = latch).

        :rtype: bool
        """
        return self.read_ladder(LONG_WORKPIECE)

    def write_long_workpiece(self, on):
        """Select or deselect long-workpiece mode (Langteil, X > 900 mm). **Live**; needs ``"%Q0100.4"`` or ``"%Q"``.

        Writes ``%Q0100.4`` (``QLBL_WKEIN`` "Langes Werkstück"), toggled by key ``%I0103.4`` in ``%SP30/00``. Read by
        34 networks: clamping uses both sides and the template valves, the stops lower on clamp (``%SP30/07``), the
        tool magazine side follows it (``%SP44/02-03``), ``E40028`` mirrors it to the NC. A programme with
        ``E30081 == 1`` (``VHM_LANGTEIL``) forces the latch from its M-function table. Fault 215 if a programme
        needs it (``E30088`` 1 or 3) and it is off. Untested.

        :param bool on: ``True`` selects, ``False`` deselects
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: ``%Q0100.4`` not unlocked on this client
        """
        return self.write_ladder(LONG_WORKPIECE, bool(on))

    def read_wide_workpiece(self):
        """Is "Überbreites Teil" selected? Reads ``%Q0101.4`` (``QLBB_WKEIN``, lamp = latch).

        :rtype: bool
        """
        return self.read_ladder(WIDE_WORKPIECE)

    def write_wide_workpiece(self, on):
        """Select or deselect wide-workpiece mode (Breitteil, Y > 800 mm). **Live**; needs ``"%Q0101.4"`` or ``"%Q"``.

        Writes ``%Q0101.4`` (``QLBB_WKEIN`` "Überbreites Werkstück"), toggled by the unnamed key ``%I0102.4`` in
        ``%SP44/01`` - the key only works outside a cycle, a direct write ignores that gate. With it on, the tool
        magazine is driven to the side away from the machining side (``%SP44/02-03``, ``%Q0800.4/.5``) once a cycle
        has set "Bearbeitung links/rechts". Fault 214 and feed stop ``%V82.4`` if a programme needs it (``E30088``
        >= 2) and it is off; fault 198 if long and wide are both on with a tool change aborted. Untested.

        :param bool on: ``True`` selects, ``False`` deselects
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: ``%Q0101.4`` not unlocked on this client
        """
        return self.write_ladder(WIDE_WORKPIECE, bool(on))

    # ------- ladder variables (938914 §4.1.3.3, 938846 §15) -------

    def read_ladder(self, variable, signed=True):
        """Read one ladder variable.

        :param str variable: ``%SNNNN.S`` - symbol ``%M %V %I %Q %R %W %S``, hex logical number, size
            ``.0``-``.7`` (bit), ``.B``, ``.W``, ``.L`` or ``.&``. Index fields are not supported.
        :param bool signed: ``.B``/``.W``/``.L`` as signed (938846 §4) or unsigned (I/O bytes, potentiometers)
        :returns: ``bool`` for a bit, ``int`` for ``.B``/``.W``/``.L``, address ``int`` for ``.&``
        :raises ValueError: Invalid variable
        :raises UnexpectedUniteResponse: Answer code is not ``0x66``
        :raises UnexpectedObjectTypeResponse: Echoed specific byte differs
        :raises UnexpectedDataLength: Data length does not match the size
        """
        (_symbol, segment, address, size, _index) = parse_ladder_variable(variable)
        resp = self._read_objects(segment, ladder_specific_byte(size), address, 1)
        return parse_ladder_read_response(resp, size, signed)

    def write_ladder(self, variable, value, signed=True):
        """Write one ladder variable. **Live on the machine.**

        .. WARNING::
            Trace the address with ``trace_signal.py`` first; ``%W3.2`` is NC start. Locked unless ``writable=``
            names it.

        :param str variable: As for :meth:`read_ladder`
        :param value: ``bool`` for a bit, else an ``int`` in the signed or unsigned range of the size
        :param bool signed: Which range ``value`` must fit
        :returns: ``True`` on the ``0xFE`` answer
        :raises WriteNotAllowed: Neither the variable nor its segment is unlocked on this client
        :raises ValueError: Invalid variable, ``.&``, or value out of range
        """
        (symbol, segment, address, size, _index) = parse_ladder_variable(variable)
        name = ladder_variable_name(variable)
        if symbol not in self.writable and name not in self.writable:
            raise WriteNotAllowed(name, self.writable)
        data = encode_ladder_value(size, value, signed)
        return self._write_objects(segment, ladder_specific_byte(size), address, 1, data)

    # ------- general purpose requests (938914 §4.3 - §4.8) -------

    def get_unit_identification(self):
        """Unit identification (§4.3).

        :returns: ``product_type_code``, ``product_type``, ``subtype``, ``product_version``, ``text``
        :rtype: dict
        """
        resp = self.run_unite(self.link_address, [IDENTIFICATION, self.category_code], text="IDENTIFICATION")
        if not is_valid_response_code(IDENTIFICATION, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(IDENTIFICATION), resp[0])
        return parse_unit_identification(resp)

    def get_unit_status(self, axis_group_index=0):
        """Unit status: NC + PLC state, programme status of one axis group (§4.4).

        :param int axis_group_index: Axis group
        :rtype: dict
        """
        resp = self.run_unite(self.link_address, [STATUS, self.category_code, axis_group_index], text="STATUS")
        if not is_valid_response_code(STATUS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(STATUS), resp[0])
        return parse_unit_status(resp)

    def mirror(self, data):
        """Mirror request: the NC echoes ``data`` (§4.5).

        :param list[int] data: Up to 126 bytes
        :returns: ``True`` if the echo matches
        :rtype: bool
        """
        if len(data) > 126:
            raise ValueError("mirror data is limited to 126 bytes (938914 §4.5)")
        resp = self.run_unite(self.link_address, [MIRROR, self.category_code, *data], text="MIRROR")
        if not is_valid_response_code(MIRROR, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(MIRROR), resp[0])
        return parse_mirror_result(resp[1:], data)

    def get_unit_fault_history(self):
        """Link error counters (§4.6): sent/not acknowledged, sent/rejected, received/not acknowledged, received/rejected.

        :rtype: (int, int, int, int)
        """
        resp = self.run_unite(self.link_address, [READ_CPT, self.category_code], text="READ_CPT")
        if not is_valid_response_code(READ_CPT, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_CPT), resp[0])
        return parse_unit_fault_history(resp)

    def get_stations_managed_by_master(self):
        """Stations managed by the master and their connected state (§4.7).

        :rtype: (int, list[bool])
        """
        resp = self.run_unite(self.link_address, [ETAT_STATION, self.category_code], text="ETAT_STATION")
        if not is_valid_response_code(ETAT_STATION, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(ETAT_STATION), resp[0])
        return parse_stations_managed_by_master(resp)

    # ------- NUM specific requests (938914 §3.6) -------

    def get_available_bytes_in_ram(self):
        """Free bytes in the NC RAM (§4.15).

        :rtype: int
        :raises OperationInProgrammeArea: Status ``0x02``
        """
        query = [SPECIFIC_REQUEST, self.category_code, READ_MEMORY_FREE]
        resp = self.run_unite(self.link_address, query, text="READ_MEMORY_FREE")
        check_specific_answer(resp, READ_MEMORY_FREE)
        return parse_available_bytes_in_ram(resp)

    def write_message(self, message):
        """Display a supervisor message on the NC (938914 §4.17, request F5/4B). **Live, unverified.**

        :param message: One to three lines of up to 32 printable ASCII characters (``0x20``-``0x7F``):
            a ``str`` with ``\\n`` between lines, or a list of lines. Each line is padded to 32 bytes.
        :returns: ``True`` on the positive answer (``0xFE`` per §4.17, ``0x7B`` per the §3.6 table)
        :raises ValueError: No line, more than three, a line over 32 characters, or a non-printable character
        :raises UniteRequestFailed: Negative report ``0xFD`` (request unknown)
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
                raise ValueError(f"non-printable character in {line!r} (allowed: 0x20-0x7F)")
            data += [ord(c) for c in line.ljust(32)]
        query = [SPECIFIC_REQUEST, self.category_code, WRITE_MESSAGE, 0x00, len(lines)] + data  # index byte: not significant
        resp = self.run_unite(self.link_address, query, text=f"WRITE_MESSAGE {len(lines)} line(s)")
        check_specific_answer(resp, WRITE_MESSAGE, also_accept=(0xFE,))
        return True

    # cannot be safely tested on a live machine, possibly dangerous
    # def shutdown(self):
    #     """Shut down the PCNC PC module (938928 §10.4.10). **Untested; unknown whether a UC SII answers.**

    #     :returns: ``True`` if the status byte is ``0x00``
    #     """
    #     query = [SPECIFIC_REQUEST, self.category_code, SHUTDOWN, 0x00]
    #     resp = self.run_unite(self.link_address, query, text="SHUTDOWN")
    #     check_specific_answer(resp, SHUTDOWN)
    #     return parse_shutdown_result(resp)

    # ------- files (938914 §4.13, §4.16): read only - no download or delete request exists here -------

    def _answer(self, request, resp):
        """Raise unless ``resp`` carries the answer code of ``request``; return it."""
        if not is_valid_response_code(request, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(request), resp[0])
        return resp

    def upload(self, file_type, identification=0, timeout=TIMEOUT_SEC):
        """Read a file from the NC: Open-Upload-Sequence, Read-Upload-Segment ×n, Close-Upload-Sequence.

        The NC has one transfer slot; the close goes out on every exit (the ladder archive is not auto-closed).
        Verified on the machine 2026-09-26 for every file type.

        :param FileType file_type: What to read
        :param int identification: Low three bytes of the file id: programme index, ladder module
        :param float timeout: Answer wait per attempt (a large archive may need more to open)
        :returns: The file as the NC sends it, 122 bytes per segment
        :rtype: bytes
        :raises FileTransferError: A status other than 0/15, or a segment out of sequence
        """
        name = f"{FileType(file_type).name} 0x{identification:06X}"
        query = [OPEN_UPLOAD, self.category_code] + file_identification(file_type, identification)
        resp = self._answer(OPEN_UPLOAD, self.run_unite(self.link_address, query, timeout, text=f"OPEN_UPLOAD {name}"))
        status = check_file_status("OPEN_UPLOAD", resp[1], (0, 15))  # 15: programme empty
        data = bytearray()
        try:
            number = 1
            while status == 0:
                query = [READ_UPLOAD, self.category_code, *number.to_bytes(2, "little")]
                resp = self._answer(READ_UPLOAD, self.run_unite(self.link_address, query, timeout, text=f"READ_UPLOAD {name} #{number}"))
                status, segment = parse_upload_segment(resp, number)
                data += segment
                number += 1
        finally:
            self.close_upload(timeout)
        return bytes(data)

    def close_upload(self, timeout=TIMEOUT_SEC):
        """Close-Upload-Sequence (938914 §4.13.3); status 4 "already closed" is accepted.

        :returns: ``True`` if a file was open
        :rtype: bool
        """
        query = [CLOSE_UPLOAD, self.category_code]
        resp = self._answer(CLOSE_UPLOAD, self.run_unite(self.link_address, query, timeout, text="CLOSE_UPLOAD"))
        return check_file_status("CLOSE_UPLOAD", resp[1], (0, 4)) == 0

    def read_program(self, number, group=0, timeout=TIMEOUT_SEC):
        """Part programme ``%number.group`` (file type H'12'). Verified 2026-09-26.

        :rtype: bytes
        """
        return self.upload(FileType.PART_PROGRAM, program_index(number, group), timeout)

    def read_machine_parameters(self, timeout=TIMEOUT_SEC):
        """Machine parameters (file type H'05'): the ``.xpa`` text the IPC's ``UPLF 5 0 0`` saves. Verified 2026-09-26.

        :rtype: bytes
        """
        return self.upload(FileType.MACHINE_PARAMETERS, 0, timeout)

    def read_plc_archive(self, timeout=TIMEOUT_SEC):
        """All ladder and C modules (file type H'07', module type 16): the ``.xar`` of ``UPLF 7 16 0``. Verified 2026-09-26.

        :rtype: bytes
        """
        return self.upload(FileType.PLC_LADDER, PLC_ALL_MODULES << 16, timeout)

    def read_directory(self, start=0, group=0):
        """Part programmes in the NC RAM from ``%start.group`` upward (938914 §4.16), 15 per answer. Verified 2026-09-26.

        :returns: ``Program(number, group, size)`` in the NC's ascending order
        :rtype: list[Program]
        :raises OperationInProgrammeArea: Status 2, the NC is busy in the programme area
        :raises FileTransferError: Status 9 "buffer too small" or another rejection
        """
        query = [SPECIFIC_REQUEST, self.category_code, OPEN_DIRECTORY, *program_index(start, group).to_bytes(4, "little")]
        resp = self.run_unite(self.link_address, query, text=f"OPEN_DIRECTORY from %{start}.{group}")
        check_specific_answer(resp, OPEN_DIRECTORY)
        status, programs = parse_directory(resp, "OPEN_DIRECTORY")
        try:
            while status == 0:
                query = [SPECIFIC_REQUEST, self.category_code, DIRECTORY]
                resp = self.run_unite(self.link_address, query, text="DIRECTORY")
                check_specific_answer(resp, DIRECTORY)
                status, more = parse_directory(resp, "DIRECTORY")
                programs += more
        finally:
            if status == 0:  # 15 = the NC closed it itself
                self.close_directory()
        return programs

    def close_directory(self):
        """Close-Directory (938914 §4.16.3); status 4 "already closed" is accepted.

        :returns: ``True`` if a directory read was open
        :rtype: bool
        """
        query = [SPECIFIC_REQUEST, self.category_code, CLOSE_DIRECTORY]
        resp = self.run_unite(self.link_address, query, text="CLOSE_DIRECTORY")
        check_specific_answer(resp, CLOSE_DIRECTORY)
        return check_file_status("CLOSE_DIRECTORY", resp[2], (0, 4)) == 0
