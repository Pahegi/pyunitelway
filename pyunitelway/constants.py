# Wait times (in ms)
# Took from doc: https://download.schneider-electric.com/files?p_enDocType=User+guide&p_File_Name=35000789_K06_000_00.pdf&p_Doc_Ref=35000789K01000

TBIT = 1 / 9600 * 1000
ICT = 2000
TRET_MIN = 10 * TBIT
TRET_MAX = ICT

TERT_MIN = 150  # TEST

TIMEOUT_SEC = 2  # Time between message sent and received in second
POLLING_TIMEOUT_SEC = 10  # Max wait for the master's <DLE><ENQ><addr> poll before giving up
MAX_RETRIES = 3  # send + wait attempts per request before NoUniteResponse

# Special chars
DLE = 0x10
STX = 0x02
ENQ = 0x05
ACK = 0x06
NAK = 0x15

# Category types
TYPE_TSX = 7

# Request codes
READ_OBJECTS = 0x36
WRITE_OBJECTS = 0x37
UNSOLICITED_DATA = 0xFC
IDENTIFICATION = 0x0F
STATUS = 0x31
MIRROR = 0xFA
READ_CPT = 0xA2
ETAT_STATION = 0xA3
CLEAR_CPT = 0xA4
OPEN_DOWNLOAD = 0x3A
WRITE_DOWNLOAD = 0x3B
CLOSE_DOWNLOAD = 0x3C
OPEN_UPLOAD = 0x3D
WRITE_UPLOAD = 0x3E
CLOSE_UPLOAD = 0x3F

# NUM specific requests (938914 §3.6; 938928 §10.4): request H'F5' + additional request code,
# answer H'F5' + additional answer code (= request code + 0x30), then status/data
SPECIFIC_REQUEST = 0xF5

DELETE_FILE = 0x46
READ_MEMORY_FREE = 0x47
OPEN_DIRECTORY = 0x48
DIRECTORY = 0x49
CLOSE_DIRECTORY = 0x4A
WRITE_MESSAGE = 0x4B
STOP_AUTOMATE = 0x4C
INIT_AUTOMATE = 0x4D
RUN_AUTOMATE = 0x4F
START_APPLI = 0x65  # 938928 §10.4.11, PCNC server only
SHUTDOWN = 0x66  # 938928 §10.4.10, PCNC server only

ADDITIONAL_ANSWER_CODES = {
    DELETE_FILE: 0x76,
    READ_MEMORY_FREE: 0x77,
    OPEN_DIRECTORY: 0x78,
    DIRECTORY: 0x79,
    CLOSE_DIRECTORY: 0x7A,
    WRITE_MESSAGE: 0x7B,  # §3.6 table; the §4.17 body says H'FE' - client.write_message accepts both
    STOP_AUTOMATE: 0x7C,
    INIT_AUTOMATE: 0x7D,
    RUN_AUTOMATE: 0x7F,
    START_APPLI: 0x95,
    SHUTDOWN: 0x96,
}

# Response codes
RESPONSE_CODES = {
    READ_OBJECTS: 0x66,
    WRITE_OBJECTS: 0xFE,
    IDENTIFICATION: 0x3F,
    STATUS: 0x61,
    MIRROR: 0xFB,
    READ_CPT: 0xD2,
    ETAT_STATION: 0xD3,
    CLEAR_CPT: 0xFE,
    OPEN_DOWNLOAD: 0x6A,
    WRITE_DOWNLOAD: 0x6B,
    CLOSE_DOWNLOAD: 0x6C,
    OPEN_UPLOAD: 0x6D,
    WRITE_UPLOAD: 0x6E,
    CLOSE_UPLOAD: 0x6F,
    SPECIFIC_REQUEST: 0xF5,  # then check ADDITIONAL_ANSWER_CODES (utils.check_specific_answer)
}

# Ladder adresses
LADDER_REQUEST = {
    "%M": 0xA1,
    "%V": 0xA0,
    "%I": 0xA8,
    "%Q": 0xA9,
    "%R": 0xA4,
    "%W": 0xA5,
    "%S": 0xA2
}
