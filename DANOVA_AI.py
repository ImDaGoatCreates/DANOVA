"""
D.A.N.O.V.A. – local Jarvis‑style assistant with pure voice loop interaction.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

import cv2
import geocoder
import requests
import speech_recognition as sr
from flask import Flask, jsonify, request

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# External modules
from robot_controller import HOME, RobotController
from danova_core import AuditLog, PiperSpeaker

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".ultralytics"))
MEMORY_FILE = ROOT / "DANOVA_memory.json"
PROMPT_FILE = ROOT / "DANOVA_system_prompt.txt"
UPLOAD_DIR = ROOT / "uploads"
DEFAULT_LEADER_PORT = os.environ.get("DANOVA_LEADER_PORT", "COM12")
DEFAULT_FOLLOWER_PORT = os.environ.get("DANOVA_FOLLOWER_PORT", "COM11")
MODEL = os.environ.get("DANOVA_MODEL", "openai/gpt-oss-20b")

# Dedicated download path
DOWNLOADS_DIR = Path(os.environ.get("USERPROFILE", "C:\\Users\\hudso")) / "Downloads"

ENDPOINTS = [
    os.environ.get("DANOVA_LLM_API_URL"),
    "http://127.0.0.1:1234/v1/chat/completions",
]
VISION_MODEL = ROOT / "yolov8n.pt"
YOLO26_DETECT_MODEL = ROOT / "yolo26n.pt"
YOLO26_POSE_MODEL = ROOT / "yolo26n-pose.pt"
HAND_MODEL = ROOT / "hand_landmarker.task"
SNAPSHOT_DIR = ROOT / "snapshots"
WAKE_WORDS_PATTERN = re.compile(
    r"\b(dan|danova|dan\s*ova|dan\s*nova|dan\s*over|dan\s*off\s*a|dan\s*of\s*a|than)\b",
    re.IGNORECASE
)

# Common Application Launch Aliases
APP_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "notepad": "notepad",
    "text editor": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "file explorer": "explorer",
    "explorer": "explorer",
    "my computer": "explorer",
    "cmd": "cmd",
    "terminal": "cmd",
    "command prompt": "cmd",
    "edge": "msedge",
    "ms edge": "msedge",
    "browser": "msedge",
}


# ------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------
def load_memory() -> list[dict]:
    try:
        raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return [
            x if isinstance(x, dict) else {"role": "assistant", "content": str(x)}
            for x in raw
        ]
    except (OSError, json.JSONDecodeError):
        return []

def sanitize_voice_text(text: str) -> str:
    """Strips all characters except letters, numbers, spaces, and allowed punctuation: . , ' : ; ( )"""
    # Remove markdown code blocks first
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    
    # Remove all symbols EXCEPT a-z, A-Z, 0-9, spaces, and allowed punctuation: . , ' : ; ( )
    text = re.sub(r"[^a-zA-Z0-9\s.,':;()]", "", text)
    
    # Collapse extra whitespace
    return re.sub(r"\s+", " ", text).strip()

def extract_wake_word_command(text: str) -> str | None:
    match = WAKE_WORDS_PATTERN.search(text)
    if not match:
        return None
    command = text[match.end():].strip()
    return command if command else ""


def save_turn(user: str, assistant: str) -> None:
    memory = load_memory()[-78:]
    stamp = datetime.now().isoformat(timespec="seconds")
    memory += [
        {"role": "user", "content": user, "time": stamp},
        {"role": "assistant", "content": assistant, "time": stamp},
    ]
    temp = MEMORY_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(memory, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(MEMORY_FILE)


def system_prompt() -> str:
    try:
        return PROMPT_FILE.read_text(encoding="utf-8")
    except OSError:
        return "You are D.A.N.O.V.A., a helpful voice desktop assistant."


def endpoint() -> str | None:
    for url in dict.fromkeys(x.rstrip("/") for x in ENDPOINTS if x):
        try:
            if requests.get(url.rsplit("/v1/", 1)[0] + "/v1/models", timeout=2).ok:
                return url
        except requests.RequestException:
            pass
    return None


def open_app(app_name: str) -> str:
    """Launches local system applications by name or matching target."""
    clean_name = app_name.lower().strip()
    target = APP_ALIASES.get(clean_name, clean_name)

    try:
        if platform.system() == "Windows":
            os.system(f"start {target}")
        elif platform.system() == "Darwin":  # macOS
            subprocess.Popen(["open", "-a", target])
        else:  # Linux
            subprocess.Popen([target])
        return f"Opening {app_name}."
    except Exception as e:
        return f"Failed to launch {app_name}. Error: {e}"


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extracts code blocks and suggested filenames from Markdown text."""
    pattern = re.compile(r"```(?P<lang>[\w+-]+)?\n(?P<code>.*?)```", re.DOTALL)
    blocks = []
    for match in pattern.finditer(text):
        lang = match.group("lang") or "txt"
        code = match.group("code")
        ext_map = {"python": "py", "py": "py", "cpp": "cpp", "c": "c", "json": "json", "html": "html", "javascript": "js", "js": "js"}
        ext = ext_map.get(lang.lower(), "txt")
        filename = f"generated_output_{int(time.time())}.{ext}"
        blocks.append((filename, code))
    return blocks


# ------------------------------------------------------------------
# Speech Thread Worker
# ------------------------------------------------------------------
class STTThread(threading.Thread):
    def __init__(self, q: queue.Queue[str]):
        super().__init__(daemon=True)
        self.q = q
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        self.running = True

    def stop(self):
        self.running = False

    def run(self):
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        while self.running:
            try:
                with self.microphone as source:
                    audio = self.recognizer.listen(
                        source, timeout=3, phrase_time_limit=10
                    )
                text = self.recognizer.recognize_google(audio)
                if text:
                    self.q.put(text)
            except sr.WaitTimeoutError:
                continue
            except Exception:
                pass


# ------------------------------------------------------------------
# AI Worker Thread
# ------------------------------------------------------------------
class AssistantWorker(QThread):
    completed = pyqtSignal(str, str)

    def __init__(self, user_text: str, vision_context: str = ""):
        super().__init__()
        self.user_text = user_text
        self.vision_context = vision_context

    def run(self):
        messages = [{"role": "system", "content": system_prompt()}]

        messages += [
            {"role": x.get("role", "assistant"), "content": x.get("content", "")}
            for x in load_memory()[-16:]
            if x.get("content")
        ]

        context = (
            f"\n\nLive camera context: {self.vision_context}"
            if self.vision_context
            else ""
        )

        messages.append({"role": "user", "content": self.user_text + context})

        url = endpoint()

        if not url:
            self.completed.emit(
                self.user_text,
                "I cannot reach the local language model.",
            )
            return

        try:
            response = requests.post(
                url,
                json={"model": MODEL, "messages": messages, "temperature": 0.6},
                timeout=500,
            )

            response.raise_for_status()
            data = response.json()

            if "choices" in data:
                text = data["choices"][0]["message"]["content"].strip()
            elif "message" in data and "content" in data["message"]:
                text = data["message"]["content"].strip()
            elif "response" in data:
                text = data["response"].strip()
            else:
                text = "I received an unexpected response format."

        except Exception:
            text = "The language model returned an error."

        self.completed.emit(self.user_text, text)


# ------------------------------------------------------------------
# Scene Analyzer & Vision Thread
# ------------------------------------------------------------------
class SceneAnalyzer:
    def __init__(self, objects: bool, poses: bool, hands: bool):
        from ultralytics import YOLO

        self.object_model = (
            YOLO(
                str(
                    YOLO26_DETECT_MODEL
                    if YOLO26_DETECT_MODEL.exists()
                    else VISION_MODEL
                )
            )
            if objects
            else None
        )
        self.pose_model = (
            YOLO(str(YOLO26_POSE_MODEL))
            if poses and YOLO26_POSE_MODEL.exists()
            else None
        )
        self.hand_landmarker = None
        self.wrist_history = []

        if hands and HAND_MODEL.exists():
            try:
                import mediapipe as mp
                from mediapipe.tasks import python
                from mediapipe.tasks.python import vision

                options = vision.HandLandmarkerOptions(
                    base_options=python.BaseOptions(model_asset_path=str(HAND_MODEL)),
                    running_mode=vision.RunningMode.IMAGE,
                    num_hands=2,
                    min_hand_detection_confidence=0.55,
                )
                self.hand_landmarker = vision.HandLandmarker.create_from_options(
                    options
                )
                self.mp = mp
            except Exception:
                pass

    @staticmethod
    def _visible(points, *indices):
        return all(len(points) > i and points[i][2] >= 0.4 for i in indices)

    def _body_gestures(self, pose_result, width, height):
        gestures = []
        if (
            pose_result is None
            or pose_result.keypoints is None
            or pose_result.keypoints.data is None
        ):
            return gestures
        for raw_person in pose_result.keypoints.data.cpu().tolist()[:2]:
            person = [[p[0] / width, p[1] / height, p[2]] for p in raw_person]
            if self._visible(person, 5, 6, 9, 10):
                left_up = person[9][1] < person[5][1]
                right_up = person[10][1] < person[6][1]
                if left_up and right_up:
                    gestures.append("both hands raised")
                elif left_up:
                    gestures.append("left hand raised")
                elif right_up:
                    gestures.append("right hand raised")

                shoulder_span = abs(person[5][0] - person[6][0])
                wrist_span = abs(person[9][0] - person[10][0])
                level = (
                    abs(person[9][1] - person[5][1]) + abs(person[10][1] - person[6][1])
                )
                if shoulder_span and wrist_span > shoulder_span * 1.7 and level < 0.16:
                    gestures.append("T-pose")
                cross_distance = (
                    abs(person[9][0] - person[6][0]) + abs(person[10][0] - person[5][0])
                )
                if cross_distance < max(0.20, shoulder_span * 1.5):
                    gestures.append("arms crossed")

                raised_x = (
                    person[9][0] if left_up else None,
                    person[10][0] if right_up else None,
                )
                self.wrist_history.append(raised_x)

        self.wrist_history = self.wrist_history[-12:]
        for hand_index in (0, 1):
            series = [
                p[hand_index] for p in self.wrist_history if p[hand_index] is not None
            ]
            if len(series) >= 6 and max(series) - min(series) > 0.11:
                gestures.append("waving")
                break
        return gestures

    @staticmethod
    def _hand_gesture(landmarks):
        extended = [
            landmarks[8].y < landmarks[6].y,
            landmarks[12].y < landmarks[10].y,
            landmarks[16].y < landmarks[14].y,
            landmarks[20].y < landmarks[18].y,
        ]
        count = sum(extended)
        thumb_up = landmarks[4].y < landmarks[3].y < landmarks[2].y
        if count >= 4:
            return "open palm"
        if count <= 1 and not thumb_up:
            return "closed fist"
        if extended[0] and count == 1:
            return "pointing"
        if extended[0] and extended[1] and count == 2:
            return "peace sign"
        if thumb_up and count <= 1:
            return "thumbs up"
        return "hand visible"

    def analyze(self, frame):
        labels, gestures, person = [], [], False
        if self.object_model:
            result = self.object_model(frame, verbose=False, imgsz=416)[0]
            for box in result.boxes:
                if float(box.conf[0]) >= 0.45:
                    label = result.names[int(box.cls[0])]
                    labels.append(f"{label} {float(box.conf[0]):.0%}")
                    person = person or label == "person"
        if self.pose_model:
            gestures.extend(
                self._body_gestures(
                    self.pose_model(frame, verbose=False, imgsz=416)[0],
                    frame.shape[1],
                    frame.shape[0],
                )
            )
        if self.hand_landmarker:
            rgb = frame[:, :, ::-1]
            result = self.hand_landmarker.detect(
                self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
            )
            gestures.extend(self._hand_gesture(hand) for hand in result.hand_landmarks)
        return labels[:8], list(dict.fromkeys(gestures))[:5], person

    def close(self):
        if self.hand_landmarker:
            self.hand_landmarker.close()


# ------------------------------------------------------------------
# Main GUI Window
# ------------------------------------------------------------------
class JarvisWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.robot = RobotController(DEFAULT_LEADER_PORT, DEFAULT_FOLLOWER_PORT)
        self.speaker = PiperSpeaker()
        self.vision_context = "Camera offline"
        self.person_detected = False

        self.location: dict | None = None
        self.cached_weather: str = "Weather data unavailable."
        self.file_context: str = ""
        self.last_ai_response: str = ""

        self.setWindowTitle("D.A.N.O.V.A. // VOICE CONSOLE")
        self.resize(850, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self._build_ui(central_widget)

        self.refresh_status()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(2500)

        self._start_gps_updates()
        self._start_upload_server()

    def _build_ui(self, central_widget):
        root = QVBoxLayout(central_widget)

        title = QLabel("D.A.N.O.V.A.  |  Voice Assistant Console")
        title.setStyleSheet("font-size:17px; font-weight:bold; color:#51d8ff;")
        root.addWidget(title)

        top_bar = QHBoxLayout()
        self.status_label = QLabel("STATUS: Passive Listening Active")
        self.status_label.setStyleSheet("font-size:14px; color:#00ffcc; font-weight:bold;")
        top_bar.addWidget(self.status_label)
        root.addLayout(top_bar)

        content = QHBoxLayout()

        # Camera View & Controls
        vision = QWidget()
        vision_layout = QVBoxLayout(vision)
        vision_layout.addWidget(QLabel("VISION // LOCAL CAMERA"))
        self.camera_view = QLabel("Camera is off")
        self.camera_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_view.setMinimumSize(320, 240)
        self.camera_view.setStyleSheet(
            "background:#080b10; color:#7a9aae; border:1px solid #294355;"
        )
        vision_layout.addWidget(self.camera_view)

        self.vision_status = QLabel("Camera offline")
        self.vision_status.setWordWrap(True)
        vision_layout.addWidget(self.vision_status)

        vision_row = QHBoxLayout()
        vision_row.addWidget(QLabel("Camera"))
        self.camera_index = QLineEdit("0")
        self.camera_index.setMaximumWidth(45)
        vision_row.addWidget(self.camera_index)
        self.detector_box = QCheckBox("Object detection")
        self.detector_box.setChecked(True)
        vision_row.addWidget(self.detector_box)
        vision_layout.addLayout(vision_row)

        self.start_camera_btn = QPushButton("Start camera")
        self.start_camera_btn.clicked.connect(self.start_camera)
        self.stop_camera_btn = QPushButton("Stop camera")
        self.stop_camera_btn.clicked.connect(self.stop_camera)

        vision_layout.addWidget(self.start_camera_btn)
        vision_layout.addWidget(self.stop_camera_btn)
        vision_layout.addStretch()

        content.addWidget(vision, 2)

        # Controls & File Workspace Panel
        panel = QWidget()
        controls = QVBoxLayout(panel)
        controls.addWidget(QLabel("FILE WORKSPACE & ROBOTICS"))
        
        # File operations
        file_box = QHBoxLayout()
        self.upload_btn = QPushButton("Upload File Context")
        self.upload_btn.clicked.connect(self.select_file)
        self.save_btn = QPushButton("Save AI Code to Downloads")
        self.save_btn.clicked.connect(self.save_extracted_file)
        file_box.addWidget(self.upload_btn)
        file_box.addWidget(self.save_btn)
        controls.addLayout(file_box)

        self.file_label = QLabel("No file loaded.")
        self.file_label.setStyleSheet("color: #7a9aae; font-size: 11px;")
        controls.addWidget(self.file_label)

        self.robot_status = QLabel()
        self.robot_status.setWordWrap(True)
        controls.addWidget(self.robot_status)

        ports = QGridLayout()
        ports.addWidget(QLabel("Leader"), 0, 0)
        self.leader_port = QLineEdit(DEFAULT_LEADER_PORT)
        ports.addWidget(self.leader_port, 0, 1)
        ports.addWidget(QLabel("Follower"), 1, 0)
        self.follower_port = QLineEdit(DEFAULT_FOLLOWER_PORT)
        ports.addWidget(self.follower_port, 1, 1)
        controls.addLayout(ports)

        for label, method in [
            ("Connect & verify", self.connect_arms),
            ("Safe home", self.home_arms),
            ("Torque OFF", lambda: self.set_torque(False)),
            ("Torque ON", lambda: self.set_torque(True)),
        ]:
            button = QPushButton(label)
            button.clicked.connect(method)
            controls.addWidget(button)

        controls.addStretch()
        content.addWidget(panel, 2)
        root.addLayout(content)

    def select_file(self):
        """Allows users to select a file and load its contents into context."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File for Context", "", "Text Files (*.txt *.py *.json *.csv *.md *.cpp);;All Files (*)"
        )
        if file_path:
            try:
                content = Path(file_path).read_text(encoding="utf-8")
                self.file_context = f"\n\n[File Contents of {Path(file_path).name}]:\n{content}"
                self.file_label.setText(f"Loaded: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to read file: {e}")

    def save_extracted_file(self):
        """Extracts code blocks from the AI response and saves them to Downloads."""
        if not self.last_ai_response:
            QMessageBox.information(self, "Info", "No recent AI response to save.")
            return

        blocks = extract_code_blocks(self.last_ai_response)
        if not blocks:
            QMessageBox.information(self, "Info", "No code blocks found in the latest AI output.")
            return

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        saved_paths = []
        for filename, content in blocks:
            dest_path = DOWNLOADS_DIR / filename
            dest_path.write_text(content, encoding="utf-8")
            saved_paths.append(str(dest_path))

        QMessageBox.information(self, "Success", f"Saved output file(s) to:\n" + "\n".join(saved_paths))

    def get_context_info(self) -> str:
        """Generates real-time Date, Time, GPS Location, Weather, and File context."""
        now = datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%I:%M %p")

        loc_str = "Unknown location"
        if self.location:
            loc_str = f"Lat: {self.location.get('lat')}, Lon: {self.location.get('lon')}"

        return (
            f"[Current Date]: {date_str}\n"
            f"[Current Time]: {time_str}\n"
            f"[GPS Location]: {loc_str}\n"
            f"[Current Weather]: {self.cached_weather}"
            f"{getattr(self, 'file_context', '')}"
        )

    def fetch_weather(self):
        """Fetches live weather using Open-Meteo API based on current GPS location."""
        if not self.location:
            return
        try:
            lat = self.location.get("lat")
            lon = self.location.get("lon")
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
            res = requests.get(url, timeout=5)
            if res.ok:
                data = res.json().get("current_weather", {})
                temp_c = data.get("temperature")
                temp_f = (temp_c * 9 / 5) + 32 if temp_c is not None else "N/A"
                wind = data.get("windspeed")
                self.cached_weather = f"{temp_f:.1f}°F ({temp_c}°C), Wind Speed: {wind} km/h"
        except Exception as e:
            print(f"[Weather Error] {e}")

    def generate_wake_greeting(self) -> str:
        """Instructs the LLM to dynamically generate a concise wake-up greeting."""
        greeting_prompt = (
            "[System Event]: The user just spoke your wake word to get your attention. "
            "Acknowledge them with a short, natural, single-sentence response (e.g., 'Yes?', 'How can I help you?')."
        )
        return self.ask_assistant(greeting_prompt)

    def ask_assistant(self, user_text: str) -> str:
        messages = [{"role": "system", "content": system_prompt()}]
        messages += [
            {"role": x.get("role", "assistant"), "content": x.get("content", "")}
            for x in load_memory()[-16:]
            if x.get("content")
        ]

        # Inject real-time context (Date, Time, GPS, Weather, File, Camera)
        environment_context = self.get_context_info()
        full_context = f"\n\n[Environment Context]:\n{environment_context}"
        if self.vision_context:
            full_context += f"\n[Camera Vision]: {self.vision_context}"

        messages.append({"role": "user", "content": user_text + full_context})

        url = endpoint()
        if not url:
            return "I cannot reach the local language model."

        try:
            response = requests.post(
                url,
                json={"model": MODEL, "messages": messages, "temperature": 0.6},
                timeout=500,
            )
            response.raise_for_status()
            data = response.json()

            if "choices" in data:
                text = data["choices"][0]["message"]["content"].strip()
            elif "message" in data and "content" in data["message"]:
                text = data["message"]["content"].strip()
            elif "response" in data:
                text = data["response"].strip()
            else:
                text = "I received an unexpected response format."
        except Exception:
            text = "The language model returned an error."

        self.last_ai_response = text
        save_turn(user_text, text)
        return text

    def play_media(self, query: str) -> str:
        """Searches YouTube using yt-dlp and autoplays the top organic result."""
        if not query:
            return "Please specify what song, video, or topic you want to play."

        if "drop my needle" in query.lower() or "drop the needle" in query.lower():
            current_month = datetime.now().month
            if current_month == 12:
                query = "Jingle Bells Bombay Dub Orchestra Remix"
            else:
                query = "T.N.T. AC/DC"

        try:
            import yt_dlp

            ydl_opts = {
                "extract_flat": True,
                "skip_download": True,
                "quiet": True,
                "no_warnings": True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch5:{query}", download=False)

                if "entries" in info and info["entries"]:
                    for entry in info["entries"]:
                        video_id = entry.get("id")
                        title = entry.get("title", query)

                        if video_id:
                            watch_url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
                            webbrowser.open(watch_url)
                            return f"Playing {title}."

        except Exception as e:
            print(f"[Media Search Error] Fallback triggered: {e}")

        encoded_query = urllib.parse.quote(query)
        fallback_url = f"https://www.youtube.com/results?search_query={encoded_query}"
        webbrowser.open(fallback_url)
        return f"Searching for {query}."

    def _start_gps_updates(self):
        def updater():
            while True:
                try:
                    g = geocoder.ip("me")
                    if g.ok and g.latlng:
                        self.location = {"lat": g.latlng[0], "lon": g.latlng[1]}
                        self.fetch_weather()
                except Exception as exc:
                    print(f"[GPS Error] {exc}")
                time.sleep(300)

        threading.Thread(target=updater, daemon=True).start()

    def _start_upload_server(self):
        self.upload_app = Flask(__name__)

        @self.upload_app.route("/upload", methods=["POST"])
        def upload_file():
            if "file" not in request.files:
                return jsonify({"error": "no file"}), 400
            f = request.files["file"]
            path = os.path.join("uploads", f.filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
            
            # Read file content into LLM context automatically
            try:
                with open(path, "r", encoding="utf-8") as file_data:
                    content = file_data.read()
                    self.file_context = f"\n\n[Uploaded File Content ({f.filename})]:\n{content}"
            except Exception as e:
                print(f"[Upload Error] Could not read text content: {e}")

            return jsonify({"path": path})

    def connect_arms(self):
        try:
            self.robot.connect(self.leader_port.text(), self.follower_port.text())
        except Exception as e:
            print(f"[Hardware Error] {e}")

    def home_arms(self):
        try:
            self.robot.home()
        except Exception as e:
            print(f"[Hardware Error] {e}")

    def set_torque(self, enabled: bool):
        try:
            self.robot.set_torque(enabled)
        except Exception as e:
            print(f"[Hardware Error] {e}")

    def refresh_status(self):
        snapshot = self.robot.snapshot()
        lines = [
            f"{name.title()}: {'ONLINE' if item['connected'] else 'offline'}"
            for name, item in snapshot.items()
        ]
        self.robot_status.setText("\n".join(lines))

    def start_camera(self):
        try:
            if hasattr(self, "cap") and self.cap.isOpened():
                return
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                raise RuntimeError("Failed to open camera device")

            self.cam_timer = QTimer(self)
            self.cam_timer.timeout.connect(self.update_camera_frame)
            self.cam_timer.start(33)
            self.vision_status.setText("Camera live")
        except Exception as e:
            self.vision_status.setText(f"Camera failed ({e})")

    def stop_camera(self):
        try:
            if hasattr(self, "cam_timer") and self.cam_timer.isActive():
                self.cam_timer.stop()
            if hasattr(self, "cap") and self.cap.isOpened():
                self.cap.release()
            self.vision_status.setText("Camera off")
        except Exception as e:
            self.vision_status.setText(f"Camera failed ({e})")

    def update_camera_frame(self):
        if not hasattr(self, "cap") or not self.cap.isOpened():
            return
        ret, frame = self.cap.read()
        if not ret:
            return

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image).scaled(
            self.camera_view.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        self.camera_view.setPixmap(pixmap)

    def closeEvent(self, event):
        self.stop_camera()
        self.robot.disconnect()
        event.accept()


# ------------------------------------------------------------------
# Entry Point Execution & Voice Loop
# ------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    window = JarvisWindow()
    window.show()

    stt_queue = queue.Queue()
    stt_thread = STTThread(stt_queue)
    stt_thread.start()

    def voice_loop():
        active_session = False
        session_timeout = 0.0

        while True:
            try:
                spoken_text = stt_queue.get(timeout=0.5)
                if not spoken_text:
                    continue

                print(f"[HEARD] {spoken_text}")
                command = extract_wake_word_command(spoken_text)

                if command is not None or (active_session and time.time() < session_timeout):

                    # Spoke ONLY the wake word
                    if command == "" and not active_session:
                        greeting = window.generate_wake_greeting()
                        print(f"[DANOVA] {greeting}")

                        with stt_queue.mutex:
                            stt_queue.queue.clear()

                        window.speaker.speak(greeting)

                        active_session = True
                        session_timeout = time.time() + 10.0
                        continue

                    # Follow-up command spoken or full phrase spoken
                    actual_prompt = command if (command is not None and command != "") else spoken_text
                    active_session = False

                    prompt_lower = actual_prompt.lower()

                    # Handle app launching commands
                    if prompt_lower.startswith("open ") or prompt_lower.startswith("launch "):
                        target_app = (
                            prompt_lower.replace("open", "")
                            .replace("launch", "")
                            .strip()
                        )
                        response_text = open_app(target_app)

                    # Trigger media handler or preprogrammed needle drop
                    elif (
                        prompt_lower.startswith("play ") 
                        or " play " in prompt_lower 
                        or "drop my needle" in prompt_lower
                        or "drop the needle" in prompt_lower
                    ):
                        if "drop my needle" in prompt_lower or "drop the needle" in prompt_lower:
                            media_query = "drop my needle"
                        else:
                            media_query = (
                                prompt_lower.replace("play", "")
                                .replace("on spotify", "")
                                .replace("on youtube", "")
                                .replace("video", "")
                                .replace("song", "")
                                .strip()
                            )
                        response_text = window.play_media(media_query)
                    else:
                        response_text = window.ask_assistant(actual_prompt)

                    print(f"[DANOVA] {response_text}")

                    with stt_queue.mutex:
                        stt_queue.queue.clear()

                    window.speaker.speak(response_text)

            except queue.Empty:
                if active_session and time.time() > session_timeout:
                    active_session = False
                continue
            except KeyboardInterrupt:
                stt_thread.stop()
                break

    threading.Thread(target=voice_loop, daemon=True).start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()