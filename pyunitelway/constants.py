# Wait times (in ms)
# Took from doc: https://download.schneider-electric.com/files?p_enDocType=User+guide&p_File_Name=35000789_K06_000_00.pdf&p_Doc_Ref=35000789K01000
from enum import Enum

TBIT = 1 / 9600 * 1000
ICT = 2000
TRET_MIN = 10 * TBIT
TRET_MAX = ICT

TERT_MIN = 150 # TEST

TIMEOUT_SEC = 2 # Time between message sent and received in second

# Special chars
DLE = 0x10
STX = 0x02
ENQ = 0x05
ACK = 0x06

# Category types
TYPE_TSX = 7

# Request codes
MIRROR = 0xFA
IDENTIFICATION = 0x0F
STATUS = 0x31
AVAILABLE_RAM = 0xF5
SEND_MESSAGE = 0xF5
UNSOLICITED_DATA = 0xFC

READ_INTERNAL_BIT = 0x00
READ_SYSTEM_BIT = 0x01
READ_INTERNAL_WORD = 0x04
READ_SYSTEM_WORD = 0x06
READ_CONSTANT_WORD = 0x05
READ_INTERNAL_DWORD = 0x40
READ_CONSTANT_DWORD = 0x41
READ_OBJECTS = 0x36

#Answer codes 

READ_INTERNAL_BIT_ANSWER = 0x30
READ_INTERNAL_WORD_ANSWER = 0x34
READ_INTERNAL_DWORD_ANSWER = 0x70
READ_CONSTANT_DWORD_ANSWER = 0x35
READ_SYSTEM_BIT_ANSWER = 0x31
READ_SYSTEM_WORD_ANSWER = 0x36

#READ_DIGITAL_MODULE_IMAGE = 0x49
READ_IO_CHANNEL = 0x43

WRITE_INTERNAL_BIT = 0x10
WRITE_SYSTEM_BIT = 0x11
WRITE_INTERNAL_WORD = 0x14
WRITE_SYSTEM_WORD = 0x15
WRITE_INTERNAL_DWORD = 0x46
WRITE_OBJECTS = 0x37
WRITE_IO_CHANNEL = 0x48

# Response codes
# For reading requests: response = request code + 0x30
# For mirror request: response = 0xFB
# For writing requests: response = 0xFE
RESPONSE_CODES = {
    MIRROR: 0xFB,
    IDENTIFICATION: 0x3F,
    AVAILABLE_RAM: [0xF5, 0x77],
    SEND_MESSAGE: 0xFE,
    STATUS: 0x61,
    WRITE_INTERNAL_BIT: 0xFE,
    WRITE_SYSTEM_BIT: 0xFE,
    WRITE_INTERNAL_WORD: 0xFE,
    WRITE_SYSTEM_WORD: 0xFE,
    WRITE_INTERNAL_DWORD: 0xFE,
    WRITE_OBJECTS: 0xFE,
}

# READ_OBJECT_ADDRESSES = {
#     AXIS_POSITION_REFERENCE: 0x80,
#     AXIS_MEASUREMENT: 0x81,
#
# }