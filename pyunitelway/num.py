from enum import IntEnum

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
    LOAD = 0x000D
    UNLOAD = 0x000F


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
