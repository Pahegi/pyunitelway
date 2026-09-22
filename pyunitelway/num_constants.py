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
    ACKNOWLEDGEMENT_OF_BLOCKING_MESSAGE = 0xE2  #$11 or $22


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
