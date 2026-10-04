"""Core services shared by the DANOVA desktop, voice, and automation layers."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import wave
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
AUDIT_LOG = ROOT / "danova_audit.jsonl"
PIPER_MODEL = ROOT / "voices" / "en_GB-alan-medium" / "en_GB-alan-medium.onnx"


class AuditLog:
    _lock = threading.Lock()

    @classmethod
    def write(cls, event: str, **details):
        RUNTIME.mkdir(exist_ok=True)
        record = {"time": datetime.now().isoformat(timespec="seconds"), "event": event, **details}
        with cls._lock, AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class PiperSpeaker:
    """Offline, distinct assistant voice. It never clones or impersonates anyone."""
    def __init__(self, model_path: Path = PIPER_MODEL):
        self.model_path = model_path
        self._voice = None
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def ready(self) -> bool:
        return self.model_path.exists()

    def _load(self):
        if self._voice is None:
            from piper import PiperVoice
            self._voice = PiperVoice.load(self.model_path)
        return self._voice

    def speak(self, text: str):
        if not self.ready:
            raise RuntimeError("Piper voice model is missing")
        clean = re.sub(r"\s+", " ", text).strip()[:1600]
        if not clean:
            return
        with self._lock:
            RUNTIME.mkdir(exist_ok=True)
            self._counter += 1
            output = RUNTIME / f"speech_{self._counter % 3}.wav"
            with wave.open(str(output), "wb") as wav:
                self._load().synthesize_wav(clean, wav)
            if os.name == "nt":
                import winsound
                winsound.PlaySound(str(output), winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                subprocess.Popen(["aplay", str(output)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        AuditLog.write("voice_spoken", characters=len(clean), model=self.model_path.name)


class SafeActionRegistry:
    """Explicit allow-list for future desktop/automation commands."""
    def __init__(self):
        self._actions: dict[str, tuple[Callable, bool]] = {}

    def register(self, name: str, callback: Callable, requires_confirmation: bool = True):
        self._actions[name] = (callback, requires_confirmation)

    def names(self) -> list[str]:
        return sorted(self._actions)

    def invoke(self, name: str, confirmed: bool = False, **kwargs):
        if name not in self._actions:
            raise ValueError("unknown action")
        callback, needs_confirmation = self._actions[name]
        if needs_confirmation and not confirmed:
            return {"ok": False, "needs_confirmation": True, "action": name}
        result = callback(**kwargs)
        AuditLog.write("action", name=name, arguments=kwargs)
        return {"ok": True, "result": result}


def system_health() -> dict:
    """Local-only health snapshot for the future dashboard and alerts."""
    try:
        import psutil
        disk = psutil.disk_usage(str(ROOT))
        return {"cpu_percent": psutil.cpu_percent(), "memory_percent": psutil.virtual_memory().percent,
                "disk_free_gb": round(disk.free / 1024 ** 3, 1), "time": datetime.now().isoformat(timespec="seconds")}
    except Exception as exc:
        return {"error": str(exc)}


def load_plugins(registry: SafeActionRegistry, directory: Path = ROOT / "plugins") -> list[str]:
    """Load only local plugin files that expose register_plugin(registry)."""
    loaded = []
    if not directory.exists():
        return loaded
    for file in directory.glob("*.py"):
        if file.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"danova_plugin_{file.stem}", file)
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register = getattr(module, "register_plugin", None)
        if callable(register):
            register(registry); loaded.append(file.stem)
    return loaded
