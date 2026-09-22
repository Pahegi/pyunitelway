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
* ``read_ladder`` - PLC variables ``%M %V %I %Q %R %W %S`` as bit, byte, word or long word
* ``get_stations_managed_by_master``, ``get_unit_fault_history``

Live writes, unit-tested only: ``write_mode`` / ``write_object`` (setting the mode was verified
earlier), ``_write_objects``. Not implemented: ``write_ladder`` (raises), ``write_message`` (cannot
send yet), file transfer and directory requests. ``shutdown`` is untested.

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
``poetry run test`` runs every read-only request and logs the wire bytes to ``example/logs/``.

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
