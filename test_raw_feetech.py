#!/usr/bin/env python
"""
Raw Feetech motor test - bypasses lerobot entirely
Tests if motors respond to basic Feetech protocol commands
"""
import serial
import time

def test_raw_feetech():
    print("="*70)
    print("RAW FEETECH MOTOR TEST (No lerobot)")
    print("="*70)
    
    for port in ['COM3', 'COM4']:
        print(f"\n[{port}] Testing raw Feetech communication")
        print("-" * 70)
        
        try:
            # Open port
            print(f"  1. Opening {port} at 1M baud...")
            ser = serial.Serial(port, 1000000, timeout=0.5, write_timeout=0.5)
            print(f"     ✓ Success")
            
            # Clear buffers
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Test 1: Broadcast ping
            print(f"  2. Sending broadcast PING...")
            ping = bytes([0xFF, 0xFF, 0xFE, 0x02, 0x01, 0xFC])
            ser.write(ping)
            time.sleep(0.2)
            
            resp1 = ser.read(100)
            if resp1:
                print(f"     ✓ Response: {resp1.hex().upper()} ({len(resp1)} bytes)")
            else:
                print(f"     ✗ No response")
            
            # Test 2: Ping ID 1
            print(f"  3. Sending PING to motor ID=1...")
            ping_id1 = bytes([0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB])
            ser.reset_input_buffer()
            ser.write(ping_id1)
            time.sleep(0.2)
            
            resp2 = ser.read(100)
            if resp2:
                print(f"     ✓ Response: {resp2.hex().upper()} ({len(resp2)} bytes)")
            else:
                print(f"     ✗ No response")
            
            # Test 3: Read motor model (Address 0x03, Length 2)
            print(f"  4. Sending READ MODEL command to ID=1...")
            read_model = bytes([0xFF, 0xFF, 0x01, 0x04, 0x02, 0x03, 0x02, 0xF8])
            ser.reset_input_buffer()
            ser.write(read_model)
            time.sleep(0.2)
            
            resp3 = ser.read(100)
            if resp3:
                print(f"     ✓ Response: {resp3.hex().upper()} ({len(resp3)} bytes)")
            else:
                print(f"     ✗ No response")
            
            ser.close()
            print(f"  ✓ {port} test complete\n")
            
        except Exception as e:
            print(f"     ✗ Error: {e}\n")

if __name__ == '__main__':
    test_raw_feetech()
    
    print("="*70)
    print("ANALYSIS")
    print("="*70)
    print("""
If you see responses:
  ✓ Motors ARE responding to Feetech protocol
  → Problem is with lerobot's initialization/handshake
  
If you see NO responses:
  ✗ Motors are NOT responding on these ports
  → Check if motors are on different COM ports
  → Check if Phospho uses different baud rate
  → Verify power and cables
""")
