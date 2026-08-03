"""Safe Feetech STS arm control used by DANOVA.

Hardware is never moved during discovery.  Motion is explicitly bounded,
serialized, and requires a connected bus.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Any

try:
    from scservo_sdk import PortHandler
    from scservo_sdk.sms_sts import sms_sts, SMS_STS_TORQUE_ENABLE
    from scservo_sdk.scservo_def import COMM_SUCCESS
    HAS_DRIVER = True
except ImportError:
    PortHandler = sms_sts = None
    HAS_DRIVER = False

HOME = {1: 2048, 2: 750, 3: 3048, 4: 2850, 5: 2048, 6: 2048}
SAFE_MIN, SAFE_MAX = 300, 3700
VALID_TARGETS = {"leader", "follower", "both"}


@dataclass
class ArmStatus:
    port: str
    connected: bool = False
    error: str = "Not connected"


class RobotController:
    """Thread-safe dual-arm controller with conservative motion limits."""

    def __init__(self, leader_port: str, follower_port: str):
        self.ports = {"leader": leader_port, "follower": follower_port}
        self.buses: dict[str, Any] = {"leader": None, "follower": None}
        self.status = {name: ArmStatus(port) for name, port in self.ports.items()}
        self._lock = threading.RLock()
        self.drivers: dict[str, Any] = {"leader": None, "follower": None}

    @staticmethod
    def available_ports() -> list[dict[str, str]]:
        try:
            from serial.tools import list_ports
            return [{"device": p.device, "description": p.description or "Unknown device"}
                    for p in list_ports.comports()]
        except Exception:
            return []

    def connect(self, arm: str, handshake: bool = True) -> ArmStatus:
        if arm not in self.buses:
            raise ValueError("arm must be leader or follower")
        if not HAS_DRIVER:
            self.status[arm].error = "Feetech driver is not available"
            return self.status[arm]
        with self._lock:
            self.disconnect(arm)
            try:
                bus = PortHandler(self.ports[arm])
                if not bus.openPort():
                    raise ConnectionError(f"could not open {self.ports[arm]}")
                driver = sms_sts(bus)
                # Handshake only pings; it cannot change servo state.
                if handshake:
                    found = [sid for sid in HOME if driver.ping(sid)[1] == COMM_SUCCESS]
                    if not found:
                        bus.closePort()
                        raise ConnectionError("no STS servos responded to ping")
                self.buses[arm] = bus
                self.drivers[arm] = driver
                self.status[arm] = ArmStatus(self.ports[arm], True, "")
            except Exception as exc:
                self.buses[arm] = None
                self.drivers[arm] = None
                self.status[arm] = ArmStatus(self.ports[arm], False, f"{type(exc).__name__}: {exc}")
            return self.status[arm]

    def connect_all(self, handshake: bool = True) -> dict[str, ArmStatus]:
        return {arm: self.connect(arm, handshake) for arm in self.buses}

    def disconnect(self, arm: str | None = None) -> None:
        with self._lock:
            for name in ([arm] if arm else list(self.buses)):
                bus = self.buses.get(name)
                if bus:
                    try:
                        bus.disconnect()
                    except Exception:
                        pass
                self.buses[name] = None
                self.drivers[name] = None
                self.status[name].connected = False

    @staticmethod
    def _bounded(servo_id: int, position: Any) -> int:
        if int(servo_id) not in HOME:
            raise ValueError("servo id must be 1 through 6")
        return max(SAFE_MIN, min(SAFE_MAX, int(position)))

    @staticmethod
    def _targets(target: str) -> list[str]:
        target = (target or "both").lower()
        if target not in VALID_TARGETS:
            raise ValueError("target must be leader, follower, or both")
        return ["leader", "follower"] if target == "both" else [target]

    def _write(self, arm: str, servo_id: int, position: int) -> None:
        if not self.buses[arm] or not self.status[arm].connected:
            raise RuntimeError(f"{arm} arm is not connected")
        result, error = self.drivers[arm].WritePosEx(servo_id, position, 800, 50)
        if result != COMM_SUCCESS or error:
            raise RuntimeError(f"servo {servo_id} write failed (comm={result}, error={error})")

    def move_servo(self, servo_id: int, position: Any, target: str = "both") -> None:
        position = self._bounded(servo_id, position)
        with self._lock:
            for arm in self._targets(target):
                self._write(arm, int(servo_id), position)

    def move_many(self, moves: list[dict[str, Any]], target: str = "both") -> None:
        if not moves:
            raise ValueError("no moves supplied")
        clean = [(int(m["id"]), self._bounded(m["id"], m["pos"])) for m in moves]
        with self._lock:
            for arm in self._targets(target):
                for servo_id, position in clean:
                    self._write(arm, servo_id, position)

    def home(self, target: str = "both") -> None:
        self.move_many([{"id": i, "pos": p} for i, p in HOME.items()], target)

    def torque(self, enabled: bool, target: str = "both") -> None:
        with self._lock:
            for arm in self._targets(target):
                if not self.buses[arm] or not self.status[arm].connected:
                    raise RuntimeError(f"{arm} arm is not connected")
                for servo_id in HOME:
                    result, error = self.drivers[arm].write1ByteTxRx(
                        servo_id, SMS_STS_TORQUE_ENABLE, int(enabled))
                    if result != COMM_SUCCESS or error:
                        raise RuntimeError(f"torque write failed for servo {servo_id}")

    def positions(self, target: str = "both") -> dict[str, dict[int, int]]:
        """Read present positions; this is diagnostic-only and does not move motors."""
        readings: dict[str, dict[int, int]] = {}
        with self._lock:
            for arm in self._targets(target):
                if not self.buses[arm] or not self.status[arm].connected:
                    raise RuntimeError(f"{arm} arm is not connected")
                readings[arm] = {}
                for servo_id in HOME:
                    value, result, error = self.drivers[arm].ReadPos(servo_id)
                    if result != COMM_SUCCESS or error:
                        raise RuntimeError(f"could not read servo {servo_id} on {arm}")
                    readings[arm][servo_id] = value
        return readings

    def snapshot(self) -> dict[str, Any]:
        return {name: {"port": s.port, "connected": s.connected, "error": s.error}
                for name, s in self.status.items()}
