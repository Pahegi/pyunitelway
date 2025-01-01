from enum import Enum

class Mode(Enum):
    AUTO = 0x00
    SINGLE_STEP = 0x01
    MDI = 0x02
    DRYRUN = 0x03
    SEQUENCE_NUMBER_SEARCH = 0x04
    EDIT = 0x05
    TEST = 0x06
    MANUAL = 0x07
    HOMING = 0x08
    SHIFT = 0x09
    TOOL_SET = 0x0A
    LOAD = 0x0D
    UNLOAD = 0x0F