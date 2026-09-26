from enum import IntEnum
from typing import NamedTuple

symbol_bounds = {
    "%M": 0x77FF,
    "%V": 0x7FFF,
    "%I": 0x6F3F,
    "%Q": 0x6F3F,
    "%R": 0x0F7F,
    "%W": 0x0F7F,
    "%S": 0x3F7F
}

ladder_size = {
    "B": 1,
    "W": 2,
    "L": 4,
    "&": 4
}

# 938914 §4.1.3.3: specific byte = object size (a bit uses its own number 0-7)
ladder_specific = {
    "B": 64,
    "W": 65,
    "L": 66,
    "&": 66
}

# 938914 §4.1.3.3 footnotes: max low byte of the address
symbol_low_byte_max = {
    "%R": 0x7F,
    "%W": 0x7F,
    "%I": 0x3F,
    "%Q": 0x3F
}

class Mode(IntEnum):
    AUTO = 0x0000
    SINGLE_STEP = 0x0001
    MDI = 0x0002
    DRYRUN = 0x0003
    SEQUENCE_NUMBER_SEARCH = 0x0004
    EDIT = 0x0005
    TEST = 0x0006
    MANUAL = 0x0007
    HOMING = 0x0008
    SHIFT = 0x0009
    TOOL_SET = 0x000A
    NONE = 0x000B  # 938846 §3.8.1.9: no mode active
    LOAD = 0x000D
    UNLOAD = 0x000F
    INDEPENDENT_GROUPS = 0x0010  # 938846 §3.8.1.9


class Object(IntEnum):
    AXIS_POSITION_REFERENCE = 0x80
    AXIS_MEASUREMENT = 0x81
    AXIS_DAT1_VALUES = 0x82
    AXIS_DAT2_VALUES = 0x83
    AXIS_DAT3_VALUES = 0x84
    MINIMUM_DYNAMIC_AXIS_TRAVEL = 0x85
    MAXIMUM_DYNAMIC_AXIS_TRAVEL = 0x86
    INCLINED_AXIS_ANGULAR_VALUE = 0x87
    MACHINE_ZERO_POINT = 0x88
    MINIMUM_STATIC_TRAVEL = 0x89
    MAXIMUM_STATIC_TRAVEL = 0x8A
    CURRENT_CORRECTIONS_SLAVE_AXIS = 0x8B
    AXIS_POSITION_REFERENCE_AXISWISE = 0x8C
    AXIS_MEASUREMENT_AXISWISE = 0x8D
    DRIVEN_AXES = 0x8F
    MEASURED_SPINDLE_SPEED_SETTING = 0x90
    MEASURED_SPINDLE_REFERENCE_POSITION = 0x91
    TOOL_CORRECTIONS = 0x92
    H_VARIABLE_DYNAMIC_CORRECTORS = 0x93
    INTERPOLATION_STATUS = 0x94
    HOMING_NOT_DONE_ON_AXES = 0x95
    LOCAL_DATA_PARAMETERS_E = 0x96
    MASTER_AXIS_REFERENCE_POSITION_INTERAXIS_CALIBRATION = 0x97
    SLAVE_AXIS_CORRECTION_INTERAXIS_CALIBRATION = 0x98
    PROGRAMME_STATUS = 0x99
    BLOCK_END_DIMENSIONS = 0x9D
    MODE_SELECTION = 0xB4
    CURRENT_PROGRAMME_NUMBER = 0xB5
    DATA_TRANSMITTED_TO_PROGRAMME_BEING_EXECUTED = 0xE0
    ACKNOWLEDGEMENT_OF_BLOCKING_MESSAGE = 0xE2  # $11 or $22


ALL_NC_OBJECTS = frozenset(Object)  # for UnitelwayClient(writable=...)


class Action(IntEnum):
    """Requests that make the machine act and are locked like writes (``UnitelwayClient(writable={Action.CYCLE_START})``).
    On purpose outside ``ALL_NC_OBJECTS`` and ``ALL_LADDER_SEGMENTS``."""
    CYCLE_START = 0x24  # UNI-TE Run (938914 §4.9): CYCLE START in the current mode, past the ladder's start memory
    CYCLE_STOP = 0x25  # UNI-TE Stop (938914 §4.10 "FEED STOP"): the CYHLD machining stop, the spindle keeps turning
    FEED_STOP = 0x25  # alias: the request's name in 938914
    WRITE_PROGRAM = 0x3A  # Open-Download-Sequence (938914 §4.12): store a part programme in the NC RAM
    DELETE_PROGRAM = 0x46  # Delete-File (938914 §4.14, F5/46): remove a part programme from the NC RAM


class ObjectSpec(NamedTuple):
    size: int  # bytes per object
    writable: bool  # "accessible for write", 938914 §4.1.3
    kind: str  # int (signed) | mode | longs (list of signed long words) | raw


# 938914 §4.1.3
OBJECT_SPEC = {
    Object.AXIS_POSITION_REFERENCE: ObjectSpec(36, False, "longs"),
    Object.AXIS_MEASUREMENT: ObjectSpec(36, False, "longs"),
    Object.AXIS_DAT1_VALUES: ObjectSpec(36, True, "longs"),
    Object.AXIS_DAT2_VALUES: ObjectSpec(36, True, "longs"),
    Object.AXIS_DAT3_VALUES: ObjectSpec(36, True, "longs"),
    Object.MINIMUM_DYNAMIC_AXIS_TRAVEL: ObjectSpec(36, True, "longs"),
    Object.MAXIMUM_DYNAMIC_AXIS_TRAVEL: ObjectSpec(36, True, "longs"),
    Object.INCLINED_AXIS_ANGULAR_VALUE: ObjectSpec(4, True, "int"),
    Object.MACHINE_ZERO_POINT: ObjectSpec(4, True, "int"),
    Object.MINIMUM_STATIC_TRAVEL: ObjectSpec(4, True, "int"),
    Object.MAXIMUM_STATIC_TRAVEL: ObjectSpec(4, True, "int"),
    Object.CURRENT_CORRECTIONS_SLAVE_AXIS: ObjectSpec(4, False, "int"),
    Object.AXIS_POSITION_REFERENCE_AXISWISE: ObjectSpec(4, False, "int"),
    Object.AXIS_MEASUREMENT_AXISWISE: ObjectSpec(4, False, "int"),
    Object.DRIVEN_AXES: ObjectSpec(4, False, "int"),
    Object.MEASURED_SPINDLE_SPEED_SETTING: ObjectSpec(4, False, "int"),
    Object.MEASURED_SPINDLE_REFERENCE_POSITION: ObjectSpec(4, False, "int"),
    Object.TOOL_CORRECTIONS: ObjectSpec(28, False, "longs"),
    Object.H_VARIABLE_DYNAMIC_CORRECTORS: ObjectSpec(4, True, "int"),  # first object at address 1
    Object.INTERPOLATION_STATUS: ObjectSpec(16, False, "longs"),
    Object.HOMING_NOT_DONE_ON_AXES: ObjectSpec(4, True, "int"),
    Object.LOCAL_DATA_PARAMETERS_E: ObjectSpec(4, True, "int"),  # E800xx
    Object.MASTER_AXIS_REFERENCE_POSITION_INTERAXIS_CALIBRATION: ObjectSpec(4, True, "int"),
    Object.SLAVE_AXIS_CORRECTION_INTERAXIS_CALIBRATION: ObjectSpec(4, True, "int"),
    Object.PROGRAMME_STATUS: ObjectSpec(22, False, "raw"),
    Object.BLOCK_END_DIMENSIONS: ObjectSpec(44, False, "longs"),
    Object.MODE_SELECTION: ObjectSpec(2, True, "mode"),
    Object.CURRENT_PROGRAMME_NUMBER: ObjectSpec(2, True, "int"),
    Object.DATA_TRANSMITTED_TO_PROGRAMME_BEING_EXECUTED: ObjectSpec(4, True, "int"),
}


# ------- IMA BIMA Quadroform C80/280: ladder addresses of this machine (SPS.md, trace_signal.py) -------

VACUUM_PUMP = "%Q0700.6"  # QK_VakpEin__ "KR Vakuumpumpe einschalten": pump contactor, set/reset by the panel key (%SP24/00)
# panel lamps that double as the state latch: set/reset by the key, no cyclic coil
EXTRACTION_HOOD = "%Q0100.3"  # QLBABFSAKT "Absaugung Frässpindel": on = hood lifted per M200-M203 (%SP43/04), off = hood down
LONG_WORKPIECE = "%Q0100.4"  # QLBL_WKEIN "Langes Werkstück": long-part clamping, stops, E40028 (%SP30/00, /03)
WIDE_WORKPIECE = "%Q0101.4"  # QLBB_WKEIN "Überbreites Werkstück": key %I0102.4, %SP44/01; magazine side in %SP44/02-03
CYCLE_STOPPED = "%R3.1"  # E_ARUS "Cycle stop" (938846 §3.8.1): CYHLD held; the NC-Stopp lamp %Q0100.0 follows it (%SP11/08)
CYCLE_IN_PROGRESS = "%R3.2"  # E_CYCLE "Cycle in progress" (938846 §3.8.1)
NC_START = "%W3.2"  # AZYKLUS = C_CYCLE "CYCLE START pulse" (938846 §3.8.2): %SP11/03 coil; a direct write skips the start memory


class FileType(IntEnum):
    """File types (938914 §4.12.1, §4.13.1): the high byte of the file identification."""
    AXIS_CALIBRATION = 0x02
    MACROS = 0x03
    MACHINE_PARAMETERS = 0x05
    PLC_ASSEMBLER = 0x06
    PLC_LADDER = 0x07
    PART_PROGRAM = 0x12


PLC_ALL_MODULES = 16  # ladder module type "all ladder and C modules" (938914 §4.13.1; the IPC's UPLF 7 16 0)


def program_index(number, group=0):
    """Programme number indexed by the axis group: number × 10 + group (938914 §4.13.4.1)."""
    if not 0 <= group <= 9 or number < 0:
        raise ValueError(f"%{number}.{group} is not a programme name")
    return number * 10 + group


class Program(NamedTuple):
    """A part programme in the NC RAM, as the directory lists it (938914 §4.16.1)."""
    number: int
    group: int
    size: int

    @classmethod
    def from_index(cls, index, size):
        return cls(index // 10, index % 10, size)

    @property
    def name(self):
        return f"%{self.number}.{self.group}"


# Programme numbers write_program and delete_program never touch: IMA's own programmes below %9000 (2023 NCDat backup
# and the directory); %9000 upward (9001 active programme, 9997 Verrechnungen, ...) is refused by range.
PROGRAM_NUMBER_MAX = 8999
IMA_PROGRAM_NUMBERS = frozenset({5, 6, 8, 9, 10, 11, 12, 14, 30, 31, 32, 33, 34, 35, 81, 83, 85, 86, 89, 91, 92, 93, 95,
                                 97, 98, 100, 101, 111, 602, 603, 609})
