"""Bit local agent: opens whitelisted apps and folders on THIS computer when the Bit app asks.
Listens only on 127.0.0.1. Every request needs the shared token. Standard library only (Python 3.9+).

Run:   python bit_local_agent.py
First run creates local_agent_config.json next to this file: edit apps there, copy the token into the Bit app settings."""
import json
import os
import platform
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "local_agent_config.json"
PORT = 8765
SYSTEM = platform.system()  # Windows / Linux / Darwin

DEFAULT_APPS = {
    "Windows": {
        "telegram": {"uri": "tg://"},
        "chrome": {"cmd": ["cmd", "/c", "start", "", "chrome"]},
        "edge": {"cmd": ["cmd", "/c", "start", "", "msedge"]},
        "vscode": {"cmd": ["cmd", "/c", "code"]},
        "notepad": {"cmd": ["notepad.exe"]},
        "calculator": {"cmd": ["calc.exe"]},
        "explorer": {"cmd": ["explorer.exe"]},
        "terminal": {"cmd": ["cmd", "/c", "start", "", "wt"]},
    },
    "Linux": {
        "telegram": {"cmd": ["telegram-desktop"]},
        "chrome": {"cmd": ["google-chrome"]},
        "firefox": {"cmd": ["firefox"]},
        "vscode": {"cmd": ["code"]},
        "terminal": {"cmd": ["x-terminal-emulator"]},
        "files": {"cmd": ["xdg-open", str(Path.home())]},
    },
    "Darwin": {
        "telegram": {"cmd": ["open", "-a", "Telegram"]},
        "chrome": {"cmd": ["open", "-a", "Google Chrome"]},
        "vscode": {"cmd": ["open", "-a", "Visual Studio Code"]},
        "terminal": {"cmd": ["open", "-a", "Terminal"]},
    },
}


def load_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    cfg = {"token": secrets.token_urlsafe(24), "apps": DEFAULT_APPS.get(SYSTEM, {}),
           "allowed_origins": ["*"], "allow_desktop_folders": True}
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


def desktop_dirs() -> list[Path]:
    home = Path.home()
    cands = [home / "Desktop", home / "OneDrive" / "Desktop", home / "Рабочий стол", home / "Ish stoli"]
    return [p for p in cands if p.is_dir()]


def named_folders() -> dict[str, Path]:
    home = Path.home()
    folders = {"home": home, "downloads": home / "Downloads", "documents": home / "Documents",
               "pictures": home / "Pictures", "music": home / "Music", "videos": home / "Videos"}
    d = desktop_dirs()
    if d:
        folders["desktop"] = d[0]
    return {k: v for k, v in folders.items() if v.is_dir()}


def open_path(p: Path):
    if SYSTEM == "Windows":
        os.startfile(str(p))  # noqa: S606 - path is resolved from a whitelist
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def resolve_target(target: str, cfg: dict):
    t = target.strip().lower()
    t = t.removeprefix("desktop/").removeprefix("desktop\\") if t not in ("desktop",) else t
    apps = {k.lower(): v for k, v in cfg.get("apps", {}).items()}
    if t in apps:
        return "app", apps[t]
    folders = named_folders()
    if t in folders:
        return "folder", folders[t]
    if cfg.get("allow_desktop_folders", True):  # a folder sitting on the desktop, matched by name only
        for d in desktop_dirs():
            for child in d.iterdir():
                if child.is_dir() and child.name.lower() == t:
                    return "folder", child
    return None, None


def launch(kind, spec):
    if kind == "folder":
        open_path(spec)
    elif "uri" in spec:
        if SYSTEM == "Windows":
            os.startfile(spec["uri"])  # noqa: S606
        else:
            subprocess.Popen(["open" if SYSTEM == "Darwin" else "xdg-open", spec["uri"]])
    else:
        subprocess.Popen(spec["cmd"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Handler(BaseHTTPRequestHandler):
    cfg: dict = {}

    def _cors(self):
        origin = self.headers.get("Origin", "")
        allowed = self.cfg.get("allowed_origins", ["*"])
        if "*" in allowed or origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin or "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Private-Network", "true")  # Chrome private network access

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "system": SYSTEM})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/open":
            return self._json(404, {"error": "not found"})
        auth = self.headers.get("Authorization", "")
        if not secrets.compare_digest(auth.encode(), f"Bearer {self.cfg['token']}".encode()):
            return self._json(401, {"error": "bad token"})
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 4096)
            target = str(json.loads(self.rfile.read(n) or b"{}").get("target", ""))
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad json"})
        kind, spec = resolve_target(target, self.cfg)
        if not kind:
            names = sorted(list(self.cfg.get("apps", {})) + list(named_folders()))
            return self._json(404, {"error": f"'{target}' is not allowed", "allowed": names})
        try:
            launch(kind, spec)
        except Exception as e:
            return self._json(500, {"error": f"could not open: {e}"})
        print(f"opened {kind}: {target}")
        self._json(200, {"ok": True, "opened": target, "kind": kind})

    def log_message(self, *a):
        pass


def main():
    cfg = load_config()
    Handler.cfg = cfg
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Bit local agent on http://127.0.0.1:{PORT}  ({SYSTEM})")
    print(f"Token (paste into Bit settings): {cfg['token']}")
    print(f"Config: {CONFIG}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
