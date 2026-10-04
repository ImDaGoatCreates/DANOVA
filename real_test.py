import serial
import time

ser = serial.Serial("COM12", 115200, timeout=1)

print("Connected to serial")


packet = bytearray([
    0xFF, 0xFF,        # header
    0x01,              # ID = 1
    0x07,              # length
    0x03,              # WRITE instruction
    0x2A,              # Goal Position address (LOW)
    0xB8, 0x0B,        # 3000 (little endian)
    0x00               # checksum placeholder
])

packet[-1] = (~sum(packet[2:-1])) & 0xFF

print("Sending raw packet:", packet)

ser.write(packet)

time.sleep(1)
ser.close()