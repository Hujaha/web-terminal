"""
Web Terminal — server.

Flask + Socket.IO web terminal styled like Claude.ai.
Designed to be deployed on Railway via the included Dockerfile.

Auth: random username/password generated on first start (or read from env vars
WEB_TERMINAL_USERNAME / WEB_TERMINAL_PASSWORD). Credentials are printed to stdout
so they appear in the Railway log stream.

Terminal: real PTY on Linux (Railway / Docker), subprocess fallback on Windows for
local dev.

Metrics: CPU / RAM via psutil, GPU via GPUtil (if NVIDIA + nvidia-smi present).
"""

from __future__ import annotations

import os
import sys
import platform
import secrets
import string
import struct
import threading
import time
from functools import wraps

import eventlet
eventlet.monkey_patch()

import psutil
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_socketio import SocketIO, disconnect, emit

try:
    import GPUtil  # type: ignore
    _GPU_LIB = True
except Exception:  # pragma: no cover - optional dep
    _GPU_LIB = False

IS_WINDOWS = platform.system() == "Windows"

if not IS_WINDOWS:
    import pty
    import fcntl
    import termios
    import select
    import signal


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _gen_username() -> str:
    return "user_" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def _gen_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20))


USERNAME = os.environ.get("WEB_TERMINAL_USERNAME") or _gen_username()
PASSWORD = os.environ.get("WEB_TERMINAL_PASSWORD") or _gen_password()
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48)
SHELL = os.environ.get("SHELL") or ("cmd.exe" if IS_WINDOWS else "/bin/bash")
PORT = int(os.environ.get("PORT", "8080"))


def _print_credentials() -> None:
    banner = "=" * 60
    print(banner, flush=True)
    print(" Web Terminal — login credentials", flush=True)
    print(banner, flush=True)
    print(f"  username: {USERNAME}", flush=True)
    print(f"  password: {PASSWORD}", flush=True)
    print(banner, flush=True)
    print(" Set WEB_TERMINAL_USERNAME / WEB_TERMINAL_PASSWORD env vars", flush=True)
    print(" to use fixed credentials instead of random ones.", flush=True)
    print(banner, flush=True)


# ---------------------------------------------------------------------------
# Flask + Socket.IO
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins="*",
    ping_timeout=30,
    ping_interval=15,
)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if session.get("authed"):
        return redirect(url_for("terminal"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        if secrets.compare_digest(u, USERNAME) and secrets.compare_digest(p, PASSWORD):
            session.clear()
            session["authed"] = True
            session["user"] = u
            nxt = request.args.get("next") or url_for("terminal")
            return redirect(nxt)
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/terminal")
@login_required
def terminal():
    return render_template(
        "terminal.html",
        user=session.get("user", USERNAME),
        host=platform.node() or "railway",
    )


@app.route("/api/stats")
@login_required
def api_stats():
    return jsonify(_collect_stats())


# ---------------------------------------------------------------------------
# System metrics
# ---------------------------------------------------------------------------

def _collect_stats() -> dict:
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True) or 1
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    gpus: list[dict] = []
    if _GPU_LIB:
        try:
            for g in GPUtil.getGPUs():
                gpus.append({
                    "name": g.name,
                    "load": round(g.load * 100, 1),
                    "memory_used": int(g.memoryUsed),
                    "memory_total": int(g.memoryTotal),
                    "memory_percent": round((g.memoryUsed / g.memoryTotal) * 100, 1) if g.memoryTotal else 0.0,
                    "temperature": g.temperature,
                })
        except Exception:
            gpus = []

    return {
        "cpu": {
            "percent": cpu_percent,
            "count": cpu_count,
            "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
        },
        "ram": {
            "percent": vm.percent,
            "used": vm.used,
            "total": vm.total,
            "available": vm.available,
        },
        "swap": {
            "percent": swap.percent,
            "used": swap.used,
            "total": swap.total,
        },
        "gpu": gpus,
        "host": platform.node() or "railway",
        "system": f"{platform.system()} {platform.release()}",
        "uptime": int(time.time() - psutil.boot_time()),
    }


def _stats_broadcaster():
    """Push system stats to all connected clients every second."""
    while True:
        try:
            socketio.emit("stats", _collect_stats())
        except Exception:
            pass
        eventlet.sleep(1.0)


# ---------------------------------------------------------------------------
# PTY / terminal sessions
# ---------------------------------------------------------------------------

# Map socket-id -> session dict
_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


def _spawn_pty() -> dict:
    """Fork a child running $SHELL connected to a pseudo-terminal."""
    pid, fd = pty.fork()
    if pid == 0:
        # Child: become the shell.
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        try:
            os.execvpe(SHELL, [SHELL], env)
        except Exception as exc:
            sys.stderr.write(f"failed to exec {SHELL}: {exc}\n")
            os._exit(1)
    # Parent
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    return {"pid": pid, "fd": fd}


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass


def _pty_reader(sid: str) -> None:
    """Read from PTY and forward to the websocket client."""
    sess = _sessions.get(sid)
    if not sess:
        return
    fd = sess["fd"]
    while True:
        try:
            socketio.sleep(0.01)
            r, _, _ = select.select([fd], [], [], 0)
            if fd not in r:
                continue
            data = os.read(fd, 65536)
            if not data:
                break
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = data.decode("latin-1", errors="replace")
            socketio.emit("pty-output", {"data": text}, to=sid)
        except (OSError, ValueError):
            break
        except Exception:
            break
    _kill_session(sid)


def _kill_session(sid: str) -> None:
    with _sessions_lock:
        sess = _sessions.pop(sid, None)
    if not sess:
        return
    fd = sess.get("fd")
    pid = sess.get("pid")
    try:
        if fd is not None:
            os.close(fd)
    except Exception:
        pass
    try:
        if pid:
            os.kill(pid, signal.SIGHUP)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Socket.IO events
# ---------------------------------------------------------------------------

def _is_ws_authed() -> bool:
    return bool(session.get("authed"))


@socketio.on("connect")
def on_connect():
    if not _is_ws_authed():
        return False  # reject handshake
    if IS_WINDOWS:
        emit("pty-output", {"data": "\r\n\x1b[33mNote: PTY not available on Windows host. "
                                     "Deploy on Linux/Docker for an interactive shell.\x1b[0m\r\n"})
        return
    sid = request.sid  # type: ignore[attr-defined]
    try:
        sess = _spawn_pty()
    except Exception as exc:
        emit("pty-output", {"data": f"\r\n\x1b[31mfailed to start shell: {exc}\x1b[0m\r\n"})
        return
    with _sessions_lock:
        _sessions[sid] = sess
    socketio.start_background_task(_pty_reader, sid)
    emit("pty-output", {"data": f"\x1b[32m✓ shell ready ({SHELL})\x1b[0m\r\n"})


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid  # type: ignore[attr-defined]
    _kill_session(sid)


@socketio.on("pty-input")
def on_input(message):
    if not _is_ws_authed() or IS_WINDOWS:
        return
    sid = request.sid  # type: ignore[attr-defined]
    sess = _sessions.get(sid)
    if not sess:
        return
    data = message.get("data", "") if isinstance(message, dict) else str(message)
    try:
        os.write(sess["fd"], data.encode("utf-8", errors="replace"))
    except OSError:
        _kill_session(sid)


@socketio.on("pty-resize")
def on_resize(message):
    if not _is_ws_authed() or IS_WINDOWS:
        return
    sid = request.sid  # type: ignore[attr-defined]
    sess = _sessions.get(sid)
    if not sess:
        return
    rows = int(message.get("rows", 24))
    cols = int(message.get("cols", 80))
    _set_winsize(sess["fd"], rows, cols)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    _print_credentials()
    socketio.start_background_task(_stats_broadcaster)
    socketio.run(
        app,
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
        log_output=True,
    )


if __name__ == "__main__":
    main()
