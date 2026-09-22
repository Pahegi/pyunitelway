USR-TCP232-306 configuration
============================

The USR-TCP232-306 TCP-to-serial adapter is configured as a TCP server; its serial side goes to
port COMM1 of the NUM 1060 UC SII over RS232. The serial settings must match NUM parameter P112,
normally:

* 19200 baud
* 1 start bit
* 1 stop bit
* odd parity
* INTEL format

The master polls one link address on this machine, ``0x01`` - check with ``poetry run listen``
before changing ``UnitelwayClient(slave_address=...)``.

.. figure:: pyunitelway_setup_schema.png
   :align: center

   Tested setup
