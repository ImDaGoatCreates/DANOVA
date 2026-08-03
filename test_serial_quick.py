import serial
import time
import sys

print("Testing COM3/COM4 serial communication...")

for port in ['COM3', 'COM4']:
    print(f"\n{'='*50}")
    print(f"Testing {port}")
    print(f"{'='*50}")
    
    try:
        print(f"1. Opening {port} at 1M baud...")
        ser = serial.Serial(port, 1000000, timeout=1, write_timeout=1)
        print(f"   ✓ Opened successfully")
        
        print(f"2. Flushing buffers...")
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        time.sleep(0.1)
        
        print(f"3. Writing 10x 0xFF bytes...")
        bytes_written = ser.write(b'\xFF' * 10)
        print(f"   ✓ Wrote {bytes_written} bytes")
        
        print(f"4. Waiting 0.5s for response...")
        time.sleep(0.5)
        
        print(f"5. Checking if data is waiting...")
        data_waiting = ser.in_waiting
        print(f"   Bytes in buffer: {data_waiting}")
        
        if data_waiting > 0:
            print(f"6. Reading response...")
            response = ser.read(min(data_waiting, 100))
            print(f"   ✓ Response ({len(response)} bytes): {response.hex().upper()}")
        else:
            print(f"6. No response data")
        
        print(f"7. Closing port...")
        ser.close()
        print(f"   ✓ Closed")
        
    except serial.SerialException as e:
        print(f"   ✗ Serial Error: {e}")
    except Exception as e:
        print(f"   ✗ Error: {type(e).__name__}: {e}")

print(f"\n{'='*50}")
print("Test complete")
print(f"{'='*50}")
