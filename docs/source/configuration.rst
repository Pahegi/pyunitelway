USR-TCP232-306 configuration
============================

This library is designed to use the USR-TCP232-306 TCP to RS485 adapter.
The USR-TCP232-306 must be configured as a TCP server.
The serial settings have to be set according to the configuration of the NUM 1060 in P112.
This is normally:

* 19200 baud
* 1 start bit
* 1 stop bid
* odd parity
* INTEL Format.

.. figure:: pyunitelway_setup_schema.png
   :align: center

   Tested setup

