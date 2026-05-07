# Web Terminal

A self-hosted web terminal styled after [claude.ai](https://claude.ai).
Drop-in deployable to [Railway](https://railway.com) via the included Dockerfile.

- Real PTY shell in the browser via [xterm.js](https://xtermjs.org/) + Flask-SocketIO
- Live CPU / RAM / GPU metrics in a sidebar (psutil + GPUtil)
- Random username/password generated on container start, printed to logs
- One `server.py`, one `style.css`, two HTML templates — no build step

## Stack

| Layer    | Tech                                     |
|----------|------------------------------------------|
| Backend  | Python 3.11, Flask, Flask-SocketIO, eventlet |
| Frontend | xterm.js, vanilla JS, CSS                |
| Metrics  | psutil (CPU/RAM), GPUtil (NVIDIA GPU)    |
| Deploy   | Docker, Railway                          |

## Project layout

```
web-terminal/
├── server.py            # Flask app, Socket.IO, PTY, auth, metrics
├── requirements.txt
├── Dockerfile
├── railway.toml
├── .dockerignore
├── .gitignore
├── templates/
│   ├── login.html
│   └── terminal.html
└── static/
    ├── style.css        # Claude.ai-styled UI
    └── app.js           # client logic (xterm + socket.io + stats)
```

## Deploy on Railway

1. Push this repo to GitHub.
2. In Railway: **New Project → Deploy from GitHub repo** and pick the repo.
3. Railway detects the `Dockerfile` and builds the image.
4. Open the **Logs** tab — you'll see the generated credentials:

   ```
   ============================================================
    Web Terminal — login credentials
   ============================================================
     username: user_a1b2c3
     password: kJh7dP3...
   ============================================================
   ```

5. Open the public URL Railway gives you, sign in with those credentials.

### Fixed credentials

If you don't want random credentials regenerated on every redeploy, add the
following Railway variables (Service → Variables):

| Variable                  | Description                                     |
|---------------------------|-------------------------------------------------|
| `WEB_TERMINAL_USERNAME`   | Login username                                  |
| `WEB_TERMINAL_PASSWORD`   | Login password                                  |
| `SECRET_KEY`              | Flask session secret (any long random string)   |
| `SHELL`                   | Override shell (default: `/bin/bash`)           |
| `PORT`                    | Already injected by Railway, do not set manually|

## Run locally with Docker

```bash
docker build -t web-terminal .
docker run --rm -p 8080:8080 web-terminal
```

Then open <http://localhost:8080>. Credentials are in the container output.

## Run locally without Docker (Linux / macOS)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

> Windows note: the interactive PTY shell only works on Linux/macOS (i.e. inside
> the Docker container or on a Unix host). On Windows the page still loads and
> shows live metrics, but you'll see a notice instead of a working shell.

## Security notes

This exposes a real shell to anyone who has the credentials, so:

- Always deploy behind HTTPS (Railway gives you that for free).
- Set a strong `WEB_TERMINAL_PASSWORD` in production.
- Treat the deployed URL like SSH access — don't share it.
- The container runs as root by default (so the shell is useful). Don't deploy
  this on infra you wouldn't grant root on.

## License

MIT — do whatever you want, no warranty.
