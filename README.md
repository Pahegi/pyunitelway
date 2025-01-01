# Pyunitelway NUM 1060

This is a fork of the original [Pyunitelway](https://github.com/Purecontrol/pyunitelway) library adapted to work with the NUM 1060.

This library allows to:

* Send and receive mirror requests
* Query unit identification
* Query unit status data
* Query available memory
* Send supervisor messages
* Read and write objects

## How to use ?

This library is designed to use a TCP-RS485 adapter. The adapter is connected to the PC or server which uses this lib via Ethernet or Wi-fi or anything else, and is connected to the NUM 1060 via RS232 on port COMM1 at the UC SII. Parameter P112 has to be configured accordingly and the port has to be changed to "I-Port is private to PLC".

This library was developed using the USR-TCP232-306 adapter. It was not tested with another kind of connection.

![Setup explanation](docs/source/pyunitelway_setup_schema.png)

*Test setup*