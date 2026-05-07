/* Web Terminal — client logic */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ---------- xterm setup ----------
  const term = new Terminal({
    cursorBlink: true,
    cursorStyle: "bar",
    fontFamily:
      "'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, Consolas, monospace",
    fontSize: 13,
    lineHeight: 1.3,
    letterSpacing: 0,
    scrollback: 5000,
    allowProposedApi: true,
    theme: {
      background: "#1f1e1c",
      foreground: "#ebe9e2",
      cursor: "#c96342",
      cursorAccent: "#1f1e1c",
      selectionBackground: "rgba(201, 99, 66, 0.35)",
      black: "#1f1e1c",
      red: "#e06c5b",
      green: "#7cb275",
      yellow: "#d4b454",
      blue: "#6ea3c4",
      magenta: "#b984c4",
      cyan: "#6cbfb5",
      white: "#ebe9e2",
      brightBlack: "#6f6b62",
      brightRed: "#ec8678",
      brightGreen: "#94c98d",
      brightYellow: "#e3c97a",
      brightBlue: "#90b7d1",
      brightMagenta: "#caa1d4",
      brightCyan: "#88cdc4",
      brightWhite: "#faf9f5",
    },
  });

  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open($("terminal"));
  setTimeout(() => fit.fit(), 0);

  // ---------- socket.io ----------
  const socket = io({ transports: ["websocket", "polling"] });

  function setConn(status, text) {
    const dot = $("conn-dot");
    const lab = $("conn-text");
    dot.classList.remove("ok", "warn", "bad");
    dot.classList.add(status);
    lab.textContent = text;
  }

  socket.on("connect", () => {
    setConn("ok", "connected");
    sendResize();
  });

  socket.on("disconnect", () => {
    setConn("bad", "disconnected");
  });

  socket.on("connect_error", () => {
    setConn("warn", "reconnecting…");
  });

  socket.on("pty-output", (msg) => {
    if (msg && typeof msg.data === "string") term.write(msg.data);
  });

  term.onData((data) => socket.emit("pty-input", { data }));

  // ---------- resize ----------
  function sendResize() {
    try {
      fit.fit();
      const { rows, cols } = term;
      socket.emit("pty-resize", { rows, cols });
    } catch (_) {}
  }

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(sendResize, 80);
  });

  // ---------- stats ----------
  const fmtBytes = (b) => {
    if (!b && b !== 0) return "—";
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = b;
    while (v >= 1024 && i < u.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2)} ${u[i]}`;
  };

  const fmtUptime = (s) => {
    if (!s && s !== 0) return "—";
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d) return `${d}d ${h}h`;
    if (h) return `${h}h ${m}m`;
    return `${m}m`;
  };

  const setBar = (id, percent) => {
    const el = $(id);
    if (!el) return;
    const p = Math.max(0, Math.min(100, percent || 0));
    el.style.width = p + "%";
    el.dataset.level = p > 85 ? "high" : p > 60 ? "mid" : "low";
  };

  socket.on("stats", (s) => {
    if (!s) return;

    // CPU
    if (s.cpu) {
      $("cpu-percent").textContent = (s.cpu.percent ?? 0).toFixed(0);
      setBar("cpu-bar", s.cpu.percent);
      $("cpu-count").textContent = `${s.cpu.count} cores`;
      const l = s.cpu.load || [0, 0, 0];
      $("cpu-load").textContent = `load ${l[0].toFixed(2)}`;
    }

    // RAM
    if (s.ram) {
      $("ram-percent").textContent = (s.ram.percent ?? 0).toFixed(0);
      setBar("ram-bar", s.ram.percent);
      $("ram-used").textContent = `${fmtBytes(s.ram.used)} / ${fmtBytes(s.ram.total)}`;
      $("ram-free").textContent = `free ${fmtBytes(s.ram.available)}`;
    }

    // GPU
    const gpuList = $("gpu-list");
    const gpuHead = $("gpu-headline");
    if (s.gpu && s.gpu.length) {
      gpuHead.textContent = s.gpu.length === 1 ? "1 device" : `${s.gpu.length} devices`;
      gpuList.innerHTML = s.gpu
        .map(
          (g, i) => `
          <div class="gpu-card">
            <div class="gpu-name" title="${g.name}">${g.name || "GPU " + i}</div>
            <div class="gpu-row">
              <span class="gpu-label">load</span>
              <div class="bar small"><div class="bar-fill" style="width:${g.load}%"></div></div>
              <span class="gpu-num">${g.load.toFixed(0)}%</span>
            </div>
            <div class="gpu-row">
              <span class="gpu-label">vram</span>
              <div class="bar small"><div class="bar-fill" style="width:${g.memory_percent}%"></div></div>
              <span class="gpu-num">${g.memory_used} / ${g.memory_total} MB</span>
            </div>
            ${
              g.temperature
                ? `<div class="gpu-row gpu-temp"><span class="gpu-label">temp</span><span class="gpu-num">${g.temperature}°C</span></div>`
                : ""
            }
          </div>`
        )
        .join("");
    } else {
      gpuHead.textContent = "none";
      gpuList.innerHTML = `<div class="gpu-empty">No NVIDIA GPU detected</div>`;
    }

    // Host
    if (s.system) $("host-system").textContent = s.system;
    if (s.host) $("host-name").textContent = s.host;
    if (typeof s.uptime === "number") $("host-uptime").textContent = fmtUptime(s.uptime);
  });

  // ---------- toolbar ----------
  $("btn-clear").addEventListener("click", () => {
    term.clear();
    term.focus();
  });

  // focus terminal on click anywhere in the wrap
  document.querySelector(".terminal-wrap").addEventListener("click", () => term.focus());

  setConn("warn", "connecting…");
  term.focus();
})();
