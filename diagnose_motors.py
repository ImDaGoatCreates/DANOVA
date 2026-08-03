#!/usr/bin/env python
"""
Diagnostic script to test motor connectivity on COM11/COM12
Run this on Windows to identify the connection issue
"""
import serial
import serial.tools.list_ports
import time
import sys

print("=" * 70)
print("DANOVA MOTOR CONNECTIVITY DIAGNOSTIC")
print("=" * 70)

# 1. List available ports
print("\n[1/5] Available COM Ports:")
ports = list(serial.tools.list_ports.comports())
if ports:
    for p in ports:
        print(f"      {p.device}: {p.description}")
else:
    print("      (no ports found)")

# 2. Test COM12
print("\n[2/5] Testing COM12 Port Access:")
com11_ok = False
try:
    ser = serial.Serial('COM12', 1000000, timeout=2)
    print(f"      ✓ COM12 opened at 1M baud")
    com11_ok = True
    
    # 3. Try motor ping (Feetech protocol)
    print("\n[3/5] Sending Motor Ping (Feetech STS3215):")
    # Feetech Ping packet: FF FF ID LEN CMD CHECKSUM
    # For broadcast ping: FF FF FE 02 01 FC
    ping_packet = bytes([0xFF, 0xFF, 0xFE, 0x02, 0x01, 0xFC])
    
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    print(f"      Sending: {ping_packet.hex().upper()}")
    ser.write(ping_packet)
    time.sleep(0.5)
    
    response = ser.read(100)
    if response:
        print(f"      ✓ RESPONSE RECEIVED: {response.hex().upper()}")
        print(f"        ({len(response)} bytes)")
    else:
        print(f"      ✗ No response from motors (timeout)")
    
    # 4. Try single motor ping (ID 1)
    print("\n[4/5] Sending Single Motor Ping (ID 1):")
    ping_single = bytes([0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB])
    
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    
    print(f"      Sending: {ping_single.hex().upper()}")
    ser.write(ping_single)
    time.sleep(0.5)
    
    response = ser.read(100)
    if response:
        print(f"      ✓ RESPONSE RECEIVED: {response.hex().upper()}")
        print(f"        ({len(response)} bytes)")
    else:
        print(f"      ✗ No response from motor ID 1")
    
    ser.close()
    
except Exception as e:
    print(f"      ✗ Failed to open COM11: {e}")

# 5. Test COM12
print("\n[5/5] Testing COM11 Port Access:")
try:
    ser = serial.Serial('COM11', 1000000, timeout=1)
    print(f"      ✓ COM11 opened at 1M baud")
    ser.close()
except Exception as e:
    print(f"      ✗ Failed to open COM11: {e}")

# Summary
print("\n" + "=" * 70)
print("DIAGNOSIS SUMMARY:")
if com11_ok:
    print("  ✓ COM11 port is accessible")
    print("  → If motors didn't respond, they may not be powered on")
    print("  → Check LED indicators on the motor boards")
else:
    print("  ✗ COM3 port cannot be opened")
    print("  → Verify USB cable connections")
    print("  → Check Device Manager for serial port conflicts")

print("=" * 70)
