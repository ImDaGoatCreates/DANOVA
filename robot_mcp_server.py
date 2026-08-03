"""Local REST bridge for DANOVA's dual Feetech arms.

Run with: python robot_mcp_server.py
The bridge listens only on 127.0.0.1.  Discovery and connection never move an
arm; motion endpoints are deliberately explicit and range limited.
"""
from __future__ import annotations

import json
import os
from flask import Flask, jsonify, request
from robot_controller import HOME, RobotController

CONFIG_FILE = "robot_config.json"
DEFAULTS = {
    "leader_port": os.environ.get("DANOVA_LEADER_PORT", "COM12"),
    "follower_port": os.environ.get("DANOVA_FOLLOWER_PORT", "COM11"),
}


def load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            saved = json.load(f)
            return {**DEFAULTS, **{k: saved[k] for k in DEFAULTS if k in saved}}
    except (OSError, json.JSONDecodeError):
        return DEFAULTS.copy()


config = load_config()
robot = RobotController(config["leader_port"], config["follower_port"])
app = Flask(__name__)


def body():
    return request.get_json(silent=True) or {}


def fail(exc, code=400):
    return jsonify({"ok": False, "error": str(exc), "arms": robot.snapshot()}), code


@app.get("/health")
@app.get("/status")
def status():
    return jsonify({"ok": True, "arms": robot.snapshot(), "home": HOME,
                    "available_ports": robot.available_ports()})


@app.post("/configure")
def configure():
    """Persist ports and disconnect; caller must explicitly reconnect."""
    global robot, config
    data = body()
    leader, follower = data.get("leader_port"), data.get("follower_port")
    if not isinstance(leader, str) or not isinstance(follower, str):
        return fail("leader_port and follower_port are required strings")
    robot.disconnect()
    config = {"leader_port": leader.strip(), "follower_port": follower.strip()}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    robot = RobotController(**config)
    return jsonify({"ok": True, "message": "Ports saved. Call /connect to test safely.", "arms": robot.snapshot()})


@app.post("/connect")
def connect():
    data = body()
    handshake = bool(data.get("handshake", True))
    try:
        arm = data.get("target", "both")
        if arm == "both":
            robot.connect_all(handshake)
        elif arm in ("leader", "follower"):
            robot.connect(arm, handshake)
        else:
            return fail("target must be leader, follower, or both")
        return jsonify({"ok": True, "arms": robot.snapshot()})
    except Exception as exc:
        return fail(exc, 500)


@app.post("/disconnect")
def disconnect():
    robot.disconnect(body().get("target"))
    return jsonify({"ok": True, "arms": robot.snapshot()})


@app.get("/positions")
def positions():
    try:
        return jsonify({"ok": True, "positions": robot.positions(request.args.get("target", "both"))})
    except Exception as exc:
        return fail(exc)


@app.post("/move_servo")
def move_servo():
    try:
        data = body()
        robot.move_servo(data["id"], data["pos"], data.get("target", "both"))
        return jsonify({"ok": True})
    except Exception as exc:
        return fail(exc)


@app.post("/multi_move")
def multi_move():
    try:
        data = body()
        robot.move_many(data["moves"], data.get("target", "both"))
        return jsonify({"ok": True})
    except Exception as exc:
        return fail(exc)


@app.post("/home")
@app.post("/reset_arm")
def home():
    try:
        robot.home(body().get("target", "both"))
        return jsonify({"ok": True, "message": "Home command sent"})
    except Exception as exc:
        return fail(exc)


@app.post("/torque")
def torque():
    try:
        data = body()
        robot.torque(bool(data.get("enable", False)), data.get("target", "both"))
        return jsonify({"ok": True})
    except Exception as exc:
        return fail(exc)


if __name__ == "__main__":
    print("DANOVA robot bridge: http://127.0.0.1:3001/health")
    app.run(host="127.0.0.1", port=3001, debug=False)
