"""UNI-TELWAY slave client for the NUM 1060 Series II.

Framing per Schneider 35000789, requests per NUM 938914 (UNI-TE) and 938846 §15 (ladder objects).
"""

import logging
import socket
import time

from pyunitelway.constants import *
from pyunitelway.conversion import unwrap_unite_response
from pyunitelway.errors import NoPollingWindow, UnexpectedUniteResponse
from pyunitelway.unite_responses import (
    parse_available_bytes_in_ram,
    parse_ladder_read_response,
    parse_ladder_variable,
    parse_mirror_result,
    parse_shutdown_result,
    parse_stations_managed_by_master,
    parse_unit_fault_history,
    parse_unit_identification,
    parse_unit_status,
    parse_write_result,
)
from pyunitelway.utils import (
    check_specific_answer,
    compute_bcc,
    duplicate_dle,
    format_hex_list,
    get_response_code,
    is_valid_response_code,
    ladder_specific_byte,
    sublist_in_list,
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
    """

    def __init__(self, slave_address=0x01, category_code=0x00, xway_network=0x00, xway_station=0xFE, xway_gate=0x00, xway_ext1=0x00, xway_ext2=0x00, VPN_Mode=False):
        self._unitelway_start = [DLE, STX, slave_address]
        self._xway_start = [0x20, xway_network, xway_station, xway_gate, xway_ext1, xway_ext2]  # 0x20: standard NPDU
        self.category_code = category_code
        self.link_address = slave_address
        self.VPN_Mode = VPN_Mode
        self.socket = None

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
        """Frame an X-WAY message: header, length (doubled if ``DLE``), data with ``DLE``s doubled, BCC."""
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

    # ------- receive -------

    def _wait_unite_response(self, timeout=TIMEOUT_SEC):
        """Wait for a ``<DLE><STX>`` frame addressed to us, skipping polls (35000789 §3.6).

        :returns: Received bytes from the frame start, or ``None`` on timeout
        """
        start = time.time()
        buf = []
        while True:
            r = self.socket.recv(3)
            if (not r) or (not buf and len(r) == 1 and r[0] == NAK):
                raise Exception(f"NAK received ({r!r})")
            log.debug("rx %s", format_hex_list(r))
            buf.extend(r)

            found, index = sublist_in_list(buf, [DLE, ENQ])  # TODO B3: may hit frame data
            if found:
                del buf[index:index + 3]

            found, idx = sublist_in_list(buf, [DLE, STX])
            if found:
                buf.extend(self.socket.recv(1))
                if buf[idx + 2] == self.link_address:
                    break

            if not self.VPN_Mode and time.time() - start >= timeout:
                log.warning("no answer within %.1f s", timeout)
                return None

        buf = buf[idx:]
        buf.extend(self.socket.recv(256))
        return buf

    def _unite_query_until_response(self, address, query, timeout=TIMEOUT_SEC, text=""):
        """Send a request in a polling window and wait for its answer, resending on timeout.

        :returns: Raw UNI-TELWAY answer bytes
        """
        r = None
        while r is None:
            if not self.VPN_Mode:
                self.is_my_turn_to_talk(address)
            self._unite_query(query, text)
            r = self._wait_unite_response(timeout)
            if r is None:
                log.warning("%s: resending", text)
        return r

    def run_unite(self, address, query, timeout=TIMEOUT_SEC, text=""):
        """Send a UNI-TE request and return the UNI-TE answer bytes.

        :param int address: Our link address
        :param list[int] query: UNI-TE request
        :param float timeout: Seconds to wait for the answer before resending
        :param str text: Request name for the log
        :rtype: list[int]
        :raises NoPollingWindow: The master never polled ``address``
        :raises BadUnitelwayChecksum: Bad BCC
        :raises RefusedUnitelwayMessage: X-WAY service code ``0x22``
        :raises UniteRequestFailed: UNI-TE answer ``0xFD``
        """
        r = self._unite_query_until_response(address, query, timeout, text)
        if not self.VPN_Mode:
            self._unitelway_query([ACK])  # 35000789 §3.6
        unite = unwrap_unite_response(r)
        log.info("%s -> %s", text, format_hex_list(unite))
        return unite

    def is_my_turn_to_talk(self, address, timeout=POLLING_TIMEOUT_SEC):
        """Block until the master polls ``address`` with ``<DLE><ENQ><address>`` (35000789 §3.6).

        :raises NoPollingWindow: No poll within ``timeout`` seconds
        :raises ConnectionError: The adapter closed the connection
        """
        buf = []
        start = time.time()
        self.socket.settimeout(timeout)
        try:
            while True:
                try:
                    r = self.socket.recv(3)
                except socket.timeout:
                    raise NoPollingWindow(address, timeout)
                if not r:
                    raise ConnectionError("Adapter closed the connection while waiting for a polling window")
                log.debug("rx %s", format_hex_list(r))
                buf.extend(r)
                if sublist_in_list(buf, [DLE, ENQ, address])[0]:
                    log.debug("polled at 0x%02X", address)
                    return True
                if time.time() - start >= timeout:
                    raise NoPollingWindow(address, timeout)
        finally:
            self.socket.settimeout(None)

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

    # ------- ladder variables (938914 §4.1.3.3, 938846 §15) -------

    def read_ladder(self, variable):
        """Read one ladder variable.

        :param str variable: ``%SNNNN.S`` - symbol ``%M %V %I %Q %R %W %S``, hex logical number, size
            ``.0``-``.7`` (bit), ``.B``, ``.W``, ``.L`` or ``.&``. Index fields are not supported.
        :returns: ``bool`` for a bit, signed ``int`` for ``.B``/``.W``/``.L``, address ``int`` for ``.&``
        :raises ValueError: Invalid variable
        :raises UnexpectedUniteResponse: Answer code is not ``0x66``
        :raises UnexpectedObjectTypeResponse: Echoed specific byte differs
        :raises UnexpectedDataLength: Data length does not match the size
        """
        (_symbol, segment, address, size, _index) = parse_ladder_variable(variable)
        resp = self._read_objects(segment, ladder_specific_byte(size), address, 1)
        return parse_ladder_read_response(resp, size)

    def write_ladder(self, variable, data):
        """Write a ladder variable - **not implemented**: validates ``variable`` and raises.

        .. WARNING::
            Writes are live on the machine. Trace the address with the bundle's ``trace_signal.py``
            before implementing this (see todo.md).

        :raises NotImplementedError: Always, after validating ``variable``
        """
        parse_ladder_variable(variable)
        raise NotImplementedError("write_ladder is not implemented yet (todo.md A2/A3)")

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
        # TODO A8: num_lines is a float and the data is not padded to 32 bytes per line (§4.17)
        """Display a supervisor message on the NC (§4.17). **Untested, cannot send yet.**

        :param str message: Up to 96 printable ASCII characters
        :returns: ``True`` on the positive answer
        """
        if len(message) > 96:
            raise ValueError("The message is too long. It must be 96 characters maximum.")
        num_lines = len(message) / 32
        query = [SPECIFIC_REQUEST, self.category_code, WRITE_MESSAGE, 0x00, num_lines]
        query += [ord(c) for c in message]
        resp = self.run_unite(self.link_address, query, text="WRITE_MESSAGE")
        check_specific_answer(resp, WRITE_MESSAGE, also_accept=(0xFE,))  # §4.17 says FE, the §3.6 table 7B
        return True

    def shutdown(self):
        """Shut down the PCNC PC module (938928 §10.4.10). **Untested; unknown whether a UC SII answers.**

        :returns: ``True`` if the status byte is ``0x00``
        """
        query = [SPECIFIC_REQUEST, self.category_code, SHUTDOWN, 0x00]
        resp = self.run_unite(self.link_address, query, text="SHUTDOWN")
        check_specific_answer(resp, SHUTDOWN)
        return parse_shutdown_result(resp)
