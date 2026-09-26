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
``%V`` memory, each read back), ``write_message`` (938914 §4.17; the NC lists it under E/A →
Fehlermeldungen → Netz-Meldungen, no acknowledgement) and a ``%Q`` output: ``write_vacuum_pump(True)`` writes
``%Q0700.6`` and starts the vacuum pump, ``False`` stops it (the coolant pump runs with it); ``read_vacuum_pump``.
Built the same way but not yet sent: ``write_extraction_hood`` (``%Q0100.3``, ``False`` lowers the hood),
``write_long_workpiece`` (``%Q0100.4``) and ``write_wide_workpiece`` (``%Q0101.4``), each with a ``read_`` twin. File reading (938914 §4.13/§4.16) verified on the machine 2026-09-26:
``read_directory``, ``read_program``, ``read_machine_parameters``, ``read_plc_archive`` (bytes; the NC's single
transfer slot is closed in every case - the ladder archive is the one type the NC does not close itself), driven by
``poetry run backup``. No download, no Delete-File.
``cycle_start`` (UNI-TE Run, 938914 §4.9: CYCLE START in the current mode, ``False`` on the NC's refusal) was
verified 2026-09-26 in MDI: a ``G4 F2`` dwell ran, a ``G0 X2000`` block moved the machine; ``read_cycle_in_progress``
reads ``%R3.2`` E_CYCLE. ``cycle_stop`` (UNI-TE Stop, 938914 §4.10: the CYHLD machining stop, the spindle keeps turning,
``cycle_start`` resumes; alias ``feed_stop``) was verified the same evening; ``read_cycle_stopped`` reads ``%R3.1`` E_ARUS.
``shutdown`` is untested.

Writes are locked by default: ``write_ladder``, ``write_object`` and ``write_mode`` raise ``WriteNotAllowed``
unless ``UnitelwayClient(writable={...})`` named the ladder segment (``"%W"``, where ``%W3.2`` is NC start),
the variable (``"%W16.B"``) or the NC object (``Object.MODE_SELECTION``); ``ALL_LADDER_SEGMENTS`` and
``ALL_NC_OBJECTS`` open everything except ``cycle_start``, which needs ``Action.CYCLE_START`` named explicitly.

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
``poetry run test`` is a minimal tour of every request (the mode round-trip, a scratch byte on unnamed ``%V``
memory and a screen message are its only writes); ``poetry run panel`` renders the machine's operator panel (buttons, lamps, key
switch, potentiometers) from ``%I0100``-``%I0104`` / ``%Q0100``-``%Q0102``, read-only, ``--watch 1``
to refresh; ``poetry run backup`` writes a full backup (every part programme, the machine parameters, the PLC
archive) into ``example/backup/<timestamp>/``.

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
