import time
from DANOVA_AI import FeetechMotorsBus, Motor

motors = {
    "joint1": Motor(id=1, model="sts3215", norm_mode="position"),
}

bus = FeetechMotorsBus(port="COM4", motors=motors)
bus.connect(handshake=False)

print("CONNECTED")

# 🔴 STEP 1 — READ POSITION (proves communication)
try:
    pos = bus.read("Present_Position", 1)
    print("READ OK, position:", pos)
except Exception as e:
    print("READ FAILED:", e)

# 🔴 STEP 2 — HARD TORQUE ON
try:
    bus.write("Torque_Enable", 1, 1)
    print("TORQUE ON SENT")
except Exception as e:
    print("TORQUE FAIL:", e)

time.sleep(1)

# 🔴 STEP 3 — SPAM ALL POSSIBLE POSITION REGISTERS
print("FORCING MOVEMENT...")

for reg in [
    "Goal_Position",
    "goal_position",
    "Position",
    "GoalPosition"
]:
    try:
        print(f"Trying {reg}...")
        bus.write(reg, 1, 3000)
        time.sleep(1)
    except Exception as e:
        print(f"{reg} failed:", e)

print("DONE")