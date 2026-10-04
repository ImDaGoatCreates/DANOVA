"""
Advanced motor connectivity test - simulates lerobot connection
Run on Windows to test different connection strategies
"""
import sys
sys.path.insert(0, r'C:\Users\hudso\AppData\Roaming\Python\Python311\site-packages')

try:
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
    from lerobot.motors import Motor
    print("✓ lerobot imported successfully\n")
except ImportError as e:
    print(f"✗ Failed to import lerobot: {e}")
    sys.exit(1)

import threading
import time

motors_config = {
    "joint1": Motor(id=1, model="sts3215", norm_mode="position"),
    "joint2": Motor(id=2, model="sts3215", norm_mode="position"),
    "joint3": Motor(id=3, model="sts3215", norm_mode="position"),
    "joint4": Motor(id=4, model="sts3215", norm_mode="position"),
    "joint6": Motor(id=6, model="sts3215", norm_mode="position"),
}

def test_connection(port, label, handshake=True, timeout=10):
    """Test motor connection with specified parameters"""
    print(f"\n{'='*70}")
    print(f"TEST: {label}")
    print(f"  Port: {port}")
    print(f"  Handshake: {handshake}")
    print(f"  Timeout: {timeout}s")
    print(f"{'='*70}")
    
    result = {"success": False, "message": "", "time": 0}
    start = time.time()
    
    def do_test():
        try:
            print(f"  [1/3] Creating FeetechMotorsBus...")
            bus = FeetechMotorsBus(port=port, motors=motors_config)
            
            print(f"  [2/3] Connecting to {port} (handshake={handshake})...")
            bus.connect(handshake=handshake)
            
            print(f"  [3/3] Verifying connection status...")
            if bus.is_connected:
                print(f"  ✓ CONNECTED")
                result["success"] = True
                result["message"] = "Connection successful"
            else:
                print(f"  ✗ Port open but connection failed")
                result["message"] = "Port opened but not connected"
                
            bus.disconnect()
            
        except TimeoutError as e:
            result["message"] = f"Timeout: {e}"
            print(f"  ✗ {e}")
        except ConnectionError as e:
            result["message"] = f"Connection Error: {e}"
            print(f"  ✗ {e}")
        except Exception as e:
            result["message"] = f"Exception: {type(e).__name__}: {e}"
            print(f"  ✗ {type(e).__name__}: {e}")
    
    test_thread = threading.Thread(target=do_test, daemon=True)
    test_thread.start()
    test_thread.join(timeout=timeout + 2)
    
    result["time"] = time.time() - start
    
    if not result["success"] and result["time"] >= timeout:
        result["message"] = f"Timed out after {result['time']:.1f}s"
    
    print(f"\n  Result: {'✓ SUCCESS' if result['success'] else '✗ FAILED'}")
    print(f"  Message: {result['message']}")
    print(f"  Time: {result['time']:.1f}s")
    
    return result

print("\nDNOVA MOTOR CONNECTION DIAGNOSTIC")
print("Testing different connection strategies...\n")

results = []

results.append(test_connection("COM3", "COM3 with Handshake (motor verification)", handshake=True, timeout=10))

results.append(test_connection("COM3", "COM3 without Handshake (skip motor verification)", handshake=False, timeout=10))

results.append(test_connection("COM4", "COM4 with Handshake (Follower Arm)", handshake=True, timeout=10))

print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
for i, r in enumerate(results, 1):
    status = "✓ PASS" if r["success"] else "✗ FAIL"
    print(f"{i}. {status} - {r['message']} ({r['time']:.1f}s)")

print(f"\n{'='*70}")
if any(r["success"] for r in results):
    print("✓ At least one connection method succeeded!")
    print("  Use that method in DANOVA_AI.py")
else:
    print("✗ All connection methods failed")
    print("  Check:")
    print("  - Motors are powered on (check LED indicators)")
    print("  - USB cables are connected (COM3/COM4 appear in Device Manager)")
    print("  - Baud rate matches motor settings (should be 1M)")
print(f"{'='*70}\n")
