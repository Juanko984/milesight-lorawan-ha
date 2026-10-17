"""Installer handover report: every device with its area, purpose, connection, signal, battery and last contact,
as CSV (spreadsheets) and as a self-contained printable page. Pure Python (unit-tested)."""
from __future__ import annotations

import csv
import html
import io
from typing import Any

COLUMNS = [("name", "Device"), ("model", "Model"), ("deveui", "DevEUI"), ("area", "Area"), ("purpose", "Purpose"),
           ("network_server", "Network server"), ("online", "Online"), ("signal", "Signal"), ("rssi", "RSSI dBm"),
           ("snr", "SNR dB"), ("sf", "SF"), ("gateway", "Best gateway"), ("gateways_heard", "Gateways"),
           ("packet_loss", "Loss today %"), ("battery", "Battery %"), ("battery_replace_by", "Battery due"),
           ("firmware", "Firmware"), ("last_seen", "Last seen"), ("walk_test", "Walk test"), ("location", "Location")]
_ICON = {"excellent": "🟢", "good": "🟢", "fair": "🟠", "poor": "🔴"}


def _walk(w: dict[str, Any] | None) -> str:
    if not w:
        return ""
    spot = f" at {w['spot']}" if w.get("spot") else ""
    return f"{w.get('verdict') or '–'}{spot} ({w.get('count', 0)} readings)"


def _cell(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    if key == "walk_test":
        return _walk(v)
    if key == "location":
        return f"{d['latitude']:.6f}, {d['longitude']:.6f}" if d.get("latitude") is not None else ""
    if key == "online":
        return "yes" if v else "no"
    if key == "last_seen" and v:
        return str(v)[:16].replace("T", " ")
    return "" if v is None else str(v)


def report_csv(devices: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _k, label in COLUMNS])
    for d in sorted(devices, key=lambda x: ((x.get("area") or "~").lower(), x["name"].lower())):
        w.writerow([_cell(d, k) for k, _l in COLUMNS])
    return buf.getvalue()


def checks(devices: list[dict[str, Any]]) -> list[str]:
    """What the installer still has to look at before handing over."""
    out = []
    off = [d["name"] for d in devices if not d.get("online")]
    weak = [d["name"] for d in devices if d.get("signal") == "poor"]
    noarea = [d["name"] for d in devices if not d.get("area")]
    noloc = [d["name"] for d in devices if d.get("latitude") is None]
    low = [d["name"] for d in devices if d.get("battery_low")]
    single = [d["name"] for d in devices if d.get("gateways_heard") == 1 and d.get("signal") in ("poor", "fair")]
    if off:
        out.append(f"Offline: {', '.join(off)}")
    if weak:
        out.append(f"Weak signal: {', '.join(weak)}")
    if single:
        out.append(f"Only one gateway with little margin: {', '.join(single)}")
    if low:
        out.append(f"Battery low: {', '.join(low)}")
    if noarea:
        out.append(f"No area set: {', '.join(noarea)}")
    if noloc:
        out.append(f"No location captured: {', '.join(noloc)}")
    return out


def report_html(site: dict[str, Any], devices: list[dict[str, Any]], gateways: list[dict[str, Any]], when: str) -> str:
    e = html.escape
    devs = sorted(devices, key=lambda x: ((x.get("area") or "~").lower(), x["name"].lower()))
    online = sum(1 for d in devs if d.get("online"))
    todo = checks(devs)
    rows = []
    for d in devs:
        sig = d.get("signal")
        rows.append("<tr>" + "".join([
            f"<td><b>{e(d['name'])}</b><br><small>{e(d.get('model') or '')} · {e(d.get('deveui') or '')}</small></td>",
            f"<td>{e(d.get('area') or '–')}<br><small>{e(d.get('purpose') or '')}</small></td>",
            f"<td>{_ICON.get(sig, '⚪')} {e(sig or '–')}<br><small>{'' if d.get('rssi') is None else e(str(d['rssi'])) + ' dBm'}"
            f"{'' if d.get('snr') is None else ' · ' + e(str(d['snr'])) + ' dB'}{'' if not d.get('sf') else ' · SF' + e(str(d['sf']))}"
            f"{'' if not d.get('gateways_heard') else ' · ' + e(str(d['gateways_heard'])) + ' gw'}</small></td>",
            f"<td>{'–' if d.get('battery') is None else e(str(d['battery'])) + ' %'}"
            f"<br><small>{'due ' + e(d['battery_replace_by']) if d.get('battery_replace_by') else ''}</small></td>",
            f"<td>{'🟢' if d.get('online') else '🔴'} {e(_cell(d, 'last_seen'))}<br><small>{e(d.get('network_server') or '')}"
            f"{' · fw ' + e(d['firmware']) if d.get('firmware') else ''}</small></td>",
            f"<td><small>{e(_walk(d.get('walk_test')))}</small>"
            + (f"<br><small><a href=\"https://maps.google.com/?q={d['latitude']},{d['longitude']}\">📍 map</a></small>"
               if d.get("latitude") is not None else "") + "</td>"]) + "</tr>")
    gw_rows = "".join(f"<li>{e(g.get('name') or g['id'])} <small>({e(g['id'])}, {g.get('packets_today') or 0} packets today)"
                      f"</small></li>" for g in gateways) or "<li>–</li>"
    todo_html = ("<ul>" + "".join(f"<li>{e(t)}</li>" for t in todo) + "</ul>") if todo else "<p>✅ Nothing open.</p>"
    contact = " · ".join(e(str(x)) for x in (site.get("contact"), site.get("phone"), site.get("email")) if x)
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Handover – {e(site.get('site') or '')}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1b1b1b;background:#fff}}
h1{{margin:0 0 4px;font-size:22px}} .muted{{color:#666}} table{{border-collapse:collapse;width:100%;margin-top:12px;font-size:13px}}
th,td{{text-align:left;vertical-align:top;padding:6px 8px;border-bottom:1px solid #ddd}} th{{background:#f3f3f3}}
small{{color:#555}} .cards{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}} .card{{border:1px solid #ddd;border-radius:8px;padding:8px 12px}}
.sign{{display:flex;gap:48px;margin-top:40px}} .sign div{{border-top:1px solid #999;padding-top:4px;min-width:220px}}
@media print{{body{{margin:10mm}} .noprint{{display:none}}}}
</style></head><body>
<h1>LoRaWAN installation handover</h1>
<div class="muted">{e(site.get('company') or '')} · {e(site.get('site') or '')}{(' · ' + e(site['address'])) if site.get('address') else ''}<br>
{('Contact: ' + contact + '<br>') if contact else ''}Report created {e(when)}</div>
<div class="cards"><div class="card"><b>{len(devs)}</b> devices</div><div class="card"><b>{online}</b> online</div>
<div class="card"><b>{len(gateways)}</b> gateway(s)</div><div class="card"><b>{len(todo)}</b> open points</div></div>
<button class="noprint" onclick="window.print()">Print / save as PDF</button>
<h2>Open points</h2>{todo_html}
<h2>Gateways</h2><ul>{gw_rows}</ul>
<h2>Devices</h2>
<table><thead><tr><th>Device</th><th>Area / purpose</th><th>Signal</th><th>Battery</th><th>Last seen</th><th>Walk test / location</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<div class="sign"><div>Installer – name, signature, date</div><div>Customer – name, signature, date</div></div>
</body></html>"""
