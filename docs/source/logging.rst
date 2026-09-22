Logging
=======

The library logs through the standard ``logging`` module, logger name ``pyunitelway.client``.
There are no ``debug`` parameters any more.

* ``INFO`` - one line per exchange: the request and the decoded UNI-TE answer bytes
* ``DEBUG`` - every byte sent and received, polls seen, ACKs
* ``WARNING`` - answer timeouts and resends

Minimal setup::

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

``example/test.py`` shows a console at ``INFO`` plus a file at ``DEBUG``.

Example (``INFO``)::

    pyunitelway.client: MIRROR -> fb 00
    pyunitelway.client: READ_OBJECTS seg=0xA4 spec=65 @0x001A n=1 -> 66 41 29 23

Example (``DEBUG``, same request)::

    pyunitelway.client: rx 10 05 01
    pyunitelway.client: polled at 0x01
    pyunitelway.client: tx READ_OBJECTS seg=0xA4 spec=65 @0x001A n=1 10 02 01 0e 20 00 fe 00 00 00 36 00 a4 41 1a 00 01 00 75
    pyunitelway.client: rx 06
    pyunitelway.client: rx 10 02 01
    pyunitelway.client: tx 06
    pyunitelway.client: READ_OBJECTS seg=0xA4 spec=65 @0x001A n=1 -> 66 41 29 23
