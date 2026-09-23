pyunitelway for the NUM 1060
============================

A UNI-TELWAY slave client plus UNI-TE requests for the NUM 1060 Series II CNC of the IMA BIMA
Quadroform C80/280 at Makerspace Darmstadt. Fork of
`Purecontrol/pyunitelway <https://github.com/Purecontrol/pyunitelway>`_.

Status: prototype. Verified on the machine on 2026-09-22 (the frames are regression vectors in
``tests/test_hardware_vectors.py``):

* ``mirror`` - link test
* ``get_unit_identification`` - product type, version, name
* ``get_unit_status`` - NC/PLC status, programme status (segment 153), mode, programme number
* ``get_available_bytes_in_ram``
* ``read_mode`` / ``read_object`` - NC objects (938914 §4.1.3), e.g. the operating mode as ``Mode``
* ``read_ladder`` - PLC variables ``%M %V %I %Q %R %W %S`` as bit, byte, word or long word (verified on
  every segment)
* ``get_stations_managed_by_master``, ``get_unit_fault_history``

Verified live write (2026-09-22): ``write_mode`` - MANUAL and back to AUTO, read back over ``read_mode``
and ``%R16.B``. ``write_object`` for the other families and ``_write_objects`` are unit-tested only.
Verified 2026-09-23: ``write_ladder`` (a ``%W`` byte written and restored; bit and word writes on unnamed
``%V`` memory, each read back) and ``write_message`` (938914 §4.17; the NC lists it under E/A →
Fehlermeldungen → Netz-Meldungen, no acknowledgement). Not implemented: file transfer and directory requests.
``shutdown`` is untested.

Writes are locked by default: ``write_ladder``, ``write_object`` and ``write_mode`` raise ``WriteNotAllowed``
unless ``UnitelwayClient(writable={...})`` named the ladder segment (``"%W"``, where ``%W3.2`` is NC start),
the variable (``"%W16.B"``) or the NC object (``Object.MODE_SELECTION``); ``ALL_LADDER_SEGMENTS`` and
``ALL_NC_OBJECTS`` open everything.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   ./configuration.rst
   ./logging.rst
   ./client.rst
   ./num_constants.rst
   ./unite_responses.rst
   ./conversion.rst
   ./utils.rst
   ./errors.rst

Quick start
===========

::

    import logging
    from pyunitelway import UnitelwayClient

    logging.basicConfig(level=logging.INFO)
    client = UnitelwayClient()                 # link address 0x01, the one this master polls
    client.connect_socket("10.1.70.202", 8234)
    client.mirror([0x00])                      # True
    client.read_mode()                         # <Mode.AUTO: 0>
    client.read_ladder("%R1A.W")               # 9001 - the active programme
    client.get_unit_status()["nc_status"]      # {'cnc_ready': True, 'active_program': False, ...}
    client.disconnect_socket()

Scripts: ``poetry run listen`` receives only and lists the link addresses the master polls;
``poetry run test`` runs every read request plus the mode round-trip and logs the wire bytes to
``example/logs/``; ``poetry run panel`` renders the machine's operator panel (buttons, lamps, key
switch, potentiometers) from ``%I0100``-``%I0104`` / ``%Q0100``-``%Q0102``, read-only, ``--watch 1``
to refresh.

Setup
=====

PC -> USR-TCP232-306 (TCP server mode) -> RS232 -> NUM 1060 UC SII, port COMM1. NUM parameter P112
must match the serial settings and the port must be set to *"I-Port is private to PLC"*.

.. figure:: pyunitelway_setup_schema.png
   :align: center

   Tested setup - see :doc:`Configuration </configuration>`

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
