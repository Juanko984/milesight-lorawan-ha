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
  `;

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
      const card = h("ha-card");
      const style = h("style"); style.textContent = BASE_CSS + (this._css || "");
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
        if (!items.length) return this._card(h("div", { class: "wrap muted" }, cfg.empty || "No tanks or silos yet."));
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
      issue: () => "offline", empty: "All devices online ✅",
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
      empty: "All devices have a good link ✅",
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
      issue: (r) => r.mixed ? "mixed versions" : null, empty: "No devices yet.",
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
      const role = this._cfg.role || this._pre().role;
      const ids = [];
      for (const id in this._hass.states) if (id.startsWith("sensor.") && this._hass.states[id].attributes.milesight_role === role) ids.push(id);
      return ids;
    }
    _rows() {
      const p = this._pre(), path = this._cfg.path || p.path || "devices";
      let src = null;
      if (this._cfg.entity) src = this._st(this._cfg.entity);
      else { const ids = this._watch(); src = ids.length ? this._st(ids[0]) : null; }
      let rows = Array.isArray(this._cfg.rows) ? this._cfg.rows
        : ((src && Array.isArray(src.attributes[path])) ? src.attributes[path] : []);
      if (p.transform) rows = p.transform(rows);
      if (p.filter) rows = rows.filter(p.filter);
      return rows;
    }
    _openRow(r) {
      if (r.device_id) {
        const reg = this._hass.entities || {};
        const ent = Object.keys(reg).find((e) => reg[e].device_id === r.device_id);
        if (ent) return fireMoreInfo(this, ent);
        history.pushState(null, "", "/config/devices/device/" + r.device_id);
        window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
      } else if (r.entity_id) fireMoreInfo(this, r.entity_id);
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
      const table = rows.length
        ? h("div", { class: "cw" }, [h("table", {}, [h("thead", {}, head), h("tbody", {}, body)])])
        : h("div", { class: "empty" }, q ? "Nothing matches your filter." : (cfg.empty || "No devices yet."));
      this._card(h("div", { class: "wrap" }, [
        title === false ? null : h("p", { class: "title", style: { marginBottom: "8px" } }, title || "Devices"),
        toolbar, table,
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
      let t = this._cfg.type || "arc";
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
        .gfill{fill:none;stroke-linecap:round;transition:stroke-dashoffset .9s cubic-bezier(.25,.1,.25,1),stroke .4s}
        .gneedle{transition:transform .9s cubic-bezier(.25,.1,.25,1)}
        .gbarfill{transition:width .9s cubic-bezier(.25,.1,.25,1),fill .4s}
      `;
      const click = () => fireMoreInfo(this, cfg.entity);
      let svg;
      if (spec.bar) {
        svg = svgNS(`<svg class="gsvg" width="100%" height="76" viewBox="0 0 200 76" onclick="void 0">
          <text class="gval" x="100" y="26" text-anchor="middle" font-size="26" data-val>–</text>
          <rect class="gtrack" x="12" y="40" width="176" height="12" rx="6" stroke-width="0" fill="var(--ms-line)"/>
          <rect class="gbarfill" x="12" y="40" width="0" height="12" rx="6" data-fill/>
          <text class="gsub" x="12" y="68" font-size="10" data-min>0</text>
          <text class="gsub" x="188" y="68" text-anchor="end" font-size="10" data-max>100</text>
        </svg>`);
      } else {
        const ring = t === "ring", half = t === "semicircle";
        const cx = 100, cy = half ? 96 : 100, r = 74;
        const track = garc(cx, cy, r, spec.start, spec.sweep);
        const valY = ring ? cy + 2 : half ? cy + 30 : cy + 42;    // clear of the needle/pivot
        const vbH = half ? 140 : ring ? 200 : 182;
        svg = svgNS(`<svg class="gsvg" width="${ring ? 172 : 200}" height="${half ? 118 : ring ? 172 : 158}"
            viewBox="0 0 200 ${vbH}">
          <path class="gtrack" d="${track}" stroke-width="${ring ? 11 : 12}"/>
          <path class="gfill" d="${track}" stroke-width="${ring ? 11 : 12}" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100" data-fill/>
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
        min: svg.querySelector("[data-min]"), max: svg.querySelector("[data-max]"), spec,
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
        if (g.min) g.min.textContent = mn; if (g.max) g.max.textContent = mx;
        if (g.val && unit) g.val.textContent = vt + " " + unit;
      } else {
        if (g.fill) { g.fill.setAttribute("stroke", col); g.fill.style.strokeDashoffset = String(100 - pct); }
        if (g.needle) g.needle.style.transform = `rotate(${(spec.start + spec.sweep * pct / 100).toFixed(1)}deg)`;
      }
      this._lastSig = (this._st(this._cfg.entity) || {}).state + "@" + (this._st(this._cfg.entity) || {}).last_changed;
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
        liquid: "Contents (optional)", low: "Low-level alarm (%)",
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
        { value: "weak", label: "Weak / lossy" }, { value: "firmware", label: "Firmware" }] } } },
      { name: "entity", selector: ENTITY_SEL }, { name: "title", selector: { text: {} } },
      { name: "only_issues", selector: { boolean: {} } }, { name: "search", selector: { boolean: {} } }],
    "milesight-gauge-card": [sel.entity, sel.name,
      { name: "type", selector: { select: { mode: "dropdown", options: [
        { value: "arc", label: "Arc" }, { value: "semicircle", label: "Half" },
        { value: "ring", label: "Ring" }, { value: "bar", label: "Bar" }] } } },
      { name: "min", selector: { number: { mode: "box" } } }, { name: "max", selector: { number: { mode: "box" } } },
      { name: "unit", selector: { text: {} } }, { name: "switchable", selector: { boolean: {} } }],
  };

  // ---------------------------------------------------------------- register
  const GW_TAG = "milesight-gateway-card", DEV_TAG = "milesight-device-card",
        MINI_TAG = "milesight-trend-card", LVL_TAG = "milesight-level-card", TBL_TAG = "milesight-table-card",
        GAUGE_TAG = "milesight-gauge-card";
  const defs = [
    [GW_TAG, GatewayCard, "Milesight Gateway", "Gateway health: online, packets, connection, location, clock"],
    [DEV_TAG, DeviceCard, "Milesight Device", "Device status: battery ring, signal bars, last-seen, headline reading + sparkline"],
    [MINI_TAG, TrendCard, "Milesight Trend", "Self-contained mini trend chart for any sensor"],
    [LVL_TAG, LevelCard, "Milesight Level", "Animated tank / silo / dam / bin fill, by purpose"],
    [TBL_TAG, TableCard, "Milesight Table", "Device/status table that faintly highlights rows and cells with issues"],
    [GAUGE_TAG, GaugeCard, "Milesight Gauge", "Animated gauge for any value — arc, half, ring or bar, switchable live"],
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
