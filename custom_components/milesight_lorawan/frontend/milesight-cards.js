/*! Milesight LoRaWAN — self-contained Lovelace cards (no external dependencies).
 *  Cards: milesight-gateway-card, milesight-device-card, milesight-trend-card, milesight-level-card.
 *  Colours come from the Home Assistant theme (CSS custom properties) so the cards match the user's
 *  dashboard in both light and dark mode; status colours are always paired with an icon + label. */
(function () {
  "use strict";
  if (window.__milesightCardsLoaded) return;
  window.__milesightCardsLoaded = true;

  // ---------------------------------------------------------------- helpers
  const h = (tag, props, kids) => {
    const el = document.createElement(tag);
    if (props) for (const k in props) {
      if (k === "style" && typeof props[k] === "object") Object.assign(el.style, props[k]);
      else if (k === "class") el.className = props[k];
      else if (k in el || k.startsWith("on")) el[k] = props[k];
      else el.setAttribute(k, props[k]);
    }
    for (const c of [].concat(kids || [])) if (c != null) el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    return el;
  };
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const esc = (s) => String(s == null ? "" : s);

  function ago(iso) {
    if (!iso) return "—";
    const t = typeof iso === "number" ? iso : Date.parse(iso);
    if (!Number.isFinite(t)) return "—";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return `${Math.round(s)}s ago`;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  }

  // entities on the same device as `entityId`, so a card pointed at one sensor can find its siblings
  function siblings(hass, entityId) {
    try {
      const reg = hass.entities || {};
      const dev = reg[entityId] && reg[entityId].device_id;
      if (!dev) return [];
      return Object.keys(reg).filter((e) => reg[e].device_id === dev);
    } catch (e) { return []; }
  }
  function findSibling(hass, entityId, pred) {
    for (const e of siblings(hass, entityId)) {
      const st = hass.states[e];
      if (st && pred(e, st)) return e;
    }
    return null;
  }
  const byClass = (cls) => (e, st) => (st.attributes.device_class === cls);
  const byName = (re) => (e, st) => re.test(e) || re.test(String(st.attributes.friendly_name || ""));

  function fireMoreInfo(node, entityId) {
    if (!entityId) return;
    node.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  const BASE_CSS = `
    :host{--ms-good:var(--success-color,#2e7d32);--ms-warn:var(--warning-color,#e67e00);
      --ms-bad:var(--error-color,#c62828);--ms-accent:var(--primary-color,#1e88e5);
      --ms-ink:var(--primary-text-color,#111);--ms-ink2:var(--secondary-text-color,#666);
      --ms-line:var(--divider-color,rgba(127,127,127,.25));--ms-surface:var(--ha-card-background,var(--card-background-color,#fff));}
    ha-card{overflow:hidden}
    .wrap{padding:14px 16px}
    .row{display:flex;align-items:center;gap:10px}
    .between{justify-content:space-between}
    .title{font-size:15px;font-weight:600;color:var(--ms-ink);margin:0}
    .sub{font-size:12px;color:var(--ms-ink2)}
    .muted{color:var(--ms-ink2)}
    .big{font-size:30px;font-weight:650;color:var(--ms-ink);line-height:1.05}
    .unit{font-size:14px;color:var(--ms-ink2);font-weight:500;margin-left:3px}
    .chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;padding:2px 8px;border-radius:999px;
      border:1px solid var(--ms-line);color:var(--ms-ink2)}
    .dot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;background:var(--ms-ink2)}
    .grid{display:grid;gap:10px 14px}
    .click{cursor:pointer}
    svg{display:block}
    .lbl{font-size:11px;color:var(--ms-ink2);text-transform:uppercase;letter-spacing:.04em}
    .val{font-size:15px;color:var(--ms-ink);font-weight:600}
    .es{display:flex;flex-direction:column;align-items:center;text-align:center;gap:7px;padding:26px 18px;color:var(--ms-ink2)}
    .es ha-icon{--mdc-icon-size:34px;color:var(--ms-ink2);opacity:.55}
    .es.warn ha-icon{color:var(--ms-warn);opacity:1}
    .es.ok ha-icon{color:var(--ms-good);opacity:1}
    .es .et{font-size:15px;font-weight:600;color:var(--ms-ink)}
    .es .eh{font-size:13px;max-width:340px;line-height:1.4}
    .es .ea{margin-top:4px;font:inherit;font-size:13px;color:var(--ms-accent);background:none;border:1px solid var(--ms-line);
      border-radius:9px;padding:7px 14px;cursor:pointer}
    .es .ea:hover{border-color:var(--ms-accent)}
    .warnbar{display:flex;align-items:center;gap:9px;margin-bottom:10px;padding:9px 12px;border-radius:9px;font-size:13px;
      background:color-mix(in srgb,var(--ms-bad) 11%,transparent);color:var(--ms-bad);box-shadow:inset 3px 0 0 var(--ms-bad)}
    .warnbar.warn{background:color-mix(in srgb,var(--ms-warn) 12%,transparent);color:var(--ms-warn);box-shadow:inset 3px 0 0 var(--ms-warn)}
  `;
  function navigate(path) {
    history.pushState(null, "", path);
    window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
  }
  function emptyState(o) {
    o = o || {};
    return h("div", { class: "es " + (o.tone || "") }, [
      o.icon ? h("ha-icon", { icon: o.icon }) : null,
      h("div", { class: "et" }, o.title || "Nothing here yet"),
      o.hint ? h("div", { class: "eh" }, o.hint) : null,
      o.action ? h("button", { class: "ea", onclick: o.action.onClick }, o.action.label) : null,
    ]);
  }
  // normalise a preset's `empty` (string or object) into emptyState options
  function emptyOpts(empty, fallbackIcon) {
    if (!empty) return { icon: fallbackIcon, title: "Nothing here yet" };
    if (typeof empty === "string") return { icon: fallbackIcon, title: empty };
    return { icon: empty.icon || fallbackIcon, ...empty };
  }

  class Base extends HTMLElement {
    constructor() { super(); this.attachShadow({ mode: "open" }); this._cfg = {}; }
    setConfig(cfg) { this._cfg = cfg || {}; this._lastSig = null; this._render(); }
    set hass(hass) {
      this._hass = hass;
      const sig = this._sig();                 // re-render only when a watched entity changed (keeps animations steady)
      if (sig !== null && sig === this._lastSig) return;
      this._lastSig = sig; this._render();
    }
    _watch() { return this._cfg && this._cfg.entity ? [this._cfg.entity] : null; }
    _sig() {
      const ids = this._watch(); if (!ids || !this._hass) return null;
      return ids.map((id) => { const s = this._hass.states[id]; return s ? id + "=" + s.state + "@" + s.last_changed : id + "∅"; }).join("|");
    }
    getCardSize() { return 3; }
    _st(id) { return (this._hass && id && this._hass.states[id]) || null; }
    _card(body) {
      const style = h("style"); style.textContent = BASE_CSS + (this._css || "");
      if (this._cfg && this._cfg.bare) {                   // chrome-less: for nesting inside the device panel
        const wrap = h("div", { style: { display: "block" } }); wrap.appendChild(style); wrap.appendChild(body);
        this.shadowRoot.replaceChildren(wrap); return wrap;
      }
      const card = h("ha-card");
      card.appendChild(style); card.appendChild(body);
      this.shadowRoot.replaceChildren(card);
      return card;
    }
    _err(msg) { this._card(h("div", { class: "wrap" }, [h("div", { class: "muted" }, msg)])); }
  }

  // ================================================================ gateway health
  class GatewayCard extends Base {
    static getStubConfig() { return { entity: "" }; }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg, st = this._st(cfg.entity);
      const online = st ? !["off", "unavailable", "offline", "false"].includes(String(st.state).toLowerCase()) : null;
      const a = st ? st.attributes : {};
      const name = cfg.name || (a && a.friendly_name) || "Gateway";
      const color = online == null ? "var(--ms-ink2)" : online ? "var(--ms-good)" : "var(--ms-bad)";
      const metric = (label, value) => h("div", {}, [h("div", { class: "lbl" }, label), h("div", { class: "val" }, esc(value))]);
      const conn = a.connection || a.conn_label || (a.semtech && a.mqtt ? "Semtech UDP + MQTT" : a.semtech ? "Semtech UDP" : a.mqtt ? "MQTT" : "—");
      const loc = a.location ? `${a.location.lat}, ${a.location.lon}` : (a.latitude != null && a.longitude != null ? `${a.latitude}, ${a.longitude}` : "—");
      const body = h("div", { class: "wrap click", onclick: () => fireMoreInfo(this, cfg.entity) }, [
        h("div", { class: "row between" }, [
          h("div", { class: "row" }, [h("span", { class: "dot", style: { background: color } }), h("p", { class: "title" }, esc(name))]),
          h("span", { class: "chip" }, [h("span", { class: "dot", style: { background: color } }), online == null ? "unknown" : online ? "Online" : "Offline"]),
        ]),
        h("div", { class: "sub", style: { marginTop: "2px" } }, esc(a.eui ? String(a.eui).toUpperCase() : (a.model || ""))),
        h("div", { class: "grid", style: { gridTemplateColumns: "repeat(3,1fr)", marginTop: "12px" } }, [
          metric("Packets today", a.packets_today != null ? a.packets_today : (a.packets != null ? a.packets : "—")),
          metric("Devices heard", a.devices != null ? a.devices : (a.device_count != null ? a.device_count : "—")),
          metric("Last heard", a.last_heard ? ago(a.last_heard * (String(a.last_heard).length <= 11 ? 1000 : 1)) : (st ? ago(st.last_changed) : "—")),
          metric("Connection", conn),
          metric("Clock", a.clock || a.time || (a.clock_synced ? "synced" : "—")),
          metric("Location", loc),
        ]),
      ]);
      this._card(body);
    }
  }

  // ================================================================ device status
  class DeviceCard extends Base {
    static getStubConfig() { return { entity: "" }; }
    _watch() {
      const id = this._cfg.entity; if (!id || !this._hass) return id ? [id] : null;
      const bat = this._cfg.battery || findSibling(this._hass, id, byClass("battery"));
      const sig = this._cfg.signal || findSibling(this._hass, id, byClass("signal_strength")) || findSibling(this._hass, id, byName(/rssi/i));
      return [id, bat, sig].filter(Boolean);
    }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg, id = cfg.entity;
      const st = this._st(id);
      if (!st) return this._err("Set an entity.");
      const a = st.attributes;
      const name = cfg.name || a.friendly_name || id;
      const batId = cfg.battery || findSibling(this._hass, id, byClass("battery"));
      const rssiId = cfg.signal || findSibling(this._hass, id, byClass("signal_strength")) || findSibling(this._hass, id, byName(/rssi/i));
      const bat = batId ? num(this._st(batId) && this._st(batId).state) : null;
      const rssi = rssiId ? num(this._st(rssiId) && this._st(rssiId).state) : null;
      const online = !["unavailable", "unknown"].includes(String(st.state).toLowerCase());
      const headVal = st.state, headUnit = a.unit_of_measurement || "";

      // battery ring
      const batColor = bat == null ? "var(--ms-ink2)" : bat <= 10 ? "var(--ms-bad)" : bat <= 25 ? "var(--ms-warn)" : "var(--ms-good)";
      const R = 15, C = 2 * Math.PI * R, bpct = bat == null ? 0 : clamp(bat, 0, 100);
      const ring = h("div", { class: "click", onclick: () => fireMoreInfo(this, batId), title: "Battery" }, [svgNS(`
        <svg width="46" height="46" viewBox="0 0 40 40">
          <circle cx="20" cy="20" r="${R}" fill="none" stroke="var(--ms-line)" stroke-width="4"/>
          <circle cx="20" cy="20" r="${R}" fill="none" stroke="${batColor}" stroke-width="4" stroke-linecap="round"
            stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - bpct / 100)}" transform="rotate(-90 20 20)"
            style="transition:stroke-dashoffset .6s ease"/>
          <text x="20" y="21" text-anchor="middle" font-size="11" font-weight="700" fill="var(--ms-ink)">${bat == null ? "—" : Math.round(bat)}</text>
          <text x="20" y="30" text-anchor="middle" font-size="6" fill="var(--ms-ink2)">%</text>
        </svg>`)]);

      // signal bars (RSSI dBm → 4 bars)
      const bars = rssiBars(rssi);
      const sig = h("div", { class: "click", onclick: () => fireMoreInfo(this, rssiId), title: rssi == null ? "No signal sensor" : `${rssi} dBm` }, [svgNS(sigSvg(bars))]);

      const body = h("div", { class: "wrap" }, [
        h("div", { class: "row between" }, [
          h("div", {}, [
            h("p", { class: "title click", onclick: () => fireMoreInfo(this, id) }, esc(name)),
            h("div", { class: "sub" }, [
              h("span", { class: "dot", style: { background: online ? "var(--ms-good)" : "var(--ms-bad)", display: "inline-block", marginRight: "6px" } }),
              online ? "Online" : "Offline", " · last seen ", ago(st.last_changed),
            ]),
          ]),
          h("div", { class: "row", style: { gap: "12px" } }, [sig, ring]),
        ]),
        h("div", { class: "row click", style: { marginTop: "10px", alignItems: "baseline" }, onclick: () => fireMoreInfo(this, id) }, [
          h("span", { class: "big" }, esc(headVal)), headUnit ? h("span", { class: "unit" }, esc(headUnit)) : null,
        ]),
        cfg.sparkline === false ? null : h(MINI_TAG),
      ]);
      this._card(body);
      // feed the inline sparkline
      const spark = body.querySelector(MINI_TAG);
      if (spark) { spark.setConfig({ entity: id, hours: cfg.hours || 24, height: 42, bare: true }); spark.hass = this._hass; }
    }
  }

  function rssiBars(rssi) {
    if (rssi == null) return 0;
    if (rssi >= -95) return 4;      // excellent
    if (rssi >= -105) return 3;     // good
    if (rssi >= -115) return 2;     // fair
    if (rssi >= -125) return 1;     // poor
    return 1;
  }
  function sigSvg(bars) {
    const col = bars >= 3 ? "var(--ms-good)" : bars === 2 ? "var(--ms-warn)" : bars <= 1 ? "var(--ms-bad)" : "var(--ms-ink2)";
    let r = "";
    for (let i = 0; i < 4; i++) {
      const on = i < bars, x = i * 9, hh = 8 + i * 6, y = 28 - hh;
      r += `<rect x="${x}" y="${y}" width="6" height="${hh}" rx="2" fill="${on ? col : "var(--ms-line)"}"/>`;
    }
    return `<svg width="38" height="30" viewBox="0 0 33 30">${r}</svg>`;
  }
  function svgNS(markup) {
    const tmp = document.createElement("div"); tmp.innerHTML = markup.trim();
    return tmp.firstChild;
  }
  function batteryRingSvg(bat, size) {
    size = size || 46;
    const R = 15, C = 2 * Math.PI * R, p = bat == null ? 0 : clamp(bat, 0, 100);
    const col = bat == null ? "var(--ms-ink2)" : bat <= 10 ? "var(--ms-bad)" : bat <= 25 ? "var(--ms-warn)" : "var(--ms-good)";
    return svgNS(`<svg width="${size}" height="${size}" viewBox="0 0 40 40">
      <circle cx="20" cy="20" r="${R}" fill="none" stroke="var(--ms-line)" stroke-width="4"/>
      <circle cx="20" cy="20" r="${R}" fill="none" stroke="${col}" stroke-width="4" stroke-linecap="round"
        stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - p / 100)}" transform="rotate(-90 20 20)" style="transition:stroke-dashoffset .6s ease"/>
      <text x="20" y="21" text-anchor="middle" font-size="11" font-weight="700" fill="var(--ms-ink)">${bat == null ? "—" : Math.round(bat)}</text>
      <text x="20" y="30" text-anchor="middle" font-size="6" fill="var(--ms-ink2)">%</text></svg>`);
  }
  const signalBarsSvg = (rssi) => svgNS(sigSvg(rssiBars(rssi)));

  // ================================================================ mini trend (SVG sparkline / area)
  class TrendCard extends Base {
    static getStubConfig() { return { entity: "", hours: 24 }; }
    setConfig(cfg) { this._cfg = cfg || {}; this._data = null; this._loadedFor = null; this._render(); }
    set hass(hass) {
      const first = !this._hass; this._hass = hass;
      if (first || this._loadedFor !== this._cfg.entity) this._load();
      const sig = this._sig();
      if (!first && sig !== null && sig === this._lastSig) return;
      this._lastSig = sig; this._render();
    }
    async _load() {
      const id = this._cfg.entity; if (!id || !this._hass) return;
      this._loadedFor = id;
      const hours = this._cfg.hours || 24;
      const start = new Date(Date.now() - hours * 3600 * 1000).toISOString();
      try {
        const r = await this._hass.callWS({ type: "history/history_during_period", start_time: start,
          entity_ids: [id], minimal_response: true, no_attributes: true });
        const series = (r && (r[id] || (Array.isArray(r) && r[0]))) || [];
        this._data = series.map((p) => [p.lu ? p.lu * 1000 : Date.parse(p.last_changed || p.lc), num(p.s != null ? p.s : p.state)])
          .filter((p) => p[1] != null);
        this._render();
      } catch (e) { this._data = []; this._render(); }
    }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg, id = cfg.entity, st = this._st(id);
      const a = st ? st.attributes : {};
      const unit = a.unit_of_measurement || "";
      const name = cfg.name || (a && a.friendly_name) || id;
      const pts = this._data || [];
      const W = 300, H = cfg.height || 90, pad = cfg.bare ? 2 : 6;
      let plot;
      if (pts.length < 2) {
        plot = h("div", { class: "muted", style: { fontSize: "12px", padding: "8px 0" } }, this._data ? "No history yet" : "Loading…");
      } else {
        const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
        const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
        const sx = (x) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad);
        const sy = (y) => (H - pad) - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
        const line = pts.map((p, i) => `${i ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join(" ");
        const area = `${line} L${sx(x1).toFixed(1)},${(H - pad).toFixed(1)} L${sx(x0).toFixed(1)},${(H - pad).toFixed(1)} Z`;
        const last = pts[pts.length - 1], up = ys[ys.length - 1] >= ys[0];
        const stroke = cfg.color || "var(--ms-accent)";
        plot = svgNS(`<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
          <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stop-color="${stroke}" stop-opacity="0.28"/><stop offset="1" stop-color="${stroke}" stop-opacity="0"/>
          </linearGradient></defs>
          <path d="${area}" fill="url(#g)"/>
          <path d="${line}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
          <circle cx="${sx(last[0]).toFixed(1)}" cy="${sy(last[1]).toFixed(1)}" r="3.2" fill="${stroke}"/>
        </svg>`);
      }
      if (cfg.bare) { this._card(h("div", { style: { padding: "0 4px 6px" } }, [plot])); return; }
      const cur = st ? st.state : "—";
      const body = h("div", { class: "wrap" }, [
        h("div", { class: "row between" }, [
          h("p", { class: "title click", onclick: () => fireMoreInfo(this, id) }, esc(name)),
          h("div", { class: "row", style: { alignItems: "baseline" } }, [h("span", { class: "val" }, esc(cur)), unit ? h("span", { class: "unit" }, esc(unit)) : null]),
        ]),
        h("div", { class: "sub", style: { marginBottom: "6px" } }, `last ${cfg.hours || 24} h`),
        plot,
      ]);
      this._card(body);
    }
  }

  // ================================================================ animated level (tank / silo / dam / bin)
  const PURPOSE_SHAPE = { water_tank: "tank", fuel_tank: "tank", silo: "silo", bin: "bin", flood: "dam", pool: "dam" };
  const LIQUID = { water_tank: "water", pool: "water", flood: "water", fuel_tank: "fuel", silo: "grain", bin: "waste" };

  class LevelCard extends Base {
    static getStubConfig() { return { entity: "", shape: "tank" }; }
    _watch() {
      if (this._cfg.entity) return [this._cfg.entity];
      return this._discover().map((x) => x.id);           // auto mode: re-render when any tank changes
    }
    _discover() {
      const role = this._cfg.role || "tank";
      const out = [];
      for (const id in this._hass.states) {
        if (!id.startsWith("sensor.")) continue;
        if (this._hass.states[id].attributes.milesight_role === role) out.push({ id, st: this._hass.states[id] });
      }
      return out.sort((p, q) => String(p.st.attributes.device || p.id).localeCompare(String(q.st.attributes.device || q.id)));
    }
    _model(st, cfg) {
      const a = st.attributes;
      let pct = num(a.fill != null ? a.fill : null);        // Milesight tank sensor: state=litres, fill=percent
      if (pct == null) pct = (a.unit_of_measurement === "%") ? num(st.state) : null;
      if (pct == null) pct = num(a.fill_percent != null ? a.fill_percent : a.percentage);
      pct = pct == null ? null : clamp(pct, 0, 100);
      const purpose = cfg.purpose || a.purpose || "";
      const shape = cfg.shape || PURPOSE_SHAPE[purpose] || inferShape(a, st) || "tank";
      const liquidKind = cfg.liquid || LIQUID[purpose] || (shape === "silo" ? "grain" : shape === "bin" ? "waste" : "water");
      const low = num(a.low_pct != null ? a.low_pct : (cfg.low != null ? cfg.low : 20)) || 20;
      let state = pct == null ? "unknown" : pct <= (low / 2) ? "bad" : pct <= low ? "warn" : "ok";
      if (a.sudden_drop === true) state = "bad";
      else if (a.low === true && state === "ok") state = "warn";
      const litres = a.litres != null ? a.litres : (a.volume_l != null ? a.volume_l : (a.unit_of_measurement !== "%" ? num(st.state) : null));
      return { pct, shape, state, liq: liquidColor(liquidKind, state),
        name: cfg.name || a.device || a.friendly_name,
        litres, cap: a.capacity_l != null ? a.capacity_l : a.capacity,
        days: a.days_left != null ? a.days_left : a.days_to_empty, low };
    }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg;
      if (!cfg.entity) {                                    // auto mode: a vessel per discovered tank
        const items = this._discover();
        if (!items.length) return this._card(h("div", { class: "wrap" }, emptyState(emptyOpts(cfg.empty || {
          icon: "mdi:storage-tank-outline", title: "No tanks or silos yet",
          hint: "Open a level sensor (EM500-UDL, WTS …) → Configure → Tank or silo." }, "mdi:storage-tank-outline"))));
        const cells = items.map(({ id, st }) => {
          const m = this._model(st, cfg);
          const chipC = m.state === "bad" ? "var(--ms-bad)" : m.state === "warn" ? "var(--ms-warn)" : "var(--ms-good)";
          return h("div", { class: "click", onclick: () => fireMoreInfo(this, id),
            style: { textAlign: "center", padding: "4px" } }, [
            this._vesselEl(m, 86),
            h("div", { class: "val", style: { marginTop: "4px" } }, [m.pct == null ? "—" : `${Math.round(m.pct)}`, h("span", { class: "unit" }, "%")]),
            h("div", { class: "sub", style: { display: "flex", gap: "5px", justifyContent: "center", alignItems: "center" } },
              [h("span", { class: "dot", style: { background: chipC } }), esc(m.name || "")]),
          ]);
        });
        return this._card(h("div", { class: "wrap" }, [
          cfg.title === false ? null : h("p", { class: "title", style: { marginBottom: "10px" } }, cfg.title || "Tanks & silos"),
          h("div", { class: "grid", style: { gridTemplateColumns: `repeat(auto-fill,minmax(${cfg.min_width || 110}px,1fr))`, gap: "6px" } }, cells),
        ]));
      }
      const st = this._st(cfg.entity);
      if (!st) return this._err("Set a fill-percent entity.");
      const m = this._model(st, cfg), id = cfg.entity;
      const stLabel = m.state === "bad" ? "Critically low" : m.state === "warn" ? "Low" : m.state === "ok" ? "OK" : "—";
      const stColor = m.state === "bad" ? "var(--ms-bad)" : m.state === "warn" ? "var(--ms-warn)" : "var(--ms-good)";
      const kv = (l, v) => v == null || v === "" ? null : h("div", {}, [h("div", { class: "lbl" }, l), h("div", { class: "val" }, esc(v))]);
      const body = h("div", { class: "wrap" }, [
        h("div", { class: "row between" }, [
          h("p", { class: "title click", onclick: () => fireMoreInfo(this, id) }, esc(m.name || id)),
          h("span", { class: "chip" }, [h("span", { class: "dot", style: { background: stColor } }), stLabel]),
        ]),
        h("div", { class: "row", style: { gap: "16px", marginTop: "8px", alignItems: "center" } }, [
          h("div", { class: "click", onclick: () => fireMoreInfo(this, id), style: { flex: "0 0 auto" } }, [this._vesselEl(m, 112)]),
          h("div", { style: { flex: "1 1 auto" } }, [
            h("div", { class: "row", style: { alignItems: "baseline" } }, [
              h("span", { class: "big" }, m.pct == null ? "—" : `${Math.round(m.pct)}`), h("span", { class: "unit" }, "%"),
            ]),
            h("div", { class: "grid", style: { gridTemplateColumns: "1fr 1fr", marginTop: "8px" } }, [
              kv("Volume", m.litres != null ? `${Math.round(m.litres).toLocaleString()} L` : null),
              kv("Capacity", m.cap != null ? `${Math.round(m.cap).toLocaleString()} L` : null),
              kv("Days left", m.days != null ? `${m.days}` : null),
              kv("Low alarm", `${m.low} %`),
            ]),
          ]),
        ]),
      ]);
      this._card(body);
    }
    _vesselEl(m, width) {
      const el = this._vessel(m.shape, m.pct == null ? 0 : m.pct, m.liq, m.state);
      el.setAttribute("width", width); el.setAttribute("height", Math.round(width * 1.34));
      return el;
    }

    _vessel(shape, pct, liq, state) {
      // viewBox 100x130; liquid rises from the bottom. A wave crest animates across the surface.
      const W = 100, H = 130, fillH = (H - 20) * (pct / 100);
      const topY = (H - 10) - fillH;                           // surface y
      const waveId = "w" + Math.random().toString(36).slice(2, 7);
      const clip = "c" + waveId;
      const outline = vesselPath(shape, W, H);
      const amp = pct <= 0 ? 0 : 3;
      const wave = `M0,${topY} q 12,-${amp} 25,0 t 25,0 t 25,0 t 25,0 t 25,0 V${H} H0 Z`;
      const svg = `
        <svg width="112" height="150" viewBox="0 0 ${W} ${H}" role="img" aria-label="${Math.round(pct)} percent full">
          <defs>
            <clipPath id="${clip}"><path d="${outline.inner}"/></clipPath>
            <linearGradient id="${waveId}" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stop-color="${liq}" stop-opacity="0.95"/><stop offset="1" stop-color="${liq}" stop-opacity="0.75"/>
            </linearGradient>
          </defs>
          <path d="${outline.inner}" fill="var(--ms-surface)" stroke="none"/>
          <g clip-path="url(#${clip})">
            <path d="${wave}" fill="url(#${waveId})" style="transition:transform .7s ease">
              <animateTransform attributeName="transform" type="translate" from="-100 0" to="0 0" dur="2.4s" repeatCount="indefinite"/>
            </path>
            <path d="${wave}" fill="${liq}" opacity="0.45">
              <animateTransform attributeName="transform" type="translate" from="0 0" to="-100 0" dur="3.2s" repeatCount="indefinite"/>
            </path>
          </g>
          <path d="${outline.inner}" fill="none" stroke="var(--ms-line)" stroke-width="1" opacity="0.6"/>
          <path d="${outline.body}" fill="none" stroke="var(--ms-ink)" stroke-width="2.4" stroke-linejoin="round" opacity="0.85"/>
          ${outline.extra || ""}
        </svg>`;
      return svgNS(svg);
    }
  }

  function inferShape(a, st) {
    const icon = String((a && a.icon) || (st && st.attributes.icon) || "").toLowerCase();
    if (icon.includes("silo")) return "silo";
    if (icon.includes("trash") || icon.includes("bin") || icon.includes("delete")) return "bin";
    if (icon.includes("wave") || icon.includes("flood") || icon.includes("pool")) return "dam";
    return null;
  }
  function liquidColor(kind, state) {
    if (state === "bad") return "var(--ms-bad)";
    if (state === "warn") return "var(--ms-warn)";
    if (kind === "fuel") return "#b8860b";
    if (kind === "grain") return "#c9a227";
    if (kind === "waste") return "#6d7b3a";
    return "var(--ms-accent)";                                  // water / default
  }
  function vesselPath(shape, W, H) {
    const b = H - 10, t = 10;   // body bottom / top
    if (shape === "silo") {
      return {
        body: `M20,${b} V40 L50,${t} L80,40 V${b} Z`,
        inner: `M22,${b - 1} V41 L50,${t + 3} L78,41 V${b - 1} Z`,
        extra: `<line x1="20" y1="60" x2="80" y2="60" stroke="var(--ms-ink)" stroke-width="1.2" opacity="0.3"/>
                <line x1="20" y1="85" x2="80" y2="85" stroke="var(--ms-ink)" stroke-width="1.2" opacity="0.3"/>`,
      };
    }
    if (shape === "dam") {   // water body between sloped banks
      return {
        body: `M6,${t + 18} L26,${b} H74 L94,${t + 18}`,
        inner: `M9,${t + 20} L27,${b - 1} H73 L91,${t + 20} Z`,
        extra: `<path d="M6,${t + 18} L26,${b} H74 L94,${t + 18}" fill="none" stroke="var(--ms-ink2)" stroke-width="1" opacity="0.4"/>`,
      };
    }
    if (shape === "bin") {   // waste bin: lid + tapered body
      return {
        body: `M24,28 H76 L72,${b} H28 Z`,
        inner: `M26,30 H74 L70.5,${b - 1} H29.5 Z`,
        extra: `<rect x="20" y="20" width="60" height="8" rx="2" fill="none" stroke="var(--ms-ink)" stroke-width="2.4"/>
                <rect x="44" y="14" width="12" height="6" rx="2" fill="none" stroke="var(--ms-ink)" stroke-width="2"/>`,
      };
    }
    // tank: rounded vertical cylinder
    return {
      body: `M24,22 Q24,${t} 50,${t} Q76,${t} 76,22 V${b} Q76,${b + 8} 50,${b + 8} Q24,${b + 8} 24,${b} Z`,
      inner: `M25,22 Q25,${t + 1} 50,${t + 1} Q75,${t + 1} 75,22 V${b} Q75,${b + 6} 50,${b + 6} Q25,${b + 6} 25,${b} Z`,
      extra: `<ellipse cx="50" cy="22" rx="26" ry="8" fill="none" stroke="var(--ms-ink)" stroke-width="1.5" opacity="0.5"/>`,
    };
  }

  // ================================================================ table (row + cell issue highlighting)
  // A column spec: {key, label, align, unit, grow, fmt, warn:{lt|gt|eq|in}, bad:{…}}.
  // A row rule: {when:{field, eq|lt|gt|truthy}, level:"bad"|"warn"}.
  function breach(rule, v) {
    if (rule == null) return false;
    if ("lt" in rule) return num(v) != null && num(v) < rule.lt;
    if ("gt" in rule) return num(v) != null && num(v) > rule.gt;
    if ("eq" in rule) return v === rule.eq;
    if ("in" in rule) return [].concat(rule.in).includes(v);
    if ("truthy" in rule) return !!v === rule.truthy;
    return false;
  }
  const PRESETS = {
    devices: {
      role: "fleet_total", path: "devices", title: "Devices",
      columns: [
        { key: "name", label: "Device", grow: true },
        { key: "model", label: "Model", muted: true },
        { key: "area", label: "Area", muted: true },
        { key: "battery", label: "Batt", unit: "%", align: "right", warn: { lt: 25 }, bad: { lt: 15 } },
        { key: "rssi", label: "RSSI", unit: "dBm", align: "right", warn: { lt: -110 }, bad: { lt: -120 } },
        { key: "snr", label: "SNR", unit: "dB", align: "right", warn: { lt: -7 } },
        { key: "sf", label: "SF", align: "right", fmt: (v) => v == null ? "—" : "SF" + v, warn: { gt: 10 } },
        { key: "packet_loss", label: "Loss", unit: "%", align: "right", warn: { gt: 5 }, bad: { gt: 20 } },
        { key: "firmware", label: "FW", align: "right", muted: true },
      ],
      row: [{ when: { field: "online", eq: false }, level: "bad" },
            { when: { field: "battery_low", truthy: true }, level: "warn" }],
      issue: (r) => r.online === false ? "offline" : r.battery_low ? "low battery" : null,
      empty: { icon: "mdi:access-point-network", title: "No devices yet",
        hint: "Add devices in Settings → Devices & services → Discovered, or register them on the gateway." },
      allStale: (rows) => rows.length && rows.every((r) => r.online === false)
        ? "Every device is offline — check the gateway and its network link." : null,
    },
    offline: {
      role: "fleet_total", path: "devices", title: "Offline",
      filter: (r) => (num(r.offline_hours) != null && num(r.offline_hours) >= 24) || !r.last_seen,
      columns: [
        { key: "name", label: "Device", grow: true },
        { key: "model", label: "Model", muted: true },
        { key: "area", label: "Area", muted: true },
        { key: "offline_hours", label: "Silent", align: "right",
          fmt: (v) => v == null ? "—" : (v >= 24 ? `${(v / 24).toFixed(1)} d` : `${Math.round(v)} h`) },
        { key: "last_seen", label: "Last seen", align: "right", fmt: (v) => v ? fmtTime(v) : "never" },
        { key: "battery", label: "Batt", unit: "%", align: "right", warn: { lt: 25 }, bad: { lt: 15 } },
      ],
      row: [{ when: { field: "online", eq: false }, level: "bad" }],
      issue: () => "offline",
      empty: { tone: "ok", icon: "mdi:check-circle-outline", title: "All devices reporting",
        hint: "Every device has been heard in the last 24 hours." },
    },
    weak: {
      role: "fleet_total", path: "devices", title: "Weak or lossy",
      filter: (r) => ["poor", "fair", "bad", "very_poor"].includes(r.signal) || num(r.packet_loss) > 5 || num(r.rssi) < -110,
      columns: [
        { key: "name", label: "Device", grow: true },
        { key: "rssi", label: "RSSI", unit: "dBm", align: "right", warn: { lt: -110 }, bad: { lt: -120 } },
        { key: "snr", label: "SNR", unit: "dB", align: "right", warn: { lt: -7 } },
        { key: "sf", label: "SF", align: "right", fmt: (v) => v == null ? "—" : "SF" + v, warn: { gt: 10 } },
        { key: "gateways_heard", label: "GW", align: "right" },
        { key: "packet_loss", label: "Loss", unit: "%", align: "right", warn: { gt: 5 }, bad: { gt: 20 } },
        { key: "gateway", label: "Best gw", muted: true },
      ],
      row: [{ when: { field: "signal", in: ["poor", "bad", "very_poor"] }, level: "bad" },
            { when: { field: "signal", eq: "fair" }, level: "warn" }],
      issue: (r) => ["poor", "bad", "very_poor"].includes(r.signal) ? "weak signal" : (r.signal === "fair" ? "fair signal" : null),
      empty: { tone: "ok", icon: "mdi:check-circle-outline", title: "Good signal everywhere",
        hint: "No weak or lossy links." },
    },
    firmware: {
      role: "fleet_total", path: "devices", title: "Firmware",
      transform: (rows) => {
        const by = {};
        for (const d of rows) { const m = d.model || "?"; (by[m] = by[m] || []).push(d); }
        return Object.keys(by).sort().map((m) => {
          const ds = by[m], vers = [...new Set(ds.filter((d) => d.firmware).map((d) => d.firmware))].sort();
          return { model: m, count: ds.length, versions: vers.join(", "), mixed: vers.length > 1, none: vers.length === 0 };
        });
      },
      columns: [
        { key: "model", label: "Model", grow: true },
        { key: "count", label: "Devices", align: "right" },
        { key: "versions", label: "Firmware", fmt: (v, r) => r.none ? "not reported yet" : (r.mixed ? `mixed: ${v}` : `all on ${v}`) },
      ],
      row: [{ when: { field: "mixed", truthy: true }, level: "warn" }],
      issue: (r) => r.mixed ? "mixed versions" : null,
      empty: { icon: "mdi:chip", title: "No devices yet" },
    },
    // ---- per-device role tables (one entity per row, from its attributes) ----
    cold_chain: {
      source: "entities", role: "cold_chain", title: "Fridges & freezers",
      columns: [
        { key: "device", label: "Unit", grow: true },
        { key: "area", label: "Area", muted: true },
        { key: "temperature", label: "Now", align: "right", fmt: (v) => v == null ? "—" : `${v} °C` },
        { key: "low", label: "Allowed", align: "right", fmt: (v, r) => `${r.low ?? "–"}…${r.high ?? "–"} °C` },
        { key: "min_today", label: "Min / Max", align: "right", fmt: (v, r) => `${r.min_today ?? "–"} / ${r.max_today ?? "–"}` },
        { key: "_state", label: "Out today", align: "right", fmt: (v, r) => `${v == null || v === "unknown" ? 0 : v} min${r.excursions_today ? ` (${r.excursions_today}×)` : ""}` },
        { key: "door_open", label: "Door", fmt: (v) => v == null ? "—" : (v ? "open" : "closed") },
      ],
      row: [{ when: { field: "alarm", truthy: true }, level: "bad" }],
      issue: (r) => r.alarm ? "out of range" : null,
      empty: { icon: "mdi:fridge-outline", title: "No fridge or freezer probes",
        hint: "Open a temperature sensor → Configure → Purpose → Fridge / cold room or Freezer." },
    },
    compressors: {
      source: "entities", role: "load", group: "cold_chain", title: "Compressors",
      columns: [
        { key: "device", label: "Compressor", grow: true },
        { key: "area", label: "Area", muted: true },
        { key: "running", label: "Now", fmt: (v) => v ? "Running" : "Off" },
        { key: "duty_today", label: "Duty today", align: "right", unit: "%" },
        { key: "duty_24h", label: "Duty 24 h", align: "right", unit: "%" },
        { key: "starts_today", label: "Starts", align: "right" },
      ],
      row: [{ when: { field: "ran_too_long", truthy: true }, level: "bad" }, { when: { field: "not_running", truthy: true }, level: "bad" }],
      issue: (r) => (r.ran_too_long || r.not_running) ? "check compressor" : null,
      empty: { icon: "mdi:heat-pump-outline", title: "No compressor clamps",
        hint: "Fit a CT clamp on the fridge → Configure → Purpose → Fridge / cold room." },
    },
    loads: {
      source: "entities", role: "load", title: "Loads",
      columns: [
        { key: "device", label: "Load", grow: true },
        { key: "purpose_label", label: "What", muted: true },
        { key: "area", label: "Area", muted: true },
        { key: "running", label: "Now", fmt: (v) => v ? "On" : "Off" },
        { key: "_state", label: "Run today", align: "right", fmt: (v) => `${v == null ? "–" : v} h` },
        { key: "duty_24h", label: "Duty 24 h", align: "right", unit: "%" },
        { key: "starts_today", label: "Starts", align: "right" },
      ],
      row: [{ when: { field: "ran_too_long", truthy: true }, level: "bad" }, { when: { field: "not_running", truthy: true }, level: "bad" },
            { when: { field: "after_hours", truthy: true }, level: "warn" }, { when: { field: "service_due", truthy: true }, level: "warn" }],
      issue: (r) => (r.ran_too_long || r.not_running) ? "check load" : (r.after_hours ? "after hours" : (r.service_due ? "service due" : null)),
      empty: { icon: "mdi:lightning-bolt", title: "No loads yet",
        hint: "Fit a CT clamp or smart socket → Configure → Purpose (AC, lighting, geyser …)." },
    },
    pumps: {
      source: "entities", role: "pump", title: "Pumps",
      columns: [
        { key: "device", label: "Pump", grow: true },
        { key: "area", label: "Area", muted: true },
        { key: "running", label: "Now", fmt: (v) => v ? "Running" : "Off" },
        { key: "current", label: "Current", align: "right", unit: "A" },
        { key: "normal_current", label: "Normal", align: "right", fmt: (v) => v == null ? "learning" : `${v} A` },
        { key: "starts_last_hour", label: "Starts/h", align: "right" },
        { key: "_state", label: "Run h", align: "right" },
      ],
      row: [{ when: { field: "dry_run", truthy: true }, level: "bad" }, { when: { field: "overload", truthy: true }, level: "bad" },
            { when: { field: "short_cycling", truthy: true }, level: "warn" }],
      issue: (r) => r.dry_run ? "dry-run" : (r.overload ? "overload" : (r.short_cycling ? "short-cycling" : null)),
      empty: { icon: "mdi:pump", title: "No pumps yet",
        hint: "Open a current clamp (CT101 / CT103 …) → Configure → Purpose → Pump." },
    },
    pivots: {
      source: "entities", role: "pivot", title: "Centre pivots",
      columns: [
        { key: "device", label: "Pivot", grow: true },
        { key: "status", label: "Status" },
        { key: "angle", label: "Angle", align: "right", fmt: (v) => v == null ? "—" : `${Math.round(v)}°` },
        { key: "speed", label: "Speed", align: "right", unit: "%" },
        { key: "finish_in_h", label: "Finishes in", align: "right", fmt: (v) => v == null ? "—" : `${Math.round(v * 10) / 10} h` },
      ],
      row: [{ when: { field: "status", in: ["stalled", "fault", "stuck", "stopped"] }, level: "bad" }],
      issue: (r) => ["stalled", "fault", "stuck", "stopped"].includes(r.status) ? r.status : null,
      empty: { icon: "mdi:rotate-right", title: "No centre pivots",
        hint: "Open the AT101 on the end tower → Configure → Centre pivot." },
    },
    // ---- fleet batteries, service log and gateways (from the aggregate sensors) ----
    batteries: {
      role: "fleet_total", path: "devices", title: "Batteries",
      filter: (r) => r.battery != null,
      transform: (rows) => rows.slice().sort((a, b) => {
        const da = a.battery_days_left, db = b.battery_days_left;
        if (da == null && db == null) return 0;
        if (da == null) return 1; if (db == null) return -1; return da - db;
      }),
      columns: [
        { key: "name", label: "Device", grow: true },
        { key: "area", label: "Area", muted: true },
        { key: "battery", label: "Battery", unit: "%", align: "right", warn: { lt: 25 }, bad: { lt: 15 } },
        { key: "battery_days_left", label: "Days left", align: "right", warn: { lt: 90 }, bad: { lt: 30 },
          fmt: (v, r) => v == null ? (r.battery_low ? "low now" : "—") : v },
        { key: "battery_replace_by", label: "Replace by", align: "right", fmt: (v) => v || "—" },
        { key: "battery_forecast", label: "Forecast", muted: true, fmt: (v) => v || "—" },
      ],
      row: [{ when: { field: "battery_low", truthy: true }, level: "warn" },
            { when: { field: "battery_days_left", lt: 30 }, level: "bad" }],
      issue: (r) => (r.battery_low || (r.battery_days_left != null && r.battery_days_left <= 30)) ? "replace soon" : null,
      empty: { icon: "mdi:battery-check", title: "No battery forecasts yet",
        hint: "Forecasts appear after about two weeks of readings." },
    },
    service: {
      role: "fleet_total", path: "devices", title: "Service history",
      transform: (rows) => {
        const out = [];
        for (const d of rows) for (const e of (d.service || [])) out.push({ ...e, name: d.name });
        out.sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
        return out.slice(0, 50);
      },
      columns: [
        { key: "at", label: "Date", align: "right", fmt: (v) => v ? fmtTime(v) : "—" },
        { key: "name", label: "Device", grow: true },
        { key: "kind", label: "Type", fmt: (v) => ({ battery_replaced: "Battery", firmware: "Firmware", profile: "Profile", maintenance: "Maintenance" }[v] || v || "Note") },
        { key: "text", label: "Note", grow: true },
        { key: "by", label: "By", muted: true, fmt: (v) => v || "—" },
      ],
      empty: { icon: "mdi:history", title: "No service entries yet",
        hint: "Battery and firmware changes log themselves; add notes with the Log service action." },
    },
    gateways: {
      role: "net_gateways_online", path: "gateways", title: "Gateways",
      transform: (rows) => rows.slice().sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""))),
      columns: [
        { key: "name", label: "Gateway", grow: true },
        { key: "online", label: "Status", fmt: (v) => v === true ? "Online" : (v === false ? "Offline" : "Unknown") },
        { key: "packets_today", label: "Packets today", align: "right" },
        { key: "devices_today", label: "Devices today", align: "right" },
      ],
      row: [{ when: { field: "online", eq: false }, level: "bad" }],
      issue: (r) => r.online === false ? "offline" : null,
      empty: { icon: "mdi:router-wireless", title: "No gateways seen yet",
        hint: "Gateways appear with the first uplink that lists them." },
    },
    tanks: {
      source: "entities", role: "tank", title: "Tanks & silos",
      columns: [
        { key: "device", label: "Tank", grow: true },
        { key: "area", label: "Area", muted: true },
        { key: "fill", label: "Fill", align: "right", unit: "%", warn: { lt: 20 } },
        { key: "_state", label: "Volume", align: "right",
          fmt: (v, r) => (v == null || v === "unknown") ? "—" : `${v} / ${r.capacity_l != null ? Math.round(r.capacity_l) : "–"} L` },
        { key: "usage_per_day", label: "Uses/day", align: "right", fmt: (v) => v == null ? "—" : `${Math.round(v)} L` },
        { key: "days_left", label: "Days left", align: "right", fmt: (v) => v == null ? "—" : v },
      ],
      row: [{ when: { field: "sudden_drop", truthy: true }, level: "bad" }, { when: { field: "low", truthy: true }, level: "warn" }],
      issue: (r) => r.sudden_drop ? "sudden drop" : (r.low ? "low" : null),
      empty: { icon: "mdi:storage-tank-outline", title: "No tanks or silos yet",
        hint: "Open a level sensor's device → Configure → Tank or silo." },
    },
    // ---- building analytics (sensors tagged by `kind`, grouped by HA area) ----
    comfort: {
      source: "entities", match: { attr: "kind", eq: "comfort", has: "area" }, title: "Comfort per area",
      transform: (rows) => rows.slice().sort((a, b) => String(a.area || "").localeCompare(String(b.area || ""))),
      columns: [
        { key: "area", label: "Area", grow: true },
        { key: "_state", label: "Comfort", align: "right", warn: { lt: 50 },
          fmt: (v) => { const n = num(v); return (n == null || n < 0) ? "—" : `${n} / 100`; } },
        { key: "temperature", label: "Temp", align: "right", fmt: (v) => v == null ? "—" : `${v} °C` },
        { key: "humidity", label: "Humidity", align: "right", fmt: (v) => v == null ? "—" : `${v} %` },
        { key: "co2", label: "CO₂", align: "right", fmt: (v) => v == null ? "—" : `${v} ppm` },
      ],
      row: [{ when: { field: "_state", lt: 50 }, level: "warn" }],
      empty: { icon: "mdi:emoticon-happy-outline", title: "No area comfort sensors yet",
        hint: "Assign devices with temperature / humidity / CO₂ to areas." },
    },
    utilisation: {
      source: "entities", match: { has: "utilisation_today" }, title: "Utilisation today",
      transform: (rows) => rows.slice().sort((a, b) => String(a.area || "").localeCompare(String(b.area || ""))),
      columns: [
        { key: "area", label: "Area", grow: true },
        { key: "utilisation_today", label: "Utilisation", align: "right", unit: "%",
          fmt: (v) => v == null ? "closed / outside hours" : `${v} %` },
      ],
      empty: { icon: "mdi:chart-donut", title: "No occupancy sensors yet",
        hint: "People counters, PIR and desk sensors fill this in." },
    },
  };
  function fmtTime(iso) {
    const t = Date.parse(iso); if (!Number.isFinite(t)) return "—";
    try { return new Date(t).toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }); }
    catch (e) { return new Date(t).toISOString().slice(0, 16).replace("T", " "); }
  }

  class TableCard extends Base {
    static getStubConfig() { return { preset: "devices" }; }
    _pre() { return (this._cfg.preset && PRESETS[this._cfg.preset]) || {}; }
    _watch() {
      if (this._cfg.entity) return [this._cfg.entity];
      const p = this._pre(), ids = [];
      if (p.match) {
        const m = p.match;
        for (const id in this._hass.states) {
          if (!id.startsWith("sensor.")) continue;
          const a = this._hass.states[id].attributes;
          if (m.attr && a[m.attr] !== m.eq) continue;
          if (m.has && a[m.has] === undefined) continue;
          if (!m.attr && !m.has) continue;
          ids.push(id);
        }
        return ids;
      }
      const role = this._cfg.role || p.role;
      for (const id in this._hass.states) if (id.startsWith("sensor.") && this._hass.states[id].attributes.milesight_role === role) ids.push(id);
      return ids;
    }
    _rows() {
      const p = this._pre(), path = this._cfg.path || p.path || "devices";
      let rows;
      if (Array.isArray(this._cfg.rows)) {
        rows = this._cfg.rows;
      } else if (p.source === "entities") {
        // one row per entity, from its attributes. Matched either by milesight_role (optionally + group),
        // or by a generic attribute match {attr, eq} (e.g. kind=comfort) for the analytics sensors.
        const S = this._hass.states, reg = this._hass.entities || {}, dom = (p.domain || "sensor") + ".";
        const role = this._cfg.role || p.role, grp = p.group, m = p.match;
        rows = [];
        for (const id in S) {
          if (!id.startsWith(dom)) continue;
          const a = S[id].attributes;
          if (m) { if (a[m.attr] !== m.eq || (m.has && a[m.has] === undefined)) continue; }
          else if (a.milesight_role !== role || (grp && a.group !== grp)) continue;
          rows.push({ ...a, _state: S[id].state, entity_id: id, device_id: reg[id] && reg[id].device_id });
        }
      } else {
        let src = this._cfg.entity ? this._st(this._cfg.entity) : null;
        if (!src) { const ids = this._watch(); src = ids.length ? this._st(ids[0]) : null; }
        rows = (src && Array.isArray(src.attributes[path])) ? src.attributes[path] : [];
      }
      if (p.transform) rows = p.transform(rows);
      if (p.filter) rows = rows.filter(p.filter);
      return rows;
    }
    _openRow(r) {
      if (!r.device_id && !r.entity_id) return;
      if (this._cfg.link === "more-info") {
        const reg = this._hass.entities || {};
        const ent = r.entity_id || (r.device_id && Object.keys(reg).find((e) => reg[e].device_id === r.device_id));
        if (ent) return fireMoreInfo(this, ent);
        if (r.device_id) { history.pushState(null, "", "/config/devices/device/" + r.device_id); window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true })); }
        return;
      }
      // default: route to the per-device page (a "device" view in the same dashboard)
      const view = this._cfg.device_view || "device";
      const base = location.pathname.replace(/\/[^/]*$/, "/" + view);
      const q = r.device_id ? "device=" + encodeURIComponent(r.device_id) : "entity=" + encodeURIComponent(r.entity_id);
      history.pushState(null, "", base + "?" + q);
      window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
    }
    setConfig(cfg) {
      this._cfg = cfg || {};
      try { const s = localStorage.getItem(this._pkey()); if (s) this._sort = JSON.parse(s); } catch (e) { /* private mode */ }
      this._lastSig = null; this._render();
    }
    _pkey() { const c = this._cfg; return "msTableSort:" + (c.preset || "") + ":" + (c.entity || "") + ":" + (c.title || ""); }
    _saveSort() {
      try { this._sort ? localStorage.setItem(this._pkey(), JSON.stringify(this._sort)) : localStorage.removeItem(this._pkey()); }
      catch (e) { /* private mode */ }
    }
    _disp(c, r) {
      const v = r[c.key];
      let d = c.fmt ? c.fmt(v, r) : (v == null || v === "" ? "" : v);
      if (!c.fmt && c.unit != null && v != null && v !== "") d = `${v} ${c.unit}`;
      return d;
    }
    _exportCsv(cols, rows) {
      const q = (s) => `"${String(s == null ? "" : s).replace(/"/g, '""')}"`;
      const lines = [cols.map((c) => q(c.label || c.key)).join(",")]
        .concat(rows.map((r) => cols.map((c) => q(this._disp(c, r))).join(",")));
      try {
        const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = ((this._cfg.title && this._cfg.title !== false ? this._cfg.title : this._cfg.preset) || "table") + ".csv";
        a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      } catch (e) { /* download blocked */ }
    }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg, p = this._pre();
      const cols = cfg.columns || p.columns || [];
      const rowRules = cfg.row || p.row || [];
      const title = cfg.title != null ? cfg.title : p.title;
      const rowLevel = (r) => {
        let lvl = null;
        for (const rr of rowRules) {
          const op = Object.keys(rr.when).find((k) => k !== "field");
          if (breach({ [op]: rr.when[op] }, r[rr.when.field])) lvl = rr.level === "bad" ? "bad" : (lvl || rr.level);
        }
        return lvl;
      };
      let rows = this._rows();
      if (cfg.only_issues) rows = rows.filter((r) => rowLevel(r));
      const total = rows.length;
      const q = (this._q || "").trim().toLowerCase();
      if (q) rows = rows.filter((r) => cols.some((c) => String(this._disp(c, r)).toLowerCase().includes(q)));
      const sortable = cfg.sortable !== false;
      if (this._sort) {                                    // user-chosen column sort
        const { key, dir } = this._sort;
        rows = rows.slice().sort((a, b) => {
          const va = a[key], vb = b[key], na = num(va), nb = num(vb);
          let c = (na != null && nb != null) ? na - nb : String(va == null ? "" : va).localeCompare(String(vb == null ? "" : vb));
          return dir === "desc" ? -c : c;
        });
      }
      const css = `
        table{width:100%;border-collapse:collapse;font-size:13px}
        th{font:600 11px/1 inherit;color:var(--ms-ink2);text-transform:uppercase;letter-spacing:.03em;
          text-align:left;padding:6px 8px;border-bottom:1px solid var(--ms-line)}
        td{padding:7px 8px;border-bottom:1px solid var(--ms-line);color:var(--ms-ink);white-space:nowrap}
        tr:last-child td{border-bottom:none}
        td.muted{color:var(--ms-ink2)}
        td.r,th.r{text-align:right;font-variant-numeric:tabular-nums}
        td.grow{white-space:normal}
        tr.issue td{position:relative}
        tr.bad{background:color-mix(in srgb, var(--ms-bad) 9%, transparent)}
        tr.warn{background:color-mix(in srgb, var(--ms-warn) 10%, transparent)}
        tr.bad td:first-child{box-shadow:inset 3px 0 0 var(--ms-bad)}
        tr.warn td:first-child{box-shadow:inset 3px 0 0 var(--ms-warn)}
        td.cell-bad{color:var(--ms-bad);font-weight:700}
        td.cell-warn{color:var(--ms-warn);font-weight:700}
        .cw{overflow-x:auto}
        .ico{margin-right:5px;font-size:11px}
        .empty{color:var(--ms-ink2);padding:10px 2px}
        th.s{cursor:pointer;user-select:none}
        th.s:hover{color:var(--ms-ink)}
        .ar{margin-left:4px;opacity:.7;font-size:10px}
        tr.rowclick{cursor:pointer}
        tr.rowclick:hover td{background:color-mix(in srgb, var(--ms-ink) 5%, transparent)}
        .tb{display:flex;align-items:center;gap:8px;margin-bottom:8px}
        .search{flex:1 1 auto;min-width:0;font:inherit;font-size:13px;color:var(--ms-ink);
          background:color-mix(in srgb, var(--ms-ink) 5%, transparent);border:1px solid var(--ms-line);
          border-radius:8px;padding:6px 10px;outline:none}
        .search:focus{border-color:var(--ms-accent)}
        .count{font-size:12px;color:var(--ms-ink2);white-space:nowrap}
        .csv{flex:0 0 auto;font:inherit;font-size:12px;color:var(--ms-ink2);cursor:pointer;
          background:none;border:1px solid var(--ms-line);border-radius:8px;padding:5px 10px}
        .csv:hover{color:var(--ms-ink);border-color:var(--ms-accent)}
      `;
      this._css = css;
      const showSearch = cfg.search !== false && total > 5;
      const showCsv = cfg.csv !== false && total > 0;
      let searchInput = null;
      const toolbar = (showSearch || showCsv) ? h("div", { class: "tb" }, [
        showSearch ? (searchInput = h("input", { class: "search", type: "text", value: this._q || "",
          placeholder: "Filter…", oninput: (e) => { this._q = e.target.value; this._focusSearch = true; this._render(); } })) : h("div", { style: { flex: "1" } }),
        (q && rows.length !== total) ? h("span", { class: "count" }, `${rows.length}/${total}`) : null,
        showCsv ? h("button", { class: "csv", onclick: () => this._exportCsv(cols, rows), title: "Download CSV" }, "⭳ CSV") : null,
      ]) : null;
      const head = h("tr", {}, cols.map((c) => {
        const active = this._sort && this._sort.key === c.key;
        const th = h("th", { class: (c.align === "right" ? "r " : "") + (sortable ? "s" : "") },
          [esc(c.label || c.key), active ? h("span", { class: "ar" }, this._sort.dir === "desc" ? "▼" : "▲") : null]);
        if (sortable) th.onclick = () => {
          const dir = (active && this._sort.dir === "asc") ? "desc" : "asc";
          this._sort = { key: c.key, dir }; this._saveSort(); this._render();
        };
        return th;
      }));
      const body = rows.map((r) => {
        const lvl = rowLevel(r);
        const issue = p.issue ? p.issue(r) : null;
        const clickable = !!(r.device_id || r.entity_id);
        const tds = cols.map((c, i) => {
          let v = r[c.key];
          const cellBad = breach(c.bad, v), cellWarn = !cellBad && breach(c.warn, v);
          let disp = c.fmt ? c.fmt(v, r) : (v == null || v === "" ? "—" : v);
          if (!c.fmt && c.unit != null && v != null && v !== "") disp = `${v} ${c.unit}`;
          const cls = [c.align === "right" ? "r" : "", c.grow ? "grow" : "", c.muted ? "muted" : "",
            cellBad ? "cell-bad" : cellWarn ? "cell-warn" : ""].filter(Boolean).join(" ");
          const kids = (i === 0 && issue) ? [h("span", { class: "ico", title: issue }, lvl === "bad" ? "⛔" : "⚠"), esc(disp)] : esc(disp);
          return h("td", { class: cls }, kids);
        });
        const tr = h("tr", { class: "issue " + (lvl || "") + (clickable ? " rowclick" : "") }, tds);
        if (clickable) tr.onclick = () => this._openRow(r);
        return tr;
      });
      // a "data not arriving" warning: every row present but all offline/stale — a safety signal, not setup guidance
      const staleMsg = (!q && p.allStale) ? p.allStale(rows) : null;
      const warnbar = staleMsg ? h("div", { class: "warnbar" },
        [h("ha-icon", { icon: "mdi:alert" }), h("span", {}, staleMsg)]) : null;
      let table;
      if (rows.length) {
        table = h("div", { class: "cw" }, [h("table", {}, [h("thead", {}, head), h("tbody", {}, body)])]);
      } else if (q) {
        table = emptyState({ icon: "mdi:magnify", title: "Nothing matches your filter",
          action: { label: "Clear filter", onClick: () => { this._q = ""; this._render(); } } });
      } else {
        table = emptyState(emptyOpts(cfg.empty || p.empty, "mdi:table-search"));
      }
      this._card(h("div", { class: "wrap" }, [
        title === false ? null : h("p", { class: "title", style: { marginBottom: "8px" } }, title || "Devices"),
        toolbar, warnbar, table,
      ]));
      if (this._focusSearch && searchInput) {              // keep the caret in the filter box while typing
        const el = this.shadowRoot.querySelector(".search");
        if (el) { el.focus(); const n = el.value.length; try { el.setSelectionRange(n, n); } catch (e) { /* ignore */ } }
        this._focusSearch = false;
      }
    }
  }

  // ================================================================ gauge (multi-type, switchable, animated)
  const GTYPES = {
    arc: { start: -135, sweep: 270, needle: true, label: "Arc" },
    semicircle: { start: -90, sweep: 180, needle: true, label: "Half" },
    ring: { start: 0, sweep: 359.99, needle: false, label: "Ring" },
    bar: { bar: true, label: "Bar" },
  };
  const gpolar = (cx, cy, r, deg) => { const a = (deg - 90) * Math.PI / 180; return [cx + r * Math.cos(a), cy + r * Math.sin(a)]; };
  function garc(cx, cy, r, start, sweep) {
    const [x0, y0] = gpolar(cx, cy, r, start), [x1, y1] = gpolar(cx, cy, r, start + sweep);
    return `M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${Math.abs(sweep) > 180 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
  }
  function niceStep(range, target) {
    const raw = (range || 1) / (target || 6), mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
    return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
  }
  function niceTicks(mn, mx, target) {
    const step = niceStep(mx - mn, target), out = [];
    for (let v = Math.ceil(mn / step - 1e-9) * step; v <= mx + 1e-9; v += step) out.push(Math.round(v / step) * step);
    return { ticks: out, step };
  }
  function fmtTick(v) {
    const r = Math.round(v * 100) / 100;
    return Math.abs(r) >= 1000 ? r.toLocaleString() : String(r);
  }
  const gColorName = { good: "var(--ms-good)", warn: "var(--ms-warn)", bad: "var(--ms-bad)", accent: "var(--ms-accent)",
    green: "var(--ms-good)", yellow: "var(--ms-warn)", amber: "var(--ms-warn)", red: "var(--ms-bad)" };
  const gResolve = (c) => gColorName[c] || c || "var(--ms-accent)";

  class GaugeCard extends Base {
    static getStubConfig() { return { entity: "", min: 0, max: 100 }; }
    setConfig(cfg) { this._cfg = cfg || {}; this._type = this._loadType(); this._built = false; this._g = null; this._render(); }
    set hass(hass) {
      this._hass = hass;
      const st = this._st(this._cfg.entity);
      const sig = st ? st.state + "@" + st.last_changed : "∅";
      if (!this._built) { this._render(); return; }
      if (sig !== this._lastSig) { this._lastSig = sig; this._update(); }
    }
    _types() { return (this._cfg.types || ["arc", "semicircle", "ring", "bar"]).filter((t) => GTYPES[t]); }
    _tkey() { const c = this._cfg; return "msGaugeType:" + (c.entity || "") + ":" + (c.title || c.name || ""); }
    _loadType() {
      let t = this._cfg.shape || "arc";
      try { const s = localStorage.getItem(this._tkey()); if (s && GTYPES[s]) t = s; } catch (e) { /* private */ }
      return GTYPES[t] ? t : "arc";
    }
    _setType(t) { this._type = t; this._built = false; try { localStorage.setItem(this._tkey(), t); } catch (e) { /* private */ } this._render(); }
    _segs() {
      const c = this._cfg;
      if (Array.isArray(c.segments)) return c.segments.map((s) => ({ from: num(s.from), color: gResolve(s.color) })).sort((a, b) => a.from - b.from);
      if (c.severity) { const s = c.severity, o = [];
        if (s.green != null) o.push({ from: num(s.green), color: "var(--ms-good)" });
        if (s.yellow != null) o.push({ from: num(s.yellow), color: "var(--ms-warn)" });
        if (s.red != null) o.push({ from: num(s.red), color: "var(--ms-bad)" });
        return o.sort((a, b) => a.from - b.from); }
      return [];
    }
    _vals() {
      const st = this._st(this._cfg.entity), v = st ? num(st.state) : null;
      const mn = num(this._cfg.min) != null ? num(this._cfg.min) : 0, mx = num(this._cfg.max) != null ? num(this._cfg.max) : 100;
      const pct = v == null ? 0 : clamp((v - mn) / ((mx - mn) || 1) * 100, 0, 100);
      const segs = this._segs();
      let col = this._cfg.color ? gResolve(this._cfg.color) : "var(--ms-accent)";
      for (const s of segs) if (v != null && v >= s.from) col = s.color;
      return { st, v, mn, mx, pct, col, segs, unit: (st && st.attributes.unit_of_measurement) || this._cfg.unit || "" };
    }
    _switcher() {
      const types = this._types();
      if (this._cfg.switchable === false || types.length < 2) return null;
      return h("div", { class: "gsw" }, types.map((t) => {
        const b = h("button", { class: "gt" + (t === this._type ? " on" : ""), onclick: () => this._setType(t) }, GTYPES[t].label);
        return b;
      }));
    }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg, t = this._type, spec = GTYPES[t];
      const name = cfg.name || (this._st(cfg.entity) && this._st(cfg.entity).attributes.friendly_name) || cfg.entity || "Gauge";
      this._css = `
        .gwrap{padding:12px 16px 14px;text-align:center}
        .gsvg{display:block;margin:0 auto;max-width:100%}
        .gval{font-weight:680;fill:var(--ms-ink)}
        .gunit{fill:var(--ms-ink2)}
        .gname{font-size:14px;color:var(--ms-ink);margin-top:2px}
        .gsub{font-size:12px;color:var(--ms-ink2)}
        .gsw{display:inline-flex;gap:4px;margin-top:10px;border:1px solid var(--ms-line);border-radius:999px;padding:3px}
        .gt{font:inherit;font-size:12px;color:var(--ms-ink2);background:none;border:none;border-radius:999px;padding:4px 11px;cursor:pointer}
        .gt.on{background:var(--ms-accent);color:#fff}
        .gtrack{fill:none;stroke:var(--ms-line)}
        .gzone{fill:none;stroke-linecap:butt;stroke-opacity:.5}
        .gfill{fill:none;stroke-linecap:round;transition:stroke-dashoffset .9s cubic-bezier(.25,.1,.25,1),stroke .4s}
        .gneedle,.gmark{transition:transform .9s cubic-bezier(.25,.1,.25,1)}
        .gbarfill{transition:width .9s cubic-bezier(.25,.1,.25,1),fill .4s}
        .gbarmark{transition:transform .9s cubic-bezier(.25,.1,.25,1)}
      `;
      const click = () => fireMoreInfo(this, cfg.entity);
      const vv = this._vals(), segs = vv.segs, mn = vv.mn, mx = vv.mx, zoned = segs.length > 0;
      let svg;
      if (spec.bar) {
        const bx = (val) => 12 + 176 * clamp((val - mn) / ((mx - mn) || 1), 0, 1);
        const zoneRects = zoned ? segs.map((s, i) => {
          const from = Math.max(mn, s.from), to = i + 1 < segs.length ? segs[i + 1].from : mx;
          if (to <= from) return "";
          return `<rect x="${bx(from).toFixed(1)}" y="40" width="${(bx(to) - bx(from)).toFixed(1)}" height="12" fill="${s.color}" fill-opacity="0.5"/>`;
        }).join("") : "";
        svg = svgNS(`<svg class="gsvg" width="100%" height="76" viewBox="0 0 200 76">
          <text class="gval" x="100" y="26" text-anchor="middle" font-size="26" data-val>–</text>
          <rect class="gtrack" x="12" y="40" width="176" height="12" rx="6" stroke-width="0" fill="var(--ms-line)"/>
          ${zoneRects}
          ${zoned ? `<g class="gbarmark" data-marker style="transform:translateX(0px)"><rect x="10" y="35" width="4" height="22" rx="2" fill="var(--ms-ink)"/></g>`
            : `<rect class="gbarfill" x="12" y="40" width="0" height="12" rx="6" data-fill/>`}
          <text class="gsub" x="12" y="68" font-size="10" data-min>0</text>
          <text class="gsub" x="188" y="68" text-anchor="end" font-size="10" data-max>100</text>
        </svg>`);
      } else {
        const ring = t === "ring", half = t === "semicircle";
        const showTicks = cfg.ticks !== false && !ring;      // scale labels for arc / half only
        const cx = 100, cy = half ? 96 : 100, r = ring ? 74 : showTicks ? 60 : 74, sw = ring ? 11 : 12;
        const track = garc(cx, cy, r, spec.start, spec.sweep);
        const valY = ring ? cy + 2 : half ? cy + 30 : cy + 42;    // clear of the needle/pivot
        const vbH = half ? 140 : ring ? 200 : 182;
        const ang = (val) => spec.start + clamp((val - mn) / ((mx - mn) || 1), 0, 1) * spec.sweep;
        let ticksSvg = "";
        if (showTicks) {
          const nt = niceTicks(mn, mx, cfg.tick_count || 6), rt0 = r + sw / 2 + 2, rl = rt0 + 7 + 9;
          const minor = nt.step / (cfg.minor || 5), parts = [];
          // labels at the nice ticks, plus the two endpoints when they are not right next to a tick
          const labels = nt.ticks.slice();
          if (Math.abs(mn - (nt.ticks[0] ?? mn)) > nt.step * 0.35) labels.unshift(mn);
          if (Math.abs(mx - (nt.ticks[nt.ticks.length - 1] ?? mx)) > nt.step * 0.35) labels.push(mx);
          const isLabel = (val) => labels.some((l) => Math.abs(l - val) < minor * 0.5);
          for (let val = mn; val <= mx + 1e-9; val += minor) {
            const maj = isLabel(val) || Math.abs(val / nt.step - Math.round(val / nt.step)) < 1e-6;
            const a = ang(val), [x0, y0] = gpolar(cx, cy, rt0, a), [x1, y1] = gpolar(cx, cy, rt0 + (maj ? 7 : 4), a);
            parts.push(`<line x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}" stroke="var(--ms-ink2)" stroke-width="${maj ? 1.4 : 0.8}" stroke-opacity="${maj ? 0.75 : 0.4}"/>`);
          }
          for (const val of labels) {
            const a = ang(val), [lx, ly] = gpolar(cx, cy, rl, a);
            const anchor = lx > cx + 2 ? "start" : lx < cx - 2 ? "end" : "middle";
            parts.push(`<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" dominant-baseline="central" font-size="9" fill="var(--ms-ink2)">${fmtTick(val)}</text>`);
          }
          ticksSvg = parts.join("");
        }
        const zoneArcs = zoned ? segs.map((s, i) => {
          const from = Math.max(mn, s.from), to = i + 1 < segs.length ? segs[i + 1].from : mx;
          if (to <= from) return "";
          const a0 = ang(from), a1 = ang(to);
          return `<path class="gzone" d="${garc(cx, cy, r, a0, a1 - a0)}" stroke="${s.color}" stroke-width="${sw}"/>`;
        }).join("") : "";
        // ring with zones shows a marker dot; arc/half show the needle
        const marker = (ring && zoned)
          ? `<g class="gmark" data-marker style="transform-origin:${cx}px ${cy}px"><circle cx="${cx}" cy="${cy - r}" r="6" fill="var(--ms-surface)" stroke="var(--ms-ink)" stroke-width="2.5"/></g>`
          : "";
        const vbx = showTicks ? (half ? "-10 -4 220 148" : "-12 -8 224 196") : `0 0 200 ${vbH}`;
        svg = svgNS(`<svg class="gsvg" width="${showTicks ? (half ? 220 : 212) : ring ? 172 : 200}" height="${half ? (showTicks ? 118 : 118) : ring ? 172 : showTicks ? 168 : 158}"
            viewBox="${vbx}">
          <path class="gtrack" d="${track}" stroke-width="${sw}"/>
          ${ticksSvg}
          ${zoneArcs}
          ${zoned ? "" : `<path class="gfill" d="${track}" stroke-width="${sw}" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" data-fill/>`}
          ${marker}
          ${spec.needle ? `<g class="gneedle" data-needle style="transform-origin:${cx}px ${cy}px">
            <line x1="${cx}" y1="${cy + 6}" x2="${cx}" y2="${cy - r + 14}" stroke="var(--ms-ink)" stroke-width="2.6" stroke-linecap="round"/>
            <circle cx="${cx}" cy="${cy}" r="4" fill="var(--ms-ink)"/></g>` : ""}
          <text class="gval" x="${cx}" y="${valY}" text-anchor="middle" font-size="${ring ? 30 : 26}" data-val>–</text>
          <text class="gunit" x="${cx}" y="${valY + (ring ? 16 : 15)}" text-anchor="middle" font-size="12" data-unit></text>
        </svg>`);
      }
      const card = this._card(h("div", { class: "gwrap click", onclick: click }, [
        svg,
        h("div", { class: "gname" }, esc(name)),
        this._switcher(),
      ]));
      // cache refs
      this._g = {
        val: svg.querySelector("[data-val]"), unit: svg.querySelector("[data-unit]"),
        fill: svg.querySelector("[data-fill]"), needle: svg.querySelector("[data-needle]"),
        marker: svg.querySelector("[data-marker]"), min: svg.querySelector("[data-min]"),
        max: svg.querySelector("[data-max]"), spec,
      };
      this._built = true;
      // first paint: let the empty state render, then animate to the value next frame
      requestAnimationFrame(() => this._update());
    }
    _update() {
      if (!this._g || !this._hass) return;
      const { v, mn, mx, pct, col, unit } = this._vals(), g = this._g, spec = g.spec;
      const vt = v == null ? "–" : (Math.round(v * 10) / 10).toString();
      if (g.val) g.val.textContent = vt;
      if (g.unit) g.unit.textContent = unit || "";
      if (spec.bar) {
        if (g.fill) { g.fill.setAttribute("width", (176 * pct / 100).toFixed(1)); g.fill.setAttribute("fill", col); }
        if (g.marker) g.marker.style.transform = `translateX(${(176 * pct / 100).toFixed(1)}px)`;
        if (g.min) g.min.textContent = mn; if (g.max) g.max.textContent = mx;
        if (g.val && unit) g.val.textContent = vt + " " + unit;
      } else {
        if (g.fill) { g.fill.setAttribute("stroke", col); g.fill.style.strokeDashoffset = String(100 - pct); }
        const ang = (spec.start + spec.sweep * pct / 100).toFixed(1);
        if (g.needle) g.needle.style.transform = `rotate(${ang}deg)`;
        if (g.marker) g.marker.style.transform = `rotate(${ang}deg)`;
      }
      this._lastSig = (this._st(this._cfg.entity) || {}).state + "@" + (this._st(this._cfg.entity) || {}).last_changed;
    }
  }

  // ================================================================ device panel (per-device page, by type)
  class DevicePanel extends Base {
    static getStubConfig() { return {}; }
    connectedCallback() { this._loc = () => { if (this._urlMode) this._render(); }; window.addEventListener("location-changed", this._loc); }
    disconnectedCallback() { if (this._loc) window.removeEventListener("location-changed", this._loc); }
    _resolve() {
      const cfg = this._cfg, S = this._hass.states, reg = this._hass.entities || {};
      let deviceId = cfg.device, anchor = cfg.entity;
      this._urlMode = !deviceId && !anchor;
      if (this._urlMode) {
        try { const q = new URLSearchParams(location.search); deviceId = q.get("device"); anchor = anchor || q.get("entity"); } catch (e) { /* */ }
      }
      if (!deviceId && anchor && reg[anchor]) deviceId = reg[anchor].device_id;
      const ents = deviceId ? Object.keys(reg).filter((e) => reg[e].device_id === deviceId && S[e]) : (anchor && S[anchor] ? [anchor] : []);
      return { deviceId, ents };
    }
    _watch() { try { return this._resolve().ents; } catch (e) { return null; } }
    _classify(ents) {
      const S = this._hass.states;
      const dc = (c) => ents.find((e) => S[e].attributes.device_class === c);
      const nm = (re) => ents.find((e) => re.test(e) || re.test(String(S[e].attributes.friendly_name || "")));
      const unit = (u) => ents.find((e) => S[e].attributes.unit_of_measurement === u);
      const level = ents.find((e) => S[e].attributes.milesight_role === "tank" || S[e].attributes.fill != null)
        || (nm(/level|fill|volume/i) && unit("%") ? ents.find((e) => /level|fill|volume/i.test(String(S[e].attributes.friendly_name || e)) && S[e].attributes.unit_of_measurement === "%") : null);
      const co2 = dc("carbon_dioxide") || unit("ppm");
      const temp = dc("temperature"), hum = dc("humidity"), battery = dc("battery");
      const signal = dc("signal_strength") || nm(/rssi/i);
      const current = dc("current");
      const running = ents.find((e) => e.startsWith("binary_sensor.") && (["running", "power", "moving"].includes(S[e].attributes.device_class) || /run|motor|pump/i.test(String(S[e].attributes.friendly_name || ""))));
      let type = "generic", primary = null;
      if (level) { type = "tank"; primary = level; }
      else if (co2) { type = "air"; primary = co2; }
      else if (current || running) { type = "pump"; primary = current || temp; }
      else if (temp) { type = "climate"; primary = temp; }
      else { primary = ents.find((e) => num(S[e].state) != null && S[e].attributes.unit_of_measurement && !["battery", "signal_strength"].includes(S[e].attributes.device_class)); }
      return { type, primary, level, co2, temp, hum, battery, signal, current, running };
    }
    _tile(e, click) {
      const st = this._st(e); if (!st) return null;
      const a = st.attributes;
      return h("div", { class: "mtile click", onclick: () => fireMoreInfo(this, e) }, [
        h("div", { class: "lbl", style: { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, esc(a.friendly_name || e)),
        h("div", { class: "row", style: { alignItems: "baseline", gap: "3px" } }, [
          h("span", { class: "val" }, esc(st.state)), a.unit_of_measurement ? h("span", { class: "unit" }, esc(a.unit_of_measurement)) : null,
        ]),
      ]);
    }
    _sub(tag, cfg) { const el = h(tag); el.setConfig({ ...cfg, bare: true }); el.hass = this._hass; return el; }
    _climateGauge(tempId) {
      const a = this._st(tempId).attributes;
      const lo = num(a.alarm_low), hi = num(a.alarm_high);
      const g = { entity: tempId, shape: "arc", switchable: false };
      if (lo == null && hi == null) {                       // no thresholds known: neutral gauge
        g.min = this._cfg.min != null ? this._cfg.min : -10;
        g.max = this._cfg.max != null ? this._cfg.max : 40; g.color = "accent"; return g;
      }
      const lowB = lo != null ? lo : hi - 10, highB = hi != null ? hi : lo + 10, span = (highB - lowB) || 10;
      const mn = num(a.min_today), mx = num(a.max_today);
      g.min = Math.floor(Math.min(lowB - span * 0.4, mn != null ? mn : lowB));
      g.max = Math.ceil(Math.max(highB + span * 0.4, mx != null ? mx : highB));
      const segs = [{ from: g.min, color: lo != null ? "bad" : "good" }];   // too cold below the low alarm
      if (lo != null) segs.push({ from: lo, color: "good" });
      if (hi != null) segs.push({ from: hi, color: "bad" });                 // too warm above the high alarm
      g.segments = segs; return g;
    }
    _control(e) {
      const st = this._st(e); if (!st) return null;
      const a = st.attributes, dom = e.split(".")[0];
      if (dom === "button") return h("button", { class: "act", onclick: () => this._hass.callService("button", "press", { entity_id: e }) }, esc(a.friendly_name || e));
      if (dom === "switch") { const on = String(st.state) === "on";
        return h("button", { class: "act" + (on ? " on" : ""), onclick: () => this._hass.callService("switch", "toggle", { entity_id: e }) }, `${a.friendly_name || e} · ${on ? "On" : "Off"}`); }
      return h("button", { class: "act", onclick: () => fireMoreInfo(this, e) }, esc(a.friendly_name || e));
    }
    _alerts(ents) {
      const S = this._hass.states, out = [];
      const warnDC = new Set(["problem", "safety", "smoke", "gas", "moisture", "tamper", "heat", "cold"]);
      for (const e of ents) {
        const st = S[e], a = st.attributes;
        if (e.startsWith("binary_sensor.") && String(st.state) === "on" && warnDC.has(a.device_class))
          out.push({ level: "bad", text: a.friendly_name || e });
        if (a.sudden_drop === true) out.push({ level: "bad", text: (a.device || a.friendly_name || e) + ": sudden drop" });
        else if (a.low === true || a.battery_low === true) out.push({ level: "warn", text: (a.friendly_name || e) + (a.low ? ": low level" : ": low battery") });
        if (a.alarm_low != null && num(st.state) != null && (num(st.state) < a.alarm_low || (a.alarm_high != null && num(st.state) > a.alarm_high)))
          out.push({ level: "bad", text: (a.friendly_name || e) + " out of range" });
      }
      return out.slice(0, 4);
    }
    async _loadLog(deviceId, ents) {
      if (this._logFor === deviceId) return;
      this._logFor = deviceId; this._log = null;
      try {
        const start = new Date(Date.now() - 3 * 24 * 3600 * 1000).toISOString();
        const r = await this._hass.callWS({ type: "logbook/get_events", start_time: start, entity_ids: ents });
        this._log = (Array.isArray(r) ? r : []).slice(-14).reverse();
      } catch (e) { this._log = []; }
      this._render();
    }
    _render() {
      if (!this._hass) return;
      const { deviceId, ents } = this._resolve();
      this._css = `
        .dp{padding:0}
        .dhead{display:flex;align-items:center;gap:14px;padding:16px 18px 12px;border-bottom:1px solid var(--ms-line)}
        .dhead .nm{font-size:20px;font-weight:680;color:var(--ms-ink);line-height:1.1}
        .dhead .meta{font-size:12.5px;color:var(--ms-ink2);margin-top:3px}
        .spacer{flex:1}
        .stat{display:flex;align-items:center;gap:12px}
        .sect{padding:14px 18px;border-bottom:1px solid var(--ms-line)}
        .sect:last-child{border-bottom:none}
        .sh{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--ms-ink2);margin:0 0 10px}
        .cols{display:grid;grid-template-columns:1.1fr 1fr;gap:16px}
        @media (max-width:560px){.cols{grid-template-columns:1fr}}
        .tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}
        .mtile{border:1px solid var(--ms-line);border-radius:10px;padding:9px 11px}
        .back{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--ms-ink2);cursor:pointer;margin-bottom:8px}
        .back:hover{color:var(--ms-accent)}
        .pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;padding:3px 10px;border-radius:999px;border:1px solid var(--ms-line);color:var(--ms-ink2)}
        .hero{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
        .alerts{display:flex;flex-wrap:wrap;gap:8px}
        .achip{display:inline-flex;align-items:center;gap:7px;font-size:13px;padding:7px 12px;border-radius:9px}
        .achip.bad{background:color-mix(in srgb,var(--ms-bad) 12%,transparent);color:var(--ms-bad);box-shadow:inset 3px 0 0 var(--ms-bad)}
        .achip.warn{background:color-mix(in srgb,var(--ms-warn) 13%,transparent);color:var(--ms-warn);box-shadow:inset 3px 0 0 var(--ms-warn)}
        .acts{display:flex;flex-wrap:wrap;gap:8px}
        .act{font:inherit;font-size:13px;color:var(--ms-ink);background:none;border:1px solid var(--ms-line);border-radius:9px;padding:8px 13px;cursor:pointer}
        .act:hover{border-color:var(--ms-accent);color:var(--ms-accent)}
        .act.on{border-color:var(--ms-good);color:var(--ms-good)}
        .tl{list-style:none;margin:0;padding:0}
        .tl li{display:flex;gap:10px;padding:6px 0;border-bottom:1px solid var(--ms-line);font-size:13px}
        .tl li:last-child{border-bottom:none}
        .tl .tlw{color:var(--ms-ink2);white-space:nowrap;flex:0 0 auto;font-size:12px}
        .tl .tlm{color:var(--ms-ink)}
      `;
      if (!ents.length) {
        return this._card(h("div", { class: "dp" }, [emptyState(this._urlMode
          ? { icon: "mdi:gesture-tap", title: "No device selected",
              hint: "Pick a device from one of the tables to open its page here." }
          : { icon: "mdi:devices", title: "No device set",
              hint: "Set a device or entity on this card." })]));
      }
      const S = this._hass.states, dev = (this._hass.devices || {})[deviceId] || {};
      const info = this._classify(ents);
      const prim = info.primary ? this._st(info.primary) : null;
      const name = this._cfg.name || dev.name_by_user || dev.name || (prim && prim.attributes.friendly_name) || deviceId || "Device";
      const area = dev.area_id && this._hass.areas && this._hass.areas[dev.area_id] ? this._hass.areas[dev.area_id].name : null;
      const model = dev.model || (prim && prim.attributes.model);
      const online = prim ? !["unavailable", "unknown", "off", "offline"].includes(String(prim.state).toLowerCase()) : null;
      const bat = info.battery ? num(this._st(info.battery).state) : null;
      const rssi = info.signal ? num(this._st(info.signal).state) : null;

      // header
      const head = h("div", { class: "dhead" }, [
        h("div", {}, [
          this._urlMode ? h("div", { class: "back", onclick: () => history.back() }, ["← Back"]) : null,
          h("div", { class: "nm" }, esc(name)),
          h("div", { class: "meta" }, [model ? esc(model) : "", model && area ? " · " : "", area ? esc(area) : ""].join("")),
        ]),
        h("div", { class: "spacer" }),
        h("div", { class: "stat" }, [
          online == null ? null : h("span", { class: "pill" }, [h("span", { class: "dot", style: { background: online ? "var(--ms-good)" : "var(--ms-bad)" } }), online ? "Online" : "Offline"]),
          rssi != null ? signalBarsSvg(rssi) : null,
          bat != null ? batteryRingSvg(bat, 42) : null,
        ]),
      ]);

      // hero (type-specific)
      let hero = null;
      if (info.type === "tank" && info.level) hero = this._sub("milesight-level-card", { entity: info.level });
      else if (info.type === "air" && info.co2) {
        const a = this._st(info.co2).attributes;
        hero = h("div", { class: "hero" }, [
          this._sub("milesight-gauge-card", { entity: info.co2, min: 400, max: 2000, shape: "arc", switchable: false,
            segments: [{ from: 400, color: "good" }, { from: 800, color: "warn" }, { from: 1200, color: "bad" }] }),
          info.temp || info.hum ? h("div", { class: "tiles", style: { flex: "1", minWidth: "140px" } },
            [info.temp, info.hum].filter(Boolean).map((e) => this._tile(e))) : null,
        ]);
      } else if (info.type === "climate" && info.temp) {
        hero = h("div", { class: "hero" }, [
          this._sub("milesight-gauge-card", this._climateGauge(info.temp)),
          info.hum ? h("div", { class: "tiles", style: { flex: "1", minWidth: "140px" } }, [this._tile(info.hum)]) : null,
        ]);
      } else if (info.type === "pump") {
        const run = info.running ? this._st(info.running) : null;
        const runOn = run ? ["on", "true", "running"].includes(String(run.state).toLowerCase()) : null;
        hero = h("div", { class: "hero" }, [
          h("div", { style: { textAlign: "center", minWidth: "120px" } }, [
            h("div", { class: "big", style: { color: runOn ? "var(--ms-good)" : "var(--ms-ink)" } }, runOn == null ? "—" : runOn ? "Running" : "Idle"),
            h("div", { class: "sub" }, "status"),
          ]),
          info.current ? this._sub("milesight-gauge-card", { entity: info.current, min: 0, max: this._cfg.max != null ? this._cfg.max : 20, shape: "semicircle", switchable: false, name: "Current" }) : null,
        ]);
      } else if (info.primary) {
        const a = this._st(info.primary).attributes;
        hero = this._sub("milesight-gauge-card", { entity: info.primary, min: 0, max: num(a.max) != null ? num(a.max) : 100, shape: "arc", switchable: false });
      }

      // trend of the primary metric
      const trend = info.primary ? this._sub("milesight-trend-card", { entity: info.primary, hours: this._cfg.hours || 24 }) : null;

      // secondary metric tiles (numeric entities not already shown)
      const shown = new Set([info.primary, info.battery, info.signal, info.hum, info.temp && info.type === "air" ? info.temp : null].filter(Boolean));
      const metrics = ents.filter((e) => e.startsWith("sensor.") && num(S[e].state) != null && !shown.has(e)
        && !["battery", "signal_strength"].includes(S[e].attributes.device_class) && S[e].attributes.unit_of_measurement);
      const controls = ents.filter((e) => /^(switch|button|number|select)\./.test(e));
      const alerts = this._alerts(ents);
      if (deviceId) this._loadLog(deviceId, ents);          // one-shot per device
      const tl = this._logFor === deviceId ? (this._log || []) : [];

      // walk-test quick action
      const walk = h("button", { class: "act", onclick: () => {
        history.pushState(null, "", "/milesight-commissioning");
        window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
      } }, "↦ Walk test");

      const card = this._card(h("div", { class: "dp" }, [
        head,
        alerts.length ? h("div", { class: "sect" }, [h("div", { class: "alerts" },
          alerts.map((al) => h("div", { class: "achip " + al.level }, [h("span", {}, al.level === "bad" ? "⛔" : "⚠"), esc(al.text)])))]) : null,
        hero ? h("div", { class: "sect" }, [hero]) : null,
        (trend || metrics.length) ? h("div", { class: "sect" }, [h("div", { class: "cols" }, [
          trend ? h("div", {}, [h("p", { class: "sh" }, "Trend"), trend]) : null,
          metrics.length ? h("div", {}, [h("p", { class: "sh" }, "Readings"), h("div", { class: "tiles" }, metrics.map((e) => this._tile(e)))]) : null,
        ])]) : null,
        h("div", { class: "sect" }, [h("p", { class: "sh" }, "Controls"),
          h("div", { class: "acts" }, controls.map((e) => this._control(e)).concat([walk]))]),
        tl.length ? h("div", { class: "sect" }, [h("p", { class: "sh" }, "Activity"),
          h("ul", { class: "tl" }, tl.map((ev) => h("li", {}, [
            h("span", { class: "tlw" }, ago(typeof ev.when === "number" ? (ev.when < 1e12 ? ev.when * 1000 : ev.when) : ev.when)),
            h("span", { class: "tlm" }, esc((ev.name ? ev.name + ": " : "") + (ev.message || ev.state || ""))),
          ])))]) : null,
      ]));
      return card;
    }
  }

  // ================================================================ page header (site · page · health strip)
  class PageHeader extends Base {
    static getStubConfig() { return { title: "Overview" }; }
    _findRole(role) {
      const S = this._hass.states;
      for (const id in S) if (id.startsWith("sensor.") && S[id].attributes.milesight_role === role) return id;
      return null;
    }
    _watch() {
      return [this._findRole("fleet_total"), this._findRole("net_gateways_online"), this._findRole("alerts_open")].filter(Boolean);
    }
    _site() {
      if (this._cfg.site) return this._cfg.site;
      const S = this._hass.states;
      for (const id in S) { const a = S[id].attributes; if (a && a.milesight_role && (a.company || a.site)) return a.company || a.site; }
      return (this._hass.config && this._hass.config.location_name) || "";
    }
    _stats() {
      if (this._cfg.stats === false) return [];
      const S = this._hass.states, out = [];
      const fleet = this._findRole("fleet_total");
      if (fleet) { const d = S[fleet].attributes.devices || [], on = d.filter((x) => x.online).length;
        out.push({ icon: "mdi:access-point-network", value: `${on}/${d.length}`, label: "online", entity: fleet, level: on < d.length ? "warn" : "good" }); }
      const gw = this._findRole("net_gateways_online");
      if (gw) { const g = S[gw].attributes.gateways || [], on = g.filter((x) => x.online).length;
        out.push({ icon: "mdi:router-wireless", value: `${on}/${g.length}`, label: g.length === 1 ? "gateway" : "gateways", entity: gw, level: on < g.length ? "bad" : "good" }); }
      const al = this._findRole("alerts_open");
      if (al) { const a = S[al].attributes.alerts || [], crit = a.some((x) => x.severity === "critical");
        out.push({ icon: "mdi:bell", value: String(a.length), label: a.length === 1 ? "alert" : "alerts", entity: al, level: a.length ? (crit ? "bad" : "warn") : "good" }); }
      return out;
    }
    // sibling Milesight dashboards in the sidebar, so the pages feel like one app (site landing pages first)
    _pages() {
      const panels = (this._hass && this._hass.panels) || {};
      const order = ["maintenance", "tanks", "analytics", "farm", "cold-chain", "energy"];
      const list = [];
      for (const key in panels) {
        const p = panels[key] || {}, url = p.url_path || key;
        const site = url.indexOf("building-") === 0, ms = url.indexOf("milesight-") === 0;
        if (!site && !ms) continue;
        const ord = site ? -1 : ((order.indexOf(url.slice("milesight-".length)) + 1) || 99);
        list.push({ url, title: p.title || url, site, ord,
          icon: p.icon || (site ? "mdi:home-outline" : "mdi:view-dashboard") });
      }
      list.sort((a, b) => a.ord - b.ord || a.title.localeCompare(b.title));
      return list;
    }
    _render() {
      if (!this._hass) return;
      const cfg = this._cfg;
      const site = this._site(), stats = this._stats();
      const accent = cfg.color ? gResolve(cfg.color) : "var(--ms-accent)";
      this._css = `
        .ph{display:flex;align-items:center;gap:15px;padding:15px 18px;flex-wrap:wrap}
        .phi{flex:0 0 auto;width:46px;height:46px;border-radius:13px;display:flex;align-items:center;justify-content:center;
          background:color-mix(in srgb, ${accent} 16%, transparent);color:${accent}}
        .phi ha-icon{--mdc-icon-size:26px}
        .pht{min-width:0;flex:1 1 auto}
        .eye{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--ms-ink2);font-weight:600}
        .h1{font-size:21px;font-weight:700;color:var(--ms-ink);line-height:1.1;margin:1px 0 0}
        .sub{font-size:13px;color:var(--ms-ink2);margin-top:2px}
        .phs{display:flex;gap:8px;flex-wrap:wrap}
        .stat{display:flex;align-items:center;gap:8px;border:1px solid var(--ms-line);border-radius:11px;padding:7px 12px;cursor:pointer}
        .stat:hover{border-color:${accent}}
        .stat ha-icon{--mdc-icon-size:18px;color:var(--ms-ink2)}
        .stat.good ha-icon{color:var(--ms-good)} .stat.warn ha-icon{color:var(--ms-warn)} .stat.bad ha-icon{color:var(--ms-bad)}
        .sv{font-size:15px;font-weight:700;color:var(--ms-ink);line-height:1}
        .sl{font-size:11px;color:var(--ms-ink2);line-height:1.1}
        @media (max-width:520px){.ph{gap:12px}.phs{width:100%}}
        .phnav{display:flex;gap:5px;flex-wrap:wrap;padding:0 14px 11px}
        .navlink{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ms-ink2);
          text-decoration:none;cursor:pointer;padding:6px 11px;border-radius:9px;border:1px solid transparent;white-space:nowrap}
        .navlink:hover{color:var(--ms-ink);background:color-mix(in srgb, var(--ms-ink) 5%, transparent)}
        .navlink.cur{color:${accent};background:color-mix(in srgb, ${accent} 12%, transparent);font-weight:600}
        .navlink ha-icon{--mdc-icon-size:16px}
        .phnav.scroll{flex-wrap:nowrap;overflow-x:auto}
      `;
      const statEl = (s) => h("div", { class: "stat " + (s.level || ""), onclick: () => s.entity && fireMoreInfo(this, s.entity) }, [
        h("ha-icon", { icon: s.icon }), h("div", {}, [h("div", { class: "sv" }, esc(s.value)), h("div", { class: "sl" }, esc(s.label))]),
      ]);
      const pages = cfg.nav === false ? [] : this._pages();
      const cur = (location.pathname.split("/")[1] || "");
      const navEl = pages.length > 1 ? h("div", { class: "phnav" }, pages.map((pg) =>
        h("a", { class: "navlink" + (pg.url === cur ? " cur" : ""), href: "/" + pg.url,
          onclick: (e) => { e.preventDefault(); navigate("/" + pg.url); } },
          [h("ha-icon", { icon: pg.icon }), esc(pg.title)]))) : null;
      this._card(h("div", {}, [
        h("div", { class: "ph" }, [
          h("div", { class: "phi" }, [h("ha-icon", { icon: cfg.icon || "mdi:view-dashboard" })]),
          h("div", { class: "pht" }, [
            site ? h("div", { class: "eye" }, esc(site)) : null,
            h("div", { class: "h1" }, esc(cfg.title || "Overview")),
            cfg.subtitle ? h("div", { class: "sub" }, esc(cfg.subtitle)) : null,
          ]),
          stats.length ? h("div", { class: "phs" }, stats.map(statEl)) : null,
        ]),
        navEl,
      ]));
    }
  }

  // ================================================================ first-run onboarding checklist
  // A live setup guide for a brand-new install. Each step reads the real state, so it ticks itself off as
  // the system comes up, and the whole card hides once the essentials are in place. A step that turns red
  // (devices added but silent) keeps the card visible even after it was dismissed — on a farm, silent
  // sensors are a safety issue, not a cosmetic one.
  const OB_PURPOSE_ROLES = ["cold_chain", "load", "pump", "pivot", "irrigation", "mains", "tank",
    "frost", "climate", "air", "energy", "hvac", "people", "comfort", "level"];
  class OnboardingCard extends Base {
    static getStubConfig() { return {}; }
    _watch() { return null; }                              // re-render on every update (not animated; must catch first data)
    _dkey() { return "msOnboardingDismissed"; }
    _dismissed() { try { return localStorage.getItem(this._dkey()) === "1"; } catch (e) { return false; } }
    _dismiss() { try { localStorage.setItem(this._dkey(), "1"); } catch (e) { /* private */ } this._render(); }
    _steps() {
      const S = this._hass.states;
      const find = (role) => { for (const id in S) if (id.startsWith("sensor.") && S[id].attributes.milesight_role === role) return S[id]; return null; };
      const gw = find("net_gateways_online"), gws = gw ? (gw.attributes.gateways || []) : [];
      const gwOn = gws.filter((x) => x.online).length;
      const fleet = find("fleet_total"), devs = fleet ? (fleet.attributes.devices || []) : [];
      const on = devs.filter((x) => x.online).length;
      let purposed = 0;
      for (const id in S) { const r = S[id].attributes.milesight_role; if (r && OB_PURPOSE_ROLES.indexOf(r) >= 0) purposed++; }
      const toInt = this._cfg.setup_path || "/config/integrations/integration/milesight_lorawan";
      const go = (p) => () => navigate(p);
      return [
        { key: "gateway", title: "Gateway online",
          state: gwOn > 0 ? "good" : (gws.length ? "warn" : "pending"),
          hint: gwOn > 0 ? `${gwOn} gateway${gwOn > 1 ? "s" : ""} connected and listening.`
            : (gws.length ? "A gateway is set up but offline — check its power and network uplink."
              : "Add your Milesight gateway in Settings → Devices & services."),
          action: gwOn > 0 ? null : { label: gws.length ? "Check gateway" : "Add gateway", onClick: go(toInt) } },
        { key: "devices", title: "Devices added",
          state: devs.length ? "good" : "pending",
          hint: devs.length ? `${devs.length} device${devs.length > 1 ? "s" : ""} on the gateway.`
            : "Pair your sensors to the gateway, then add them from Settings → Devices & services → Discovered.",
          action: devs.length ? null : { label: "Add devices", onClick: go(toInt) } },
        { key: "data", title: "Data arriving",
          state: on > 0 ? "good" : (devs.length ? "bad" : "pending"),
          hint: on > 0 ? `${on} of ${devs.length} device${devs.length > 1 ? "s" : ""} reporting.`
            : (devs.length ? "Devices are added but none are reporting — check the gateway link and the sensors' batteries. Until this clears, readings on your dashboards are stale."
              : "Appears once your first device sends an uplink."),
          action: (devs.length && on === 0) ? { label: "Open Maintenance", onClick: go("/milesight-maintenance/overview") } : null },
        { key: "purposes", title: "Purposes assigned",
          state: purposed > 0 ? "good" : "pending",
          hint: purposed > 0 ? `${purposed} sensor${purposed > 1 ? "s" : ""} tagged — your dashboards are tailored to the site.`
            : "Open a device → Configure → Purpose (tank, pump, fridge, pivot …) to unlock the matching dashboards and safety alerts.",
          action: purposed > 0 ? null : { label: "Assign purposes", onClick: go(toInt) } },
      ];
    }
    _render() {
      if (!this._hass) return;
      const steps = this._steps();
      const done = steps.filter((s) => s.state === "good").length;
      const allDone = done === steps.length;
      const hasBad = steps.some((s) => s.state === "bad");
      if (allDone || (this._dismissed() && !hasBad)) { this.style.display = "none"; this.shadowRoot.replaceChildren(); return; }
      this.style.display = "";
      this._css = `
        .ob{padding:16px 18px}
        .obh{display:flex;align-items:center;gap:12px;margin-bottom:13px}
        .obic{flex:0 0 auto;width:40px;height:40px;border-radius:11px;display:flex;align-items:center;justify-content:center;
          background:color-mix(in srgb, var(--ms-accent) 15%, transparent);color:var(--ms-accent)}
        .obic ha-icon{--mdc-icon-size:23px}
        .obt{font-size:17px;font-weight:700;color:var(--ms-ink);line-height:1.15}
        .obsub{font-size:12.5px;color:var(--ms-ink2);margin-top:1px}
        .obbar{height:6px;border-radius:4px;background:color-mix(in srgb, var(--ms-ink) 10%, transparent);overflow:hidden;margin-bottom:6px}
        .obbar > i{display:block;height:100%;border-radius:4px;background:var(--ms-good);transition:width .4s ease}
        .step{display:flex;gap:12px;align-items:flex-start;padding:11px 2px}
        .step + .step{border-top:1px solid var(--ms-line)}
        .stico{flex:0 0 auto;width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin-top:1px}
        .stico ha-icon{--mdc-icon-size:18px}
        .step.good .stico{color:var(--ms-good);background:color-mix(in srgb, var(--ms-good) 14%, transparent)}
        .step.warn .stico{color:var(--ms-warn);background:color-mix(in srgb, var(--ms-warn) 15%, transparent)}
        .step.bad .stico{color:var(--ms-bad);background:color-mix(in srgb, var(--ms-bad) 14%, transparent)}
        .step.pending .stico{color:var(--ms-ink2);background:color-mix(in srgb, var(--ms-ink) 8%, transparent)}
        .stbody{flex:1 1 auto;min-width:0}
        .stt{font-size:14px;font-weight:600;color:var(--ms-ink)}
        .step.pending .stt{color:var(--ms-ink2)}
        .sth{font-size:12.5px;color:var(--ms-ink2);line-height:1.4;margin-top:2px}
        .sta{margin-top:7px;font:inherit;font-size:12.5px;color:var(--ms-accent);background:none;
          border:1px solid var(--ms-line);border-radius:8px;padding:6px 12px;cursor:pointer}
        .sta:hover{border-color:var(--ms-accent)}
        .obf{display:flex;justify-content:flex-end;margin-top:8px}
        .obdismiss{font:inherit;font-size:12px;color:var(--ms-ink2);background:none;border:none;cursor:pointer}
        .obdismiss:hover{color:var(--ms-ink);text-decoration:underline}
      `;
      const icons = { good: "mdi:check", warn: "mdi:alert", bad: "mdi:alert-octagon", pending: "mdi:circle-small" };
      const stepEl = (s) => h("div", { class: "step " + s.state }, [
        h("div", { class: "stico" }, [h("ha-icon", { icon: icons[s.state] || "mdi:circle-small" })]),
        h("div", { class: "stbody" }, [
          h("div", { class: "stt" }, esc(s.title)),
          h("div", { class: "sth" }, esc(s.hint)),
          s.action ? h("button", { class: "sta", onclick: s.action.onClick }, s.action.label) : null,
        ]),
      ]);
      this._card(h("div", { class: "ob" }, [
        h("div", { class: "obh" }, [
          h("div", { class: "obic" }, [h("ha-icon", { icon: "mdi:rocket-launch-outline" })]),
          h("div", {}, [
            h("div", { class: "obt" }, this._cfg.title || "Set up your Milesight system"),
            h("div", { class: "obsub" }, `${done} of ${steps.length} done`),
          ]),
        ]),
        h("div", { class: "obbar" }, [h("i", { style: { width: Math.round(done / steps.length * 100) + "%" } })]),
        h("div", { class: "steps" }, steps.map(stepEl)),
        h("div", { class: "obf" }, [
          h("button", { class: "obdismiss", onclick: () => this._dismiss() }, "Hide this checklist"),
        ]),
      ]));
    }
  }

  // ---------------------------------------------------------------- visual config editors (ha-form)
  const ENTITY_SEL = { entity: { domain: ["sensor", "binary_sensor"] } };
  class CardEditor extends HTMLElement {
    constructor() { super(); this.attachShadow({ mode: "open" }); }
    setConfig(cfg) { this._cfg = cfg || {}; this._render(); }
    set hass(hass) { this._hass = hass; this._render(); }
    _render() {
      if (!this._hass) return;
      const form = this._form || document.createElement("ha-form");
      form.hass = this._hass;
      form.data = this._cfg;
      form.schema = this._schema;
      form.computeLabel = (s) => ({
        entity: "Entity", name: "Name (optional)", battery: "Battery entity (optional)",
        signal: "Signal entity (optional)", hours: "History window (hours)", sparkline: "Show sparkline",
        color: "Line colour (optional)", shape: "Vessel shape", purpose: "Purpose (optional)",
        liquid: "Contents (optional)", low: "Low-level alarm (%)", shape: "Gauge style",
      }[s.name] || s.name);
      if (!this._form) {
        this._form = form;
        form.addEventListener("value-changed", (e) => {
          this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: e.detail.value }, bubbles: true, composed: true }));
        });
        this.shadowRoot.replaceChildren(form);
      }
    }
  }
  const sel = { entity: { name: "entity", selector: ENTITY_SEL },
                name: { name: "name", selector: { text: {} } },
                hours: { name: "hours", selector: { number: { min: 1, max: 336, mode: "box", unit_of_measurement: "h" } } } };
  const EDITORS = {
    "milesight-gateway-card": [sel.entity, sel.name],
    "milesight-device-card": [sel.entity, sel.name,
      { name: "battery", selector: ENTITY_SEL }, { name: "signal", selector: ENTITY_SEL },
      sel.hours, { name: "sparkline", selector: { boolean: {} } }],
    "milesight-trend-card": [sel.entity, sel.name, sel.hours, { name: "color", selector: { text: {} } }],
    "milesight-level-card": [sel.entity, sel.name,
      { name: "shape", selector: { select: { mode: "dropdown", options: [
        { value: "tank", label: "Tank (cylinder)" }, { value: "silo", label: "Silo" },
        { value: "dam", label: "Dam / water body" }, { value: "bin", label: "Waste bin" }] } } },
      { name: "liquid", selector: { select: { mode: "dropdown", options: [
        { value: "water", label: "Water" }, { value: "fuel", label: "Fuel" },
        { value: "grain", label: "Grain / feed" }, { value: "waste", label: "Waste" }] } } },
      { name: "low", selector: { number: { min: 0, max: 100, mode: "box", unit_of_measurement: "%" } } }],
    "milesight-table-card": [
      { name: "preset", selector: { select: { mode: "dropdown", options: [
        { value: "devices", label: "Devices" }, { value: "offline", label: "Offline" },
        { value: "weak", label: "Weak / lossy" }, { value: "firmware", label: "Firmware" },
        { value: "cold_chain", label: "Fridges & freezers" }, { value: "compressors", label: "Compressors" },
        { value: "loads", label: "Loads" }, { value: "pumps", label: "Pumps" },
        { value: "pivots", label: "Centre pivots" }, { value: "batteries", label: "Batteries" },
        { value: "service", label: "Service history" }, { value: "gateways", label: "Gateways" },
        { value: "tanks", label: "Tanks & silos" }, { value: "comfort", label: "Comfort per area" },
        { value: "utilisation", label: "Utilisation" }] } } },
      { name: "entity", selector: ENTITY_SEL }, { name: "title", selector: { text: {} } },
      { name: "only_issues", selector: { boolean: {} } }, { name: "search", selector: { boolean: {} } }],
    "milesight-gauge-card": [sel.entity, sel.name,
      { name: "shape", selector: { select: { mode: "dropdown", options: [
        { value: "arc", label: "Arc" }, { value: "semicircle", label: "Half" },
        { value: "ring", label: "Ring" }, { value: "bar", label: "Bar" }] } } },
      { name: "min", selector: { number: { mode: "box" } } }, { name: "max", selector: { number: { mode: "box" } } },
      { name: "unit", selector: { text: {} } }, { name: "switchable", selector: { boolean: {} } }],
    "milesight-device-panel": [{ name: "device", selector: { device: {} } }, sel.entity, sel.name, sel.hours],
    "milesight-page-header": [{ name: "title", selector: { text: {} } }, { name: "subtitle", selector: { text: {} } },
      { name: "icon", selector: { icon: {} } }, { name: "site", selector: { text: {} } },
      { name: "stats", selector: { boolean: {} } }, { name: "nav", selector: { boolean: {} } }],
    "milesight-onboarding": [{ name: "title", selector: { text: {} } }],
  };

  // ---------------------------------------------------------------- register
  const GW_TAG = "milesight-gateway-card", DEV_TAG = "milesight-device-card",
        MINI_TAG = "milesight-trend-card", LVL_TAG = "milesight-level-card", TBL_TAG = "milesight-table-card",
        GAUGE_TAG = "milesight-gauge-card", PANEL_TAG = "milesight-device-panel", HEADER_TAG = "milesight-page-header",
        ONBOARD_TAG = "milesight-onboarding";
  const defs = [
    [GW_TAG, GatewayCard, "Milesight Gateway", "Gateway health: online, packets, connection, location, clock"],
    [DEV_TAG, DeviceCard, "Milesight Device", "Device status: battery ring, signal bars, last-seen, headline reading + sparkline"],
    [MINI_TAG, TrendCard, "Milesight Trend", "Self-contained mini trend chart for any sensor"],
    [LVL_TAG, LevelCard, "Milesight Level", "Animated tank / silo / dam / bin fill, by purpose"],
    [TBL_TAG, TableCard, "Milesight Table", "Device/status table that faintly highlights rows and cells with issues"],
    [GAUGE_TAG, GaugeCard, "Milesight Gauge", "Animated gauge for any value — arc, half, ring or bar, switchable live"],
    [PANEL_TAG, DevicePanel, "Milesight Device Page", "A per-device page laid out by device type (tank/climate/air/pump)"],
    [HEADER_TAG, PageHeader, "Milesight Page Header", "A page masthead: site, title, subtitle and a live health strip"],
    [ONBOARD_TAG, OnboardingCard, "Milesight Onboarding", "First-run setup checklist that ticks itself off and hides once set up"],
  ];
  window.customCards = window.customCards || [];
  for (const [tag, cls, name, desc] of defs) {
    const editorTag = tag + "-editor";
    if (!customElements.get(editorTag)) {
      customElements.define(editorTag, class extends CardEditor { constructor() { super(); this._schema = EDITORS[tag]; } });
    }
    cls.getConfigElement = () => document.createElement(editorTag);
    if (!customElements.get(tag)) customElements.define(tag, cls);
    window.customCards.push({ type: tag, name, description: desc, preview: true, documentationURL: "https://github.com/Juanko984/milesight-lorawan-ha" });
  }
  // eslint-disable-next-line no-console
  console.info("%cMilesight LoRaWAN cards loaded", "color:#1e88e5;font-weight:600");
})();
