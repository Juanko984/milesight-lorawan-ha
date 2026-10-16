// Milesight LoRaWAN – commissioning panel (sidebar: "LoRaWAN commissioning", admins only).
// Add a device by scanning its QR code, then walk the site with a live signal test.
// Plain web component, no build step. Talks to the integration over Home Assistant's websocket.

const D = "milesight_lorawan";
const QUALITY = {
  excellent: ["Excellent", "var(--success-color, #43a047)"],
  good: ["Good", "var(--success-color, #43a047)"],
  fair: ["Fair", "var(--warning-color, #ffa000)"],
  poor: ["Poor", "var(--error-color, #db4437)"],
};
const ORDER = ["poor", "fair", "good", "excellent"];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–");
const ago = (ts) => {
  if (!ts) return "never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
};

class MilesightCommissioning extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "add";
    this._parsed = null;
    this._devices = [];
    this._unknown = [];
    this._watch = null;          // deveui being watched
    this._unsub = null;
    this._samples = [];
    this._spot = "";
    this._msg = null;
    this._sound = true;
    this._busy = false;
    this._ticker = null;
    this._rendered = false;
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (first) {
      this._render();
      this._loadDevices();
      this._ticker = setInterval(() => this._updateAgo(), 1000);
    } else {
      const menu = this.shadowRoot.querySelector("ha-menu-button");
      if (menu) menu.hass = h;
    }
  }
  get hass() { return this._hass; }
  set narrow(n) {
    this._narrow = n;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.narrow = n;
  }
  set panel(p) { this._panel = p; }

  disconnectedCallback() {
    clearInterval(this._ticker);
    this._ticker = null;
    this._stopWatch();
    this._stopCamera();
    this._restoreAppHandler();
  }
  connectedCallback() {
    if (this._hass && !this._ticker) this._ticker = setInterval(() => this._updateAgo(), 1000);
    if (this._hass && this._watch && !this._unsub) this._startWatch(this._watch, true);
  }

  _ws(msg) { return this._hass.connection.sendMessagePromise({ ...msg, type: `${D}/commission/${msg.type}` }); }

  async _loadDevices() {
    try {
      const r = await this._ws({ type: "devices" });
      this._devices = r.devices; this._unknown = r.unknown;
    } catch (e) { this._error(e); }
    if (this._tab === "walk") this._render();
  }

  _error(e) { this._msg = { kind: "error", text: e?.message || String(e) }; this._render(); }
  _info(text) { this._msg = { kind: "success", text }; this._render(); }

  // ------------------------------------------------------------------ scanning
  get _ext() { return this._hass?.auth?.external; }
  get _appScanner() { return !!(this._ext && this._ext.config && this._ext.config.hasBarCodeScanner && this._ext.addCommandHandler); }
  get _liveCamera() { return !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia); }

  _scanWithApp() {
    const ext = this._ext;
    // Home Assistant's frontend keeps ONE command handler on the external bus: wrap it for the scan and
    // put it back afterwards, so the app's other commands keep working.
    if (!this._appHandler) {
      const single = "_commandHandler" in ext;
      this._prevHandler = single ? ext._commandHandler : null;
      this._appHandler = (msg) => {
        if (msg.command === "bar_code/scan_result") {
          ext.fireMessage({ type: "bar_code/close" });
          this._restoreAppHandler();
          this._gotText(msg.payload?.rawValue || "");
          return true;
        }
        if (msg.command === "bar_code/aborted") {
          this._restoreAppHandler();
          if (msg.payload?.reason === "alternative_options") this.shadowRoot.getElementById("manual")?.focus();
          return true;
        }
        return this._prevHandler ? this._prevHandler(msg) : false;
      };
      this._appHandlerSingle = single;
      ext.addCommandHandler(this._appHandler);
    }
    ext.fireMessage({ type: "bar_code/scan", payload: {
      title: "Scan the device's QR code", description: "The label on the Milesight device or its box.",
      alternative_option_label: "Type it in" } });
  }

  _restoreAppHandler() {
    if (!this._appHandler) return;
    const ext = this._ext;
    if (ext && this._appHandlerSingle) ext.addCommandHandler(this._prevHandler);   // single handler: put it back
    else if (ext && ext.removeCommandHandler) ext.removeCommandHandler(this._appHandler);
    else if (!this._appHandlerSingle) return;                                     // list without remove: keep ours
    this._appHandler = null; this._prevHandler = null;
  }

  async _decoder() {
    if ("BarcodeDetector" in window) {
      try {
        const formats = await window.BarcodeDetector.getSupportedFormats();
        if (formats.includes("qr_code")) {
          const bd = new window.BarcodeDetector({ formats: ["qr_code", "data_matrix"] });
          return async (src) => (await bd.detect(src))[0]?.rawValue || null;
        }
      } catch (e) { /* fall through */ }
    }
    if (!window.jsQR) {   // needs internet on the phone; the app scanner and typing work offline
      for (const url of ["https://cdnjs.cloudflare.com/ajax/libs/jsQR/1.4.0/jsQR.min.js",
                         "https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js"]) {
        try {
          await new Promise((ok, fail) => { const s = document.createElement("script"); s.src = url; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
          if (window.jsQR) break;
        } catch (e) { /* next */ }
      }
    }
    if (!window.jsQR) return null;
    const canvas = document.createElement("canvas");
    return async (src) => {
      const w = src.videoWidth || src.naturalWidth || src.width, h = src.videoHeight || src.naturalHeight || src.height;
      if (!w || !h) return null;
      const scale = Math.min(1, 1024 / Math.max(w, h));
      canvas.width = Math.round(w * scale); canvas.height = Math.round(h * scale);
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      return window.jsQR(img.data, img.width, img.height)?.data || null;
    };
  }

  async _startCamera() {
    const decode = await this._decoder();
    if (!decode) { this._error("No QR reader available in this browser – use 'Scan with the app' or type the DevEUI."); return; }
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    } catch (e) { this._error("The camera could not be opened: " + (e.message || e)); return; }
    this._camera = true; this._render();
    const video = this.shadowRoot.getElementById("video");
    video.srcObject = this._stream; await video.play();
    const loop = async () => {
      if (!this._camera) return;
      try {
        const text = await decode(video);
        if (text) { this._stopCamera(); this._gotText(text); return; }
      } catch (e) { /* keep trying */ }
      setTimeout(loop, 250);
    };
    loop();
  }

  _stopCamera() {
    this._camera = false;
    this._stream?.getTracks().forEach((t) => t.stop());
    this._stream = null;
  }

  async _photo(file) {
    if (!file) return;
    const decode = await this._decoder();
    if (!decode) { this._error("No QR reader available in this browser – type the DevEUI instead."); return; }
    const img = new Image();
    img.src = URL.createObjectURL(file);
    await img.decode().catch(() => {});
    const text = await decode(img).catch(() => null);
    URL.revokeObjectURL(img.src);
    if (text) this._gotText(text); else this._error("No QR code found in the photo – try again closer and in focus.");
    for (const id of ["file", "file2"]) { const el = this.shadowRoot.getElementById(id); if (el) el.value = ""; }
  }

  async _gotText(text) {
    try {
      this._msg = null;
      const r = await this._ws({ type: "parse", text });
      if (!r.deveui) { this._error(`The code was read ("${text.slice(0, 60)}") but holds no DevEUI. Type it in below.`); return; }
      this._parsed = r; this._form = {}; this._manual = "";
      this._render();
    } catch (e) { this._error(e); }
  }

  async _add() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    const data = { type: "add", deveui: $("f-deveui").value, model: $("f-model").value, name: $("f-name").value,
                   area: $("f-area").value, register: !!$("f-register")?.checked };
    if ($("f-key").value.trim()) data.app_key = $("f-key").value.trim();
    if (!data.model) { this._error("Pick the model."); return; }
    this._busy = true; this._render();
    try {
      const r = await this._ws(data);
      this._busy = false;
      this._lastAdded = r;
      this._parsed = null;
      this._info(`${r.name} added${r.gateway === "added" ? " and registered on the gateway" : r.gateway === "exists" ? " (already on the gateway)" : ""}. Switch it on – then start the walk test.`);
      await this._loadDevices();
    } catch (e) { this._busy = false; this._error(e); }
  }

  // ------------------------------------------------------------------ walk test
  async _startWatch(deveui, keep = false) {
    this._stopWatch();
    const tok = (this._watchSeq = (this._watchSeq || 0) + 1);
    this._watch = deveui;
    if (!keep) this._samples = [];
    this._tab = "walk"; this._render();
    try {
      const unsub = await this._hass.connection.subscribeMessage((s) => { if (tok === this._watchSeq) this._onSample(s); },
        { type: `${D}/commission/watch`, deveui });
      if (tok !== this._watchSeq) { unsub(); return; }       // another device was picked meanwhile
      this._unsub = unsub;
    } catch (e) { this._error(e); }
  }
  _stopWatch() { if (this._unsub) { this._unsub(); this._unsub = null; } }

  _onSample(s) {
    s.spot = s.previous ? "(before the test)" : this._spot;
    this._samples.unshift(s);
    this._samples = this._samples.slice(0, 200);
    if (!s.previous) {
      try { navigator.vibrate?.(s.quality === "poor" ? [80, 60, 80] : 60); } catch (e) { /* ignore */ }
      if (this._sound) this._beep(s.quality);
    }
    if (this._tab === "walk") this._render();
  }

  _beep(q) {
    try {
      this._audio = this._audio || new (window.AudioContext || window.webkitAudioContext)();
      const o = this._audio.createOscillator(), g = this._audio.createGain();
      o.frequency.value = { excellent: 1320, good: 1100, fair: 760, poor: 440 }[q] || 880;
      g.gain.value = 0.08; o.connect(g); g.connect(this._audio.destination);
      o.start(); o.stop(this._audio.currentTime + 0.15);
    } catch (e) { /* no audio */ }
  }

  async _fast(on) {
    try {
      if (on) {
        const r = await this._ws({ type: "fast", deveui: this._watch, minutes: 30 });
        this._info(`Fast reporting asked for (every ${r.fast} ${r.unit === "min" ? "min" : "s"}) until ${fmtTime(r.until)}. The device takes it at its next report – press its button to make it report now. The old interval (${r.restore} ${r.unit}) comes back by itself.`);
      } else {
        const r = await this._ws({ type: "end_fast", deveui: this._watch });
        this._info(r.restored ? `Reporting interval set back to ${r.restored}.` : "Fast reporting was not on.");
      }
      await this._loadDevices();
    } catch (e) { this._error(e); }
  }

  async _save() {
    const live = this._samples.filter((s) => !s.previous && !s.duplicate);
    if (!live.length) { this._error("No uplinks received during this test yet."); return; }
    try {
      const r = await this._ws({ type: "save", deveui: this._watch, samples: live, spot: this._spot,
                                 note: this.shadowRoot.getElementById("w-note")?.value || "" });
      const v = r.result.verdict ? QUALITY[r.result.verdict][0] : "–";
      this._info(`Saved: ${r.result.count} uplinks, worst ${v}. ${r.result.advice || ""}`);
    } catch (e) { this._error(e); }
  }

  _summary() {
    const live = this._samples.filter((s) => !s.previous && !s.duplicate && s.quality);
    if (!live.length) return null;
    const worst = live.reduce((w, s) => (ORDER.indexOf(s.quality) < ORDER.indexOf(w) ? s.quality : w), "excellent");
    const rs = live.map((s) => s.rssi).filter((x) => x != null);
    return { n: live.length, worst, best: rs.length ? Math.max(...rs) : "–", low: rs.length ? Math.min(...rs) : "–" };
  }

  _updateAgo() {
    const el = this.shadowRoot?.getElementById("ago");
    if (el && this._samples[0]) el.textContent = ago(this._samples[0].ts);
  }

  // ------------------------------------------------------------------ render
  _render() {
    const h = this._hass;
    if (!h) return;
    const act = this.shadowRoot.activeElement;      // keep typing focus when a new uplink re-draws the page
    const focus = act && act.id ? { id: act.id, start: act.selectionStart, end: act.selectionEnd } : null;
    const tab = this._tab;
    const msg = this._msg ? `<div class="msg ${this._msg.kind}">${esc(this._msg.text)}</div>` : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; background: var(--primary-background-color); color: var(--primary-text-color); min-height:100vh;
                font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        header { display:flex; align-items:center; gap:12px; padding: 12px 16px; background: var(--app-header-background-color, var(--primary-color));
                 color: var(--app-header-text-color, #fff); font-size: 20px; }
        header ha-menu-button { --mdc-icon-button-size: 40px; }
        .tabs { display:flex; gap:8px; padding: 12px 16px 0; }
        .tabs button { flex:1; }
        main { max-width: 760px; margin: 0 auto; padding: 16px; display:flex; flex-direction:column; gap:16px; }
        .card { background: var(--card-background-color); border-radius: 12px; padding: 16px; box-shadow: var(--ha-card-box-shadow, none);
                border: 1px solid var(--divider-color); display:flex; flex-direction:column; gap:12px; }
        h2 { margin:0; font-size: 18px; font-weight: 500; }
        p.hint { margin:0; color: var(--secondary-text-color); font-size: 14px; line-height: 1.4; }
        button { font: inherit; font-size: 15px; min-height: 44px; padding: 0 16px; border-radius: 22px; border: 1px solid var(--divider-color);
                 background: var(--card-background-color); color: var(--primary-text-color); cursor: pointer; }
        button.primary { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); border-color: transparent; }
        button.on { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
        button:disabled { opacity: .5; }
        .row { display:flex; flex-wrap: wrap; gap: 8px; }
        .row > * { flex: 1 1 160px; }
        label { display:flex; flex-direction:column; gap:4px; font-size: 13px; color: var(--secondary-text-color); }
        input, select, textarea { font: inherit; font-size: 16px; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--divider-color);
                 background: var(--secondary-background-color, var(--card-background-color)); color: var(--primary-text-color); }
        textarea { min-height: 60px; }
        .msg { padding: 12px 14px; border-radius: 10px; font-size: 14px; line-height: 1.4; }
        .msg.error { background: rgba(219,68,55,.15); border: 1px solid var(--error-color, #db4437); }
        .msg.success { background: rgba(67,160,71,.15); border: 1px solid var(--success-color, #43a047); }
        video { width: 100%; border-radius: 12px; background: #000; max-height: 50vh; object-fit: cover; }
        .big { display:grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
        .tile { border-radius: 10px; padding: 10px 12px; background: var(--secondary-background-color, rgba(127,127,127,.08)); }
        .tile .k { font-size: 12px; color: var(--secondary-text-color); }
        .tile .v { font-size: 24px; font-weight: 600; }
        .pill { display:inline-block; padding: 6px 14px; border-radius: 16px; color: #fff; font-weight: 600; font-size: 18px; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--divider-color); }
        th { color: var(--secondary-text-color); font-weight: 500; }
        .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align: middle; }
        .muted { color: var(--secondary-text-color); }
        .scroll { overflow-x: auto; }
      </style>
      <header><ha-menu-button></ha-menu-button><span>LoRaWAN commissioning</span></header>
      <div class="tabs">
        <button id="t-add" class="${tab === "add" ? "on" : ""}">1 · Add a device</button>
        <button id="t-walk" class="${tab === "walk" ? "on" : ""}">2 · Walk test</button>
      </div>
      <main>${msg}${tab === "add" ? this._renderAdd() : this._renderWalk()}</main>`;
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) { menu.hass = h; menu.narrow = this._narrow; }
    this._bind();
    if (focus) {
      const el = this.shadowRoot.getElementById(focus.id);
      if (el) { el.focus(); try { el.setSelectionRange(focus.start, focus.end); } catch (e) { /* not a text field */ } }
    }
  }

  _renderAdd() {
    const p = this._parsed;
    const scanners = `
      <div class="card">
        <h2>Scan the QR code</h2>
        <p class="hint">On the device label or its box. Works in the Home Assistant app (offline too), with the phone's camera, or from a photo.</p>
        <div class="row">
          ${this._appScanner ? `<button class="primary" id="b-app">Scan with the app</button>` : ""}
          ${this._liveCamera ? `<button ${this._appScanner ? "" : 'class="primary"'} id="b-cam">${this._camera ? "Stop camera" : "Use the camera"}</button>` : ""}
          <button id="b-photo">Take a photo</button>
          <button id="b-pick">Pick a photo</button>
        </div>
        <input type="file" accept="image/*" capture="environment" id="file" hidden>
        <input type="file" accept="image/*" id="file2" hidden>
        ${this._camera ? `<video id="video" playsinline muted></video>` : ""}
        <label>Or type / paste the DevEUI (or the code's text)
          <textarea id="manual" placeholder="24E124136D058239">${esc(this._manual || "")}</textarea></label>
        <div class="row"><button id="b-read">Use this</button></div>
      </div>`;
    if (!p) return scanners + this._renderRecent();
    const f = this._form || {};
    const chosen = f.model ?? p.model;
    const models = p.models.map((m) => `<option value="${m.value}" ${m.value === chosen ? "selected" : ""}>${esc(m.label)}</option>`).join("");
    return `
      <div class="card">
        <h2>${p.exists ? "Already set up" : "New device"}</h2>
        ${p.exists ? `<p class="hint">This DevEUI is already in Home Assistant as <b>${esc(p.existing_name)}</b>.</p>
          <div class="row"><button class="primary" id="b-walk-existing">Walk test this device</button><button id="b-again">Scan another</button></div>` : `
        <p class="hint">Read from the code${p.format ? ` (${esc(p.format)})` : ""}${p.heard ? " · the gateway already hears this device" : ""}${p.model ? "" : " · pick the model"}.</p>
        <label>DevEUI<input id="f-deveui" value="${esc(f.deveui ?? (p.deveui || "").toUpperCase())}"></label>
        <label>Model<select id="f-model"><option value="">– pick –</option>${models}</select></label>
        <div class="row">
          <label>Name<input id="f-name" value="${esc(f.name || "")}" placeholder="${esc((p.model || "Device") + " " + (p.deveui || "").slice(-4).toUpperCase())}"></label>
          <label>Area<input id="f-area" value="${esc(f.area || "")}" placeholder="e.g. Cold room"></label>
        </div>
        <label>AppKey ${p.has_app_key ? "(from the code)" : "(empty = the gateway's default key)"}
          <input id="f-key" type="password" value="${esc(f.key ?? (p.app_key || ""))}" autocomplete="off"></label>
        ${p.can_register ? `<label style="flex-direction:row;align-items:center;gap:10px;font-size:15px;color:var(--primary-text-color)">
          <input type="checkbox" id="f-register" ${f.register === false ? "" : "checked"} style="width:20px;height:20px"> Also register it on the gateway</label>`
          : `<p class="hint">Gateway registration is not set up (gateway → Configure → Add devices to the gateway) – add the device on the gateway yourself.</p>`}
        <div class="row"><button class="primary" id="b-add" ${this._busy ? "disabled" : ""}>${this._busy ? "Adding…" : "Add device"}</button><button id="b-again">Cancel</button></div>`}
      </div>`;
  }

  _renderRecent() {
    const a = this._lastAdded;
    if (!a) return "";
    return `<div class="card"><h2>Just added</h2><p class="hint">${esc(a.name)} · ${esc(a.deveui.toUpperCase())}</p>
      <div class="row"><button class="primary" id="b-walk-added">Start the walk test</button></div></div>`;
  }

  _renderWalk() {
    const opts = this._devices.map((d) => `<option value="${d.deveui}" ${d.deveui === this._watch ? "selected" : ""}>${esc(d.name)} · ${esc(d.model)}${d.area ? " · " + esc(d.area) : ""}</option>`).join("");
    const unk = this._unknown.map((d) => `<option value="${d.deveui}" ${d.deveui === this._watch ? "selected" : ""}>${esc(d.name)} (not set up)</option>`).join("");
    const dev = this._devices.find((d) => d.deveui === this._watch);
    const last = this._samples[0];
    const q = last?.quality ? QUALITY[last.quality] : null;
    const sum = this._summary();
    const rows = this._samples.map((s) => `<tr>
        <td>${fmtTime(s.ts)}</td><td>${esc(s.spot || "")}</td>
        <td>${s.rssi ?? "–"}</td><td>${s.snr ?? "–"}</td><td>${s.sf ? "SF" + s.sf : "–"}</td>
        <td>${s.quality ? `<span class="dot" style="background:${QUALITY[s.quality][1]}"></span>${QUALITY[s.quality][0]}` : "–"}${s.duplicate ? " <span class='muted'>(repeat)</span>" : ""}</td>
        <td class="muted">${esc((s.gateways || []).map((g) => g.name).join(", "))}</td></tr>`).join("");
    return `
      <div class="card">
        <h2>Device</h2>
        <select id="w-dev"><option value="">– pick a device –</option>${opts}${unk ? `<optgroup label="Heard, not set up">${unk}</optgroup>` : ""}</select>
        <label>Where are you / where is it mounted? (saved with each uplink)
          <input id="w-spot" value="${esc(this._spot)}" placeholder="e.g. Barn, north wall, 2 m high"></label>
        ${this._watch ? `<div class="row">
          ${dev?.can_fast ? (dev.walk_test ? `<button id="b-fast-off">Stop fast reporting</button>` : `<button id="b-fast">Fast reporting (30 min)</button>`) : ""}
          <button id="b-sound">${this._sound ? "Sound on" : "Sound off"}</button>
        </div>
        <p class="hint">${dev?.can_fast ? "Fast reporting makes the device report every minute while you walk, then puts its interval back. " : ""}Most Milesight devices also send an uplink when you press their button briefly.</p>` : ""}
      </div>
      ${this._watch ? `
      <div class="card">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          ${q ? `<span class="pill" style="background:${q[1]}">${q[0]}</span>` : `<span class="pill" style="background:var(--disabled-text-color,#999)">Waiting…</span>`}
          <span class="muted">Last uplink <b id="ago">${ago(last?.ts)}</b>${last?.fcnt != null ? ` · frame ${last.fcnt}` : ""}</span>
        </div>
        <div class="big">
          <div class="tile"><div class="k">RSSI (dBm)</div><div class="v">${last?.rssi ?? "–"}</div></div>
          <div class="tile"><div class="k">SNR (dB)</div><div class="v">${last?.snr ?? "–"}</div></div>
          <div class="tile"><div class="k">Spreading factor</div><div class="v">${last?.sf ? "SF" + last.sf : "–"}</div></div>
          <div class="tile"><div class="k">Margin (dB)</div><div class="v">${last?.margin ?? "–"}</div></div>
          <div class="tile"><div class="k">Gateways</div><div class="v">${last ? (last.gateways || []).length : "–"}</div></div>
        </div>
        ${last?.gateways?.length ? `<p class="hint">${last.gateways.map((g) => `${esc(g.name)}: ${g.rssi ?? "–"} dBm / ${g.snr ?? "–"} dB`).join(" · ")}</p>` : ""}
        ${sum ? `<p class="hint">This test: ${sum.n} uplinks · RSSI ${sum.low} to ${sum.best} dBm · worst <b>${QUALITY[sum.worst][0]}</b></p>` : `<p class="hint">Waiting for the device's next uplink…</p>`}
        <label>Note (optional)<input id="w-note" value="${esc(this._note || "")}" placeholder="e.g. moved to the window side"></label>
        <div class="row"><button class="primary" id="b-save">Save result</button><button id="b-clear">Clear</button></div>
      </div>
      <div class="card scroll"><h2>Uplinks</h2>
        <table><tr><th>Time</th><th>Spot</th><th>RSSI</th><th>SNR</th><th>SF</th><th>Signal</th><th>Gateways</th></tr>${rows || `<tr><td colspan="7" class="muted">None yet</td></tr>`}</table>
      </div>` : ""}`;
  }

  _bind() {
    const $ = (id) => this.shadowRoot.getElementById(id);
    const on = (id, ev, fn) => { const el = $(id); if (el) el.addEventListener(ev, fn); };
    on("t-add", "click", () => { this._tab = "add"; this._msg = null; this._render(); });
    on("t-walk", "click", () => { this._tab = "walk"; this._msg = null; this._stopCamera(); this._loadDevices(); this._render(); });
    on("b-app", "click", () => this._scanWithApp());
    on("b-cam", "click", () => (this._camera ? (this._stopCamera(), this._render()) : this._startCamera()));
    on("b-photo", "click", () => $("file").click());
    on("file", "change", (e) => this._photo(e.target.files[0]));
    on("b-pick", "click", () => $("file2").click());
    on("file2", "change", (e) => this._photo(e.target.files[0]));
    on("b-read", "click", () => { const t = $("manual").value.trim(); if (t) this._gotText(t); });
    on("manual", "keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const t = e.target.value.trim(); if (t) this._gotText(t); } });
    on("b-add", "click", () => this._add());
    on("manual", "input", (e) => { this._manual = e.target.value; });
    for (const [id, key, prop] of [["f-deveui", "deveui", "value"], ["f-model", "model", "value"], ["f-name", "name", "value"],
                                   ["f-area", "area", "value"], ["f-key", "key", "value"], ["f-register", "register", "checked"]]) {
      on(id, id === "f-model" || id === "f-register" ? "change" : "input", (e) => { this._form = { ...(this._form || {}), [key]: e.target[prop] }; });
    }
    on("b-again", "click", () => { this._parsed = null; this._form = {}; this._msg = null; this._render(); });
    on("b-walk-existing", "click", () => { const d = this._parsed.deveui; this._parsed = null; this._msg = null; this._startWatch(d); });
    on("b-walk-added", "click", () => { this._msg = null; this._startWatch(this._lastAdded.deveui); });
    on("w-dev", "change", (e) => { this._msg = null; if (e.target.value) this._startWatch(e.target.value); else { this._stopWatch(); this._watch = null; this._render(); } });
    on("w-spot", "input", (e) => { this._spot = e.target.value; });
    on("w-note", "input", (e) => { this._note = e.target.value; });
    on("b-fast", "click", () => this._fast(true));
    on("b-fast-off", "click", () => this._fast(false));
    on("b-sound", "click", () => { this._sound = !this._sound; this._render(); });
    on("b-save", "click", () => this._save());
    on("b-clear", "click", () => { this._samples = []; this._msg = null; this._render(); });
  }
}

if (!customElements.get("milesight-commissioning")) customElements.define("milesight-commissioning", MilesightCommissioning);
