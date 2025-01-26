"""UNI-TELWAY client module.
Specifically modified for NUM 1060 Series II Controller
as described in the manual "NUM 1060 - USE OF THE UNI-TE PROTOCOL - en-938914/0"
"""

import socket
import time

from pyunitelway.constants import *
from pyunitelway.conversion import parse_mirror_result, parse_write_result, unwrap_unite_response, parse_unit_identification, parse_unit_status, parse_available_bytes_in_ram, parse_ladder_variable, parse_ladder_read_response, \
    parse_unit_fault_history, parse_stations_managed_by_master
from pyunitelway.errors import UnexpectedUniteResponse
from pyunitelway.num import ladder_size
from pyunitelway.utils import compute_bcc, duplicate_dle, format_bytearray, format_hex_list, get_response_code, is_valid_response_code, sublist_in_list, delete_dle, read_byte, read_int


class UnitelwayClient:
    """UNI-TELWAY slave client. To send UNI-TELWAY messages to master PLC.
    The sender PC is considered a slave, and the contacted PLC is the master.

    .. NOTE::
        In our tests, the NUM 1060 worked only with the following settings:

        * slave_address = 0x00
        * category_code = 0x00
        * xway_network = 0x00
        * xway_station = 0xFE
        * xway_gate = 0x00
        * xway_ext1 = 0x00
        * xway_ext2 = 0x00

    .. WARNING::
        Make sure that the slave address you chose for your PC is not already used by a slave PLC.
    
    :param int slave_address: Client slave address
    :param int category_code: UNI-TE category code (between 0 and 7)
    :param int xway_network: X-WAY network value
    :param int xway_station: X-WAY station value
    :param int xway_gate: X-WAY gate value
    :param int xway_ext1: X-WAY ext1 value (5-6 levels addressing)
    :param int xway_ext2: X-WAY ext2 value (5-6 levels addressing)
    :param bool VPN_Mode : Switch On if using VPN
    """

    def __init__(self, slave_address=0x01, category_code=0x00, xway_network=0x00, xway_station=0xFE, xway_gate=0x00, xway_ext1=0x00, xway_ext2=0x00, VPN_Mode=False):
        """The constructor.
        
        ``ext1`` and ``ext2`` are used for 5 and 6-levels addressing. See: https://download.schneider-electric.com/files?p_enDocType=User+guide&p_File_Name=35000789_K06_000_00.pdf&p_Doc_Ref=35000789K01000, p.55 for the format.
        """
        self._unitelway_start = [
            DLE, STX,
            slave_address
        ]

        self._xway_start = [
            0x20,  # Type: standard
            xway_network,
            xway_station,
            xway_gate,
            xway_ext1,
            xway_ext2
        ]

        self.category_code = category_code
        self.link_address = slave_address
        self.VPN_Mode = VPN_Mode

    # ------- LIBRARY SPECIFIC FUNCTIONS -------
    def connect_socket(self, ip, port, connection_query=None):
        """Connect to the USR-TCP232-306 adapter.

        A *connection query* is also needed to connect. Without this, the client is not able to talk to the PLC. But we
        still don't know how this query is built.

        If the argument ``conection_query`` is ``None`` (default), no connection query is executed.

        :param string ip: Adapter IPv4
        :param int port: Adapter port
        :param list[int] connection_query: *Connection query* bytes
        """
        print("Connecting to ip : " + ip + " on port : " + str(port))
        self.socket = socket.socket(socket.AF_INET)
        self.socket.settimeout(2)
        self.socket.connect((ip, port))
        self.socket.settimeout(None)

        if connection_query is not None:
            self._send_connection_query(connection_query)
        print("Connected to ip : " + ip + " on port : " + str(port))

    def _send_connection_query(self, connection_query):
        """Send the *connection query* on the socket.

        See ``connect_socket`` for more information.

        :param list[int] connection_query: *Connection query*
        """
        print("Sending connection query", connection_query)
        self._unitelway_query(connection_query, "Connecting to USR-TCP232-306 adapter")

    def disconnect_socket(self, debug=0):
        print("Disconnecting from socket")

        try:
            self.socket.close()
            if debug >= 2:
                print("Socket is closed")

        except:
            print("Socket is not closed")

    def _unite_to_xway(self, unite_bytes):
        """Wrap UNI-TE request into an X-WAY request.
        
        It just adds X-WAY header at the beginning. See this `UNI-TELWAY example`_ page 55 for the format.

        .. _`UNI-TELWAY example`: https://download.schneider-electric.com/files?p_enDocType=User+guide&p_File_Name=35000789_K06_000_00.pdf&p_Doc_Ref=35000789K01000

        :param list[int] unite_bytes: UNI-TE request bytes
        
        :returns: X-WAY request bytes
        :rtype: list[int]
        """
        print("client.py - _unite_to_xway func: " + '[{}]'.format(','.join(f'{i:02X}' for i in unite_bytes)), flush=True)
        xway_bytes = []
        for b in self._xway_start:
            xway_bytes.append(b)

        xway_bytes += unite_bytes
        return xway_bytes

    def _xway_to_unitelway(self, xway_bytes):
        """Wrap X-WAY request into a UNI-TELWAY request.

        It:

        * appends the header at the beginning
        * compute the length
        * duplicate ``<DLE>``'s
        * add the checksum at the end

        :param list[int] xway_bytes: X-WAY request bytes

        :returns: UNI-TELWAY request bytes
        :rtype: list[int]
        """
        print("client.py - _xway_to_unitelway func: " + '[{}]'.format(','.join(f'{i:02X}' for i in xway_bytes)), flush=True)
        unitelway_bytes = []
        for b in self._unitelway_start:
            unitelway_bytes.append(b)

        # Length
        length = len(xway_bytes)
        # Duplicate DLE if length == DLE
        if length == DLE:
            unitelway_bytes.append(DLE)
        unitelway_bytes.append(len(xway_bytes))

        unitelway_data_start = len(unitelway_bytes)

        unitelway_bytes += xway_bytes

        duplicate_dle(unitelway_bytes, unitelway_data_start)

        bcc = compute_bcc(unitelway_bytes)
        unitelway_bytes.append(bcc)

        return unitelway_bytes

    def _unite_to_unitelway(self, unite_bytes):
        """Unwrap UNI-TE request into a UNI-TELWAY request.

        It chains ``unite_to_xway`` and ``xway_to_unitelway``.

        :param list[int] unite_bytes: UNI-TE request bytes

        :returns: UNI-TELWAY request bytes
        :rtype: list[int]
        """
        print("client.py - _unite_to_unitelway func: " + '[{}]'.format(','.join(f'{i:02X}' for i in unite_bytes)), flush=True)
        xway = self._unite_to_xway(unite_bytes)
        return self._xway_to_unitelway(xway)

    def _unitelway_query(self, query, text="", debug=0):
        """Send a UNI-TELWAY request on the socket.

        .. WARNING::

            The UNI-TELWAY request has to be already built

        :param list[int] query: UNI-TELWAY request bytes
        :param str text: Text to print in debug mode
        :param int debug: :doc:`Debug mode </debug_levels>`
        """
        print("client.py - _unitelway_query func: " + '[{}]'.format(','.join(f'{i:02X}' for i in query)), flush=True)
        bytes = bytearray(query)
        if debug >= 1:
            print(f"------------------ {text} ----------------")
            print(f"[{time.time()}] Sending: {format_bytearray(bytes)}")

        n = self.socket.send(bytes)

        # if debug:
        #    print(f"[{time.time()}] Sent {n} bytes.")

    def _unite_query(self, query, text="", debug=0):
        """Send a UNI-TE request on the socket.

        .. NOTE::

            All the UNI-TELWAY request is printed

        :param list[int] query: UNI-TE request bytes
        :param str text: Text to print in debug mode
        :param int debug: :doc:`Debug mode </debug_levels>`
        """
        print("client.py - _unite_query func: " + '[{}]'.format(','.join(f'{i:02X}' for i in query)), flush=True)
        unitelway = self._unite_to_unitelway(query)
        self._unitelway_query(unitelway, text, debug)

    def _wait_unite_response(self, timeout=TIMEOUT_SEC, debug=0):
        """Wait until a UNI-TE response is received.

        This function works with ``unite_query_until_response()``.

        The master PLC regularly sends ``<DLE> <ENQ> XX`` enquery bytes. These bytes can be sent between a request from a slave
        and the response, that's why we need to wait our response.

        This function regularly reads 3 bytes on the socket while it encounters ``<DLE> <ENQ>``.
        If it receives ``<DLE> <STX>``, it reads the next 256 bytes, and return the result. 

        If the timeout is reached, it returns ``None``, then ``unite_query_until_response`` will send again the request.

        :param float timeout: Timeout before sending again the request

        :returns: Response bytes if the timeout is not reached.
            None otherwise
        :rtype: list[int] or None
        """
        print("client.py - _wait_unite_response func: " + "Waiting for response", flush=True)
        start = time.time()
        end = start
        buf = []
        while True:
            r = self.socket.recv(3)
            if (not r) or (not buf and len(r) == 1 and r[0] == 0x15):
                raise Exception("Nack received ! Force quitting... (" + str(r) + ")")
            if debug >= 2:
                print("recv =>", format_hex_list(r))
            buf.extend(b for b in r)

            # Delete <DLE> <ENQ> <nb>
            res = sublist_in_list(buf, [DLE, ENQ])
            is_in = res[0]
            index = res[1]
            if is_in:
                # Delete three elements starting at index
                for _ in range(3):
                    if index < len(buf):
                        buf.pop(index)

            # Find <DLE> <STX> sequence
            tmp = sublist_in_list(buf, [DLE, STX])
            dle_stx_ok = tmp[0]
            dle_stx_idx = tmp[1]

            if dle_stx_ok:
                buf.extend(b for b in self.socket.recv(1))
                received_link_addr = buf[dle_stx_idx + 2]
                if received_link_addr == self.link_address:
                    break

            if not self.VPN_Mode:
                end = time.time()
                if end - start >= timeout:
                    print("client.py - _wait_unite_response func: " + "Timeout reached", flush=True)
                    return None

        buf = buf[dle_stx_idx:]
        buf.extend(b for b in self.socket.recv(256))
        # print("client.py - _wait_unite_response func: " + '[{}]'.format(','.join(f'{i:02X}'for i in buf)), flush=True)
        return buf

    def _unite_query_until_response(self, address, query, timeout=TIMEOUT_SEC, text="", debug=0):
        """Send a UNI-TE request until it receives a valid response.

        This function works with ``wait_unite_response()``.

        If ``wait_unite_response`` returns ``None`` (reached timeout), it sends the request again.

        .. NOTE::

            All the UNI-TELWAY request is printed

        :param list[int] query: UNI-TE request
        :param float timeout: Timeout before sending again the request
        :param str text: Text to print in debug mode
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: UNI-TELWAY response bytes
        :rtype: list[int]
        """
        print("client.py - _unite_query_until_response func: " + '[{}]'.format(','.join(f'{i:02X}' for i in query)), flush=True)
        r = None
        while r is None:
            # Used with VPN
            if self.VPN_Mode:
                self._unite_query(query, text, debug)
                r = self._wait_unite_response(timeout, debug)
            # Used in local / must wait polling from automate
            else:
                if self.is_my_turn_to_talk(address, debug):
                    self._unite_query(query, text, debug)
                    r = self._wait_unite_response(timeout, debug)
        return r

    def run_unite(self, address, query, timeout=TIMEOUT_SEC, text="", debug=0):
        """High-level function to send UNI-TE request and get the response.

        This function uses ``unite_query_until_response()`` and ``utils.unwrap_unite_response()``. So don't use them alone.
        See ``utils.py`` for more details about ``unwrap_unite_response``.

        .. NOTE::

            All the UNI-TELWAY request and response are printed

        :param address[int] : slave address
        :param list[int] query: UNI-TE request
        :param float timeout: Timeout before sending again the request
        :param str text: Text to print in debug mode
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: UNI-TE response bytes
        :rtype: list[int]

        :raises BadUnitelwayChecksum: Received bad UNI-TELWAY checksum
        """
        r = self._unite_query_until_response(address, query, timeout, text, debug)
        if debug >= 1:
            print(f"[{time.time()}] Received:", format_hex_list(r))

        if not self.VPN_Mode:
            self._unitelway_query([ACK], debug=debug)

        # self.disconnect_socket(debug=debug)
        return unwrap_unite_response(r)

    def is_my_turn_to_talk(self, address, debug=0):
        """Allows slave to give permission to the master to communicate

        :param address[int] : slave address
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: Boolean. Slave authorized or not to communicate to master

        :raises BadUnitelwayChecksum: Received bad UNI-TELWAY checksum
        """
        print("client.py - is_my_turn_to_talk func: " + "Waiting for sending window", flush=True)
        buf = []
        is_in = False

        while True:
            r = self.socket.recv(3)
            if debug >= 1:
                print("recv =>", format_hex_list(r))

            buf.extend(b for b in r)

            res = sublist_in_list(buf, [DLE, ENQ, address])
            is_in = res[0]

            if is_in:
                break
        if debug >= 2: print("client.py - is_my_turn_to_talk func: " + "Got sending window", flush=True)
        return is_in

    ####################################
    # ACCESS TO DATA
    ####################################

    def _read_objects(self, segment, obj_type, start_address, number, debug=0):
        """Send ``READ_OBJECTS`` request.

        This function is a low-level function: it returns directly the UNI-TE response.

        :param int segment: Object segment value
        :param int obj_type: Object type value
        :param int start_address: First address to read
        :param int number: Number of objects to read
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: UNI-TE ``READ_OBJECTS`` response
        """
        print("client.py - _read_objects func: " + "Reading objects", flush=True)

        address_bytes = start_address.to_bytes(2, byteorder="little", signed=False)
        number_bytes = number.to_bytes(2, byteorder="little", signed=False)

        unite_query = [READ_OBJECTS, self.category_code, segment, obj_type]
        unite_query.extend(address_bytes)
        unite_query.extend(number_bytes)

        slave_address = self._unitelway_start[2]

        resp = self.run_unite(slave_address, unite_query, text=f"READ_OBJECTS Seg={segment} Type={obj_type} @{start_address} N={number}", debug=debug)

        if not is_valid_response_code(READ_OBJECTS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_OBJECTS), resp[0])

        return resp

    def read_objects(self, object, number, offset=0, debug=0):
        """High level abstraction function to read objects
        TODO pass object from Object Enum and automatically figure out address and return type/size

        :param Object object: Object to read
        :param Int number: Number of objects to read
        :param Int offset: TODO offset in bytes or words?
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: Requested Object in corresponding type (depending on object)
        :rtype: Any
        """
        return NotImplementedError()

    def read_ladder(self, variable, number=1, debug=0):
        # TODO untested
        """Read a ladder variable.
        Index fields are not supported yet.

        :param str variable: Ladder variable name in the format ``%SNNNN.S[I]`` with symbol S, logical number NNNN, size S and optional index I in square brackets

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

        :param int number: Number of objects to read
        :param int debug: :doc:`Debug mode </debug_levels>`
        :returns: Ladder variable value
        :rtype: Any

        :raises ValueError: Invalid symbol
        :raises ValueError: Invalid logical number
        :raises ValueError: Invalid size
        """
        print("client.py - read_ladder func: " + "Reading ladder", flush=True)

        (symbol, symbol_request, logical_number, size, index) = parse_ladder_variable(variable, debug=debug)
        num_bytes = 1 if chr(0) <= size <= chr(7) else ladder_size(size)
        resp = self.read_objects(symbol_request, num_bytes, logical_number, number, debug)

        if not is_valid_response_code(READ_OBJECTS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_OBJECTS), resp[0])
        if not resp[1] == symbol_request:
            raise UnexpectedUniteResponse(symbol_request, resp[1])

        return parse_ladder_read_response(resp, size)

    def _write_objects(self, segment, obj_type, start_address, number, data, debug=0):
        """Send ``WRITE_OBJECTS`` request.

        This function is a low-level function. It's used by ``write_xxx_bits``, ``write_xxx_words``, ``write_xxx_dwords``.

        The ``data`` argument represents the last bytes of the request.

        :param any segment: Object segment value
        :param int obj_type: Object type value
        :param int start_address: First address to write at
        :param Union(list[int], int) data: Bytes to write
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: ``True`` if the writing succeeded
        :rtype: bool
        """
        print("client.py - _write_objects func: " + "Writing objects", flush=True)

        if isinstance(data, int):
            data = [data]

        address_bytes = start_address.to_bytes(2, byteorder="little", signed=False)
        number_bytes = number.to_bytes(2, byteorder="little", signed=False)

        unite_query = [WRITE_OBJECTS, self.category_code, segment, obj_type]
        unite_query.extend(address_bytes)
        unite_query.extend(number_bytes)
        unite_query.extend(data)

        slave_address = self._unitelway_start[2]

        resp = self.run_unite(slave_address, unite_query, text=f"WRITE_OBJECTS Seg={segment} Type={obj_type} @{start_address} Values={format_hex_list(data)}", debug=debug)

        if not is_valid_response_code(WRITE_OBJECTS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(WRITE_OBJECTS), resp[0])

        return parse_write_result(resp)

    def write_objects(self, object, number, data, offset=0, debug=0):
        """High level abstraction function to write objects
        TODO pass object from Object Enum. Automatically figure out the address and if object is allowed to be written

        :param Object object: Object to read
        :param Int number: Number of objects to read
        :param Int offset: TODO offset in bytes or words?
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: Requested Object in corresponding type (depending on object)
        :rtype: Any
        """
        return NotImplementedError()

    def write_ladder(self, variable, data, number=1, debug=0):
        # TODO untested
        """Write a ladder variable.
        Index fields are not supported yet.

        .. WARNING::
            This operation is irreversible.
            It can overwrite data and it can brick the PLC.
            Be **very** careful when using this function.

        .. WARNING::
            Writing of single bits is not supported yet.

        :param str variable: Ladder variable name in the format ``%SNNNN.S[I]`` with symbol S, logical number NNNN, size S and optional index I in square brackets

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

        :param Union(int, list[int]) data: Data to write
        :param int number: Number of bytes to be written starting with the first
        :param int debug: :doc:`Debug mode </debug_levels>`
        :returns: Success of the writing
        :rtype: bool

        :raises ValueError: Invalid symbol
        :raises ValueError: Invalid logical number
        :raises ValueError: Invalid size
        :raises NotImplementedError: Writing of single bits is not supported yet
        """
        print("client.py - read_ladder func: " + "Writing ladder", flush=True)

        (symbol, symbol_request, logical_number, size, index) = parse_ladder_variable(variable, debug=debug)
        if chr(0) <= size <= chr(7):
            raise NotImplementedError("Writing of single bits is not supported yet.")
        num_bytes = 1 if chr(0) <= size <= chr(7) else ladder_size(size)
        resp = self.write_objects(symbol_request, num_bytes, logical_number, number, data, debug)

        if not is_valid_response_code(WRITE_OBJECTS, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_OBJECTS), resp[0])

        return True

    ####################################
    # GENERAL PURPOSE REQUESTS
    ####################################

    def get_unit_identification(self, debug=0):
        """Get the unit identification.

        This request sends a ``Unit Identification`` request and returns the response.
        The response contains "product_type", "subtype", "product_version" and "text".

        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: Unit identification dict containing "product_type", "subtype", "product_version" and "text".
        :rtype: dict[str: Any]

        :raises UniteRequestFailed: Received ``0xFD``
        """
        print("client.py - get_unit_identification func: " + "Getting unit identification", flush=True)
        unite_query = [IDENTIFICATION, self.category_code]
        slave_address = self._unitelway_start[2]

        resp = self.run_unite(slave_address, unite_query, text="GET_UNIT_IDENTIFICATION", debug=debug)
        if not is_valid_response_code(IDENTIFICATION, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(IDENTIFICATION), resp[0])

        return parse_unit_identification(resp)

    def get_unit_status(self, axis_group_index=0, debug=0):
        """Get the unit status.

        This request sends a ``Unit Status Data`` request and returns the response.

        :param int axis_group_index: Desired axis group index
        :param int debug: :doc:`Debug mode </debug_levels>`
        :returns: Unit status bytes
        :rtype: dict[str: Any]

        :raises UniteRequestFailed: Received ``0xFD``
        """
        print("client.py - get_unit_status func: " + "Getting unit status", flush=True)
        unite_query = [STATUS, self.category_code, axis_group_index]
        slave_address = self._unitelway_start[2]
        r = self.run_unite(slave_address, unite_query, text="GET_UNIT_STATUS", debug=debug)
        # # r = [97, 0, 48, 2, 9, 17, 17, 144, 95, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 1, 0, 0, 40, 35, 2, 0, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255] # with auto? and tool 600
        # # r = [97, 0, 48, 2, 9, 17, 17, 144, 95, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 1, 2, 0, 40, 35, 2, 0, 0, 0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255] # with mdi and tool 603

        if not is_valid_response_code(STATUS, r[0]):
            raise UnexpectedUniteResponse(get_response_code(STATUS), r[0])

        return parse_unit_status(r)

    ####################################
    # COMMUNICATION INTERFACE REQUESTS
    ####################################

    def mirror(self, data, debug=0):
        """Test connection with ``MIRROR`` request.

        This request sends a bunch of data and checks if the received message contains the same data.
        If data are the same: return ``True``, else ``False``.

        :param list[int] data: Data to send in the request
        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: ``True`` if the received data is the same as the sent data
        :rtype: bool

        :raises BadUnitelwayChecksum: Bad UNI-TELWAY checksum
        :raises RefusedUnitelwayMessage: X-WAY type code == ``0x22``
        :raises UniteRequestFailed: Received ``0xFD``
        :raises UnexpectedUniteResponse: The response code is not ``MIRROR``'s response code
        """
        print("client.py - mirror func: " + '[{}]'.format(','.join(f'{i:02X}' for i in data)), flush=True)
        unite_query = [MIRROR, self.category_code, *data]
        slave_address = self._unitelway_start[2]

        resp = self.run_unite(slave_address, unite_query, text="MIRROR", debug=debug)

        if not is_valid_response_code(MIRROR, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(MIRROR), resp[0])

        return parse_mirror_result(resp[1:], data)

    def get_unit_fault_history(self, debug=0):
        """Get the link fault counters (character errors, frame errors, protocol errors)

        ..NOTE: Each error counter can count up to 0x7FFF and then freezes. There is no overflow. The counters can be reset manually.

        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: quadrouple of:
            * number of messages sent and not acknowledged,
            * number of messages sent and rejected,
            * number of messages received and not acknowledged,
            * number of messages received and rejected.
        :rtype: (int, int, int, int)
        """
        print("client.py - get unit fault history", flush=True)
        unite_query = [READ_CPT, self.category_code]
        slave_address = self._unitelway_start[2]

        resp = self.run_unite(slave_address, unite_query, text="Get Unit Fault History", debug=debug)

        if not is_valid_response_code(READ_CPT, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_CPT), resp[0])

        return parse_unit_fault_history(resp)

    def get_stations_managed_by_master(self, debug=0):
        """The Etat-Station request returns the number of stations connected to the master and their status.

        :param int debug: :doc:`Debug mode </debug_levels>`

        :returns: number of stations managed and their status (connected/unconnected as list of bool)
        :rtype: (int, list[bool])
        """
        print("client.py - get number of stations managed by master", flush=True)
        unite_query = [ETAT_STATION, self.category_code]
        slave_address = self._unitelway_start[2]

        resp = self.run_unite(slave_address, unite_query, text="Get Number of Stations managed by Master", debug=debug)

        if not is_valid_response_code(ETAT_STATION, resp[0]):
            raise UnexpectedUniteResponse(get_response_code(ETAT_STATION), resp[0])

        return parse_stations_managed_by_master(resp)

    # TODO CLEAR_CPT

    ####################################
    # FILE TRANSFERS
    ####################################

    # TODO OPEN DOWNLOAD

    # TODO WRITE DOWNLOAD

    # TODO CLOSE DOWNLOAD

    # TODO OPEN UPLOAD

    # TODO WRITE UPLOAD

    # TODO CLOSE UPLOAD

    ####################################
    # SPECIFIC REQUESTS
    ####################################

    def get_available_bytes_in_ram(self, debug=0):
        """Get the available bytes in RAM.

        This request sends a ``Reading the Number of Bytes Available in the RAM`` request and returns the response.

        :param int debug: :doc:`Debug mode </debug_levels>`
        :returns: Available bytes in RAM
        :rtype: int

        :raises OperationInProgrammeArea: Operation in the programme area
        :raises UniteRequestFailed: Received ``0xFD``
        :raises UnexpectedAdditionalAwnserCode: Unexpected additional answer code
        """
        print("client.py - get_available_bytes_in_ram func: " + "Getting available bytes in RAM", flush=True)
        unite_query = [READ_MEMORY_FREE, self.category_code, 0x47]
        slave_address = self._unitelway_start[2]
        r = self.run_unite(slave_address, unite_query, text="GET_AVAILABLE_BYTES_IN_RAM", debug=debug)

        if not is_valid_response_code(READ_MEMORY_FREE, r[0]):
            raise UnexpectedUniteResponse(get_response_code(READ_MEMORY_FREE), r[0])

        return parse_available_bytes_in_ram(r)

    # TODO OPEN DIRECTORY

    # TODO DIRECTORY

    # TODO CLOSE DIRECTORY

    def write_message(self, message, debug=0):
        # TODO untested
        """Send a message by supervisor.

        This request sends a ``Send Message by Supervisor`` request and returns the response.

        :param str message: Message to send, 96 characters maximum
        :param int debug: :doc:`Debug mode </debug_levels>`
        :returns: Sending success
        :rtype: bool

        :raises UniteRequestFailed: Received ``0xFD``
        """
        print("client.py - send_message_by_supervisor func: " + "Sending message by supervisor", flush=True)

        if len(message) > 96:
            raise ValueError("The message is too long. It must be 96 characters maximum.")
        num_lines = len(message) / 32

        unite_query = [WRITE_MESSAGE, self.category_code, 0x4B, 0x00, num_lines]
        unite_query.extend([ord(c) for c in message])
        slave_address = self._unitelway_start[2]
        r = self.run_unite(slave_address, unite_query, text="SEND_MESSAGE_BY_SUPERVISOR", debug=debug)

        if not is_valid_response_code(WRITE_MESSAGE, r[:1]):
            raise UnexpectedUniteResponse(get_response_code(WRITE_MESSAGE), r[0])

        return True

    def shutdown(self, debug=0):
        # TODO untested
        """Shutdown the PLC.

        This request sends a ``Shutdown`` request and returns the response.

        :param int debug: :doc:`Debug mode </debug_levels>`
        :returns: Shutdown success
        :rtype: bool

        :raises UniteRequestFailed: Received ``0xFD``
        """
        print("client.py - shutdown func: " + "Shutting down the PLC", flush=True)
        unite_query = [SHUTDOWN, self.category_code, 0x66, 0x00]
        slave_address = self._unitelway_start[2]
        r = self.run_unite(slave_address, unite_query, text="SHUTDOWN", debug=debug)

        # TODO check multiple response bits, not just one
        if not is_valid_response_code(SHUTDOWN, r[0]):
            raise UnexpectedUniteResponse(get_response_code(SHUTDOWN), r[0])
