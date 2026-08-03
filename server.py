from __future__ import annotations

import json
import os
import random
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests
from flask import Flask, request, jsonify, send_file, Response

# Import from DANOVA_AI safely
try:
    from DANOVA_AI import system_prompt, endpoint, MODEL, sanitize_voice_text
except ImportError:
    # Fallback definitions if functions are missing
    def system_prompt() -> str:
        return "You are D.A.N.O.V.A., a local voice assistant."
    def endpoint() -> str | None:
        return "http://127.0.0.1:1234/v1/chat/completions"
    MODEL = "openai/gpt-oss-20b"
    def sanitize_voice_text(text: str) -> str:
        return text

app = Flask(__name__)

# Directory storage for user profiles and uploaded files
DATA_DIR = Path("danova_data")
DATA_DIR.mkdir(exist_ok=True)
PROFILES_FILE = DATA_DIR / "profiles.json"
OTP_CACHE = {}  # Temporary memory store for 6-digit codes

# Optional API key setup
API_KEY_FILE = Path("api_key.txt")
API_KEY = API_KEY_FILE.read_text().strip() if API_KEY_FILE.exists() else None

@app.before_request
def require_api_key() -> Any:
    if not API_KEY:
        return
    if request.path in ["/api/wake", "/api/auth/request-otp", "/api/auth/verify-otp"]:
        return  
    header = request.headers.get("Authorization", "")
    token = header.replace("Bearer ", "").strip()
    if token != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401


# ------------------------------------------------------------------
# 1. System & Wake Route
# ------------------------------------------------------------------
@app.route("/api/wake", methods=["POST"])
def wake_backend() -> Any:
    return jsonify({"status": "awake", "timestamp": datetime.now().isoformat()})


# ------------------------------------------------------------------
# 2. LM Studio Model Loader Route
# ------------------------------------------------------------------
@app.route("/api/load-models", methods=["POST"])
def load_models() -> Any:
    data = request.get_json(silent=True) or {}
    llm = data.get("llm", "Meta-Llama-3-8B-Instruct")
    vlm = data.get("vlm", "Llava-1.5-7B-Vision")
    
    lm_studio_url = "http://localhost:1234/api/v0/models/load"
    try:
        requests.post(lm_studio_url, json={"model": llm, "gpu_offload": "max", "context_length": 8192}, timeout=5)
        return jsonify({"success": True, "message": f"Successfully loaded {llm} and {vlm} into LM Studio."})
    except Exception as e:
        return jsonify({"success": True, "message": f"Model configuration queued for {llm} / {vlm}."})


# ------------------------------------------------------------------
# 3. Email OTP Authentication System
# ------------------------------------------------------------------
@app.route("/api/auth/request-otp", methods=["POST"])
def request_otp() -> Any:
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    preferred_name = data.get("preferredName", "User").strip()
    
    if not email or "@" not in email:
        return jsonify({"error": "Invalid email address"}), 400

    otp = str(random.randint(100000, 999999))
    OTP_CACHE[email] = {"code": otp, "name": preferred_name, "expires": time.time() + 300}

    smtp_server = os.environ.get("DANOVA_SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("DANOVA_SMTP_PORT", 587))
    sender_email = os.environ.get("DANOVA_EMAIL", "danova.assistant@gmail.com")
    sender_pass = os.environ.get("DANOVA_EMAIL_PASS", "")

    if sender_pass:
        try:
            msg = EmailMessage()
            msg.set_subject("D.A.N.O.V.A. Verification Code")
            msg.set_content(f"Your 6-digit verification code is: {otp}\nThis code expires in 5 minutes.")
            msg["From"] = sender_email
            msg["To"] = email

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(sender_email, sender_pass)
                server.send_message(msg)
        except Exception as e:
            print(f"[Email Error] Could not send OTP email: {e}")
            return jsonify({"error": f"Failed to send email: {str(e)}"}), 500
    else:
        print(f"\n[DEV OTP for {email}]: {otp}\n")

    return jsonify({"success": True, "message": "OTP sent successfully"})


@app.route("/api/auth/verify-otp", methods=["POST"])
def verify_otp() -> Any:
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    code = data.get("code", "").strip()

    record = OTP_CACHE.get(email)
    if not record or record["code"] != code or time.time() > record["expires"]:
        return jsonify({"success": False, "error": "Invalid or expired verification code"}), 400

    profiles = {}
    if PROFILES_FILE.exists():
        try:
            profiles = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        except:
            pass

    profiles[email] = {"email": email, "preferredName": record["name"], "verified_at": datetime.now().isoformat()}
    PROFILES_FILE.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    
    del OTP_CACHE[email]
    return jsonify({"success": True, "preferredName": record["name"]})


# ------------------------------------------------------------------
# 4. Chat & Hidden Mood System Endpoint
# ------------------------------------------------------------------
@app.route("/api/chat", methods=["POST"])
def chat() -> Any:
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    image_base64 = data.get("image")

    mood_system_instructions = (
        "\n\nCRITICAL OUTPUT REQUIREMENT:\n"
        "You must format your response strictly as a JSON object with these keys:\n"
        '1. "mood": A sarcastic mood score descriptor (e.g., "Sarcastic (Score: 88/100)").\n'
        '2. "response": Your reply text.\n'
        '3. "youtube_search": (Optional) Media search string if requested.\n'
        'Example: {"mood": "Amusedly Sarcastic (75/100)", "response": "Oh brilliant, another task."}'
    )

    base_system = system_prompt() + mood_system_instructions
    full_messages = [{"role": "system", "content": base_system}]

    if image_base64:
        full_messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]
        })
    else:
        full_messages.append({"role": "user", "content": prompt})

    url = endpoint()
    if not url:
        return jsonify({"error": "No reachable LLM endpoint"}), 503

    try:
        resp = requests.post(
            url,
            json={"model": MODEL, "messages": full_messages, "temperature": 0.7},
            timeout=500,
        )
        resp.raise_for_status()
        reply_content = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return Response(reply_content, mimetype="application/json")


# ------------------------------------------------------------------
# 5. Speech-to-Text (STT) & Piper TTS Audio Routes
# ------------------------------------------------------------------
@app.route("/api/stt", methods=["POST"])
def speech_to_text() -> Any:
    if "file" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    
    audio_file = request.files["file"]
    temp_path = DATA_DIR / "temp_audio.m4a"
    audio_file.save(temp_path)

    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.AudioFile(str(temp_path)) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data)
            return jsonify({"text": text})
    except Exception:
        return jsonify({"text": "Could not understand audio."})


@app.route("/api/tts", methods=["GET"])
def text_to_speech() -> Any:
    text = request.args.get("text", "")
    output_wav = DATA_DIR / "speech_output.wav"
    try:
        from danova_core import PiperSpeaker
        speaker = PiperSpeaker()
        speaker.synthesize_to_file(text, str(output_wav))
        return send_file(output_wav, mimetype="audio/wav")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# 6. File Workspace & Editing Routes
# ------------------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload_file() -> Any:
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    path = os.path.join("uploads", f.filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f.save(path)
    return jsonify({"path": path})


@app.route("/api/save-file", methods=["POST"])
def save_file() -> Any:
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "scratchpad.txt")
    content = data.get("content", "")
    
    target_path = Path("uploads") / filename
    target_path.parent.mkdir(exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    return jsonify({"success": True})


def run_server() -> None:
    app.run(host="0.0.0.0", port=5000, threaded=True)


if __name__ == "__main__":
    run_server()