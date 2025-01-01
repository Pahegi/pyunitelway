from pyexpat.errors import messages

from pyunitelway import UnitelwayClient, constants

slave_address = 0x01

client = UnitelwayClient(slave_address, 0x00, 0x00, 0xFE, 0x00, 0x00, 0x00)
# client.connect_socket("10.1.70.9", 8234)
client.connect_socket("127.0.0.1", 8234)

# mirror requesst
# print(client.mirror([0x00], 2))

# unit identification
# print(client.get_unit_identification(2))

# get unit status data
status = client.get_unit_status(2)
print(status)
print(status["nc_mode"])

# get number of bytes available in NC RAM
# print(client.get_available_bytes_in_ram(2))

# send message by the supervisor
# print(client.send_message_by_supervisor("Hello World!", 2))


# # read object request (mode)
# korrekte Anfrage:
# # 10 02 01 0e 20 00 fe 00 00 00 36 00 b4 00 00 00 01 00 2a
# abstrahierte Anfragen:
#   10 02 01 0a 20 00 fe 00 00 00 05 00 36 00 76 system
#   10 02 01 0a 20 00 fe 00 00 00 06 00 36 00 77 internal
#   10 02 01 0a 20 00 fe 00 00 00 04 00 36 00 75 constant
#   alle abstrahierten lesemethoden falsch
# message = []
# message.append(0x36) # request code
# message.append(0x00) # category code
# message.append(0xb4) # segment (object address)
# message.append(0x00) # size of plc object
# message.append(0x00) # address of object in family (simple offset?) 1
# message.append(0x00) # address of object in family (simple offset?) 2
# message.append(0x01) # number of objects to read (bytes) 1
# message.append(0x00) # number of objects to read (bytes) 2
#
# r = client.run_unite(slave_address, message, 0x02, "read current mode" , 1)
# print(r) # 102 is answer, second byte is insignificant, third and fourth byte is mode

# # read object request (current programme number)
# r = client.read_internal_word(0x36, 1)
#

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
#
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