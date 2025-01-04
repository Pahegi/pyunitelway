from pyunitelway import UnitelwayClient
from pyunitelway.num import Object, Mode

debug = 0

client = UnitelwayClient()
client.connect_socket("10.1.70.9", 8234)
# client.connect_socket("127.0.0.1", 8234)  # used for debug mockup server

# mirror request
# print(client.mirror([0x00], debug))  # returns true if mirror request was successful (basically ping num 1060)

# unit identification
# print(client.get_unit_identification(debug))  # returns type of unit (e.g. NUM 1060 UC SII)

# get unit status data
# print(client.get_unit_status(debug))  # returns status data (e.g. current mode, program number, active G-code, etc.)

# get number of bytes available in NC RAM
# print(client.get_available_bytes_in_ram(debug))

# send message by the supervisor
# print(client.write_message("Hello World!", debug))  # sends message to network messages menu

# read object request (mode)
# print(client._read_objects(Object.MODE_SELECTION, 0x00, 0x00, 0x01))  # returns current mode

# write object request (mode)
print(client._write_objects(Object.MODE_SELECTION, 0x00, 0x00, 0x01, [Mode.AUTO, 0x00]))  # sets mode to MDI

# print(client.get_stations_managed_by_master())
# print(client.get_unit_fault_history())

# read ladder
# print(client.read_ladder("%R5.1"))  # program active
# print(client.read_ladder("%R16.B"))  # current mode
# print(client.read_ladder("%R1A.W"))  # active program number
# print(client.read_ladder("%R14.1"))  # battery status
# print(client.read_ladder("%R17.B"))  # displayed page number
# print(client.read_ladder("%R18.B"))  # machine error number

# write ladder
# print(client.write_ladder("%W3.2", 0x01))  # cycle start set (needs reset)
# print(client.write_ladder("%W3.2", 0x00))  # cycle start reset
#
# print(client.write_ladder("%W3.1", 0x01))  # cycle stop set (needs reset)
# print(client.write_ladder("%W3.1", 0x00))  # cycle stop reset
#
# print(client.write_ladder("%W3.0", 0x01))  # reset request
#
# print(client.write_ladder("%W15.B", 210))  # output message N210 $ Werkzeug-Nr. falsch gewaehlt

# tests

# read ladder
# client.read_ladder("%MA.0")

# write object request (mode)
# _write_objects:    [10,02,01,0F,20,00,FE,00,00,00,37,00,B4,00,00,00,01,00,02,2E]
# custom:         [10,02,01,10,10,20,00,FE,00,00,00,37,00,B4,00,00,00,01,00,02,00,44]
# # write mode request
# message = []
# message.append(0x37) # request code
# message.append(0x00) # category code
# message.append(0xb4) # segment (object address)
# message.append(0x00) # size of plc object
# message.append(0x00) # address of object in family (simple offset?) 1
# message.append(0x00) # address of object in family (simple offset?) 2
# message.append(0x01) # number of objects to read (bytes) 1
# message.append(0x00) # number of objects to read (bytes) 2
# message.append(0x07) # mode 1 (0 for auto, 7 for manual)
# message.append(0x00) # mode 2

# r = client.run_unite(slave_address, message, 0x02, "write current mode" , 1)
# print(r)


# # file download test
# message = []
# message.append(0x3a) # request code
# message.append(0x00) # category code
# message.append(0x06) # file type code
# message.append(0x41) # additional identification 1
# message.append(0x00) # additional identification 2 not significant for text files
# message.append(0x00) # additional identification 3 not significant for text files
# message.append(0x00) # additional identification 4 not significant for text files
# message.append(0x01) # extension code
# filename = "9002.0"
# for c in filename:
#     message.append(ord(c))
# r = client.run_unite(slave_address, message, 0x02, "file download test" , 1)
# print(r)
#
# # transfer segment
#
#
# # close file download
# message = []
# message.append(0x3c) # request code
# message.append(0x00) # category code
# r = client.run_unite(slave_address, message, 0x02, "close file download" , 1)
# print(r)


client.disconnect_socket()
