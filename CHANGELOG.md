# Changelog

All notable changes to this integration. Versions follow the GitHub releases / HACS updates.

## 0.86.0
- **Water tanks and grain/feed silos are now separated.** The tank setup gained a **"What it holds"** choice —
  Water, Fuel/diesel, Grain or feed (silo), or Other liquid. Water, fuel and other liquids stay on the **Water**
  dashboard; **grain/feed silos move to a new "Silos" section on the Farm dashboard** (with their own band,
  table and level trends, and contents shown in tonnes). So silos no longer clutter the Water page.
  - Existing tanks default to "Water", so nothing moves until you set a tank to "Grain or feed".
- **Renaming a device now updates the main name everywhere.** Previously the discovered name was baked into the
  config-entry title, and renaming the device in Home Assistant only changed the device-registry name — the group
  header, cards and dashboards kept the old name. Now, when you rename a Milesight device, the integration syncs
  that name to the entry title, so the new name shows across the group header, the cards and every dashboard.

## 0.85.0
- **Much simpler "Tank or silo" setup.** The old form showed every field at once (Length, Width, Cone height,
  density, theft settings…) no matter the shape — confusing, since an upright cylinder only needs a diameter and a
  height. It's now a short two-step flow:
  1. **Pick the shape.**
  2. **Enter only that shape's measurements** — e.g. an upright cylinder asks for diameter + height only; a silo
     adds the cone height; "any other shape" just asks for capacity. Each step shows plain guidance for what to
     measure, and the live capacity so you can sanity-check it.
  - The **optional alerts** (low level, refill detection, theft/sudden-drop, density-for-weight) come after the
    measurements, clearly marked optional with sensible defaults — no need to touch them for a basic tank.
  - Measurements that don't apply to the chosen shape are cleared automatically, so switching shape can't leave
    stale values skewing the capacity.

## 0.84.0
- **"Purpose (what it is fitted to)" now shows on every device.** The step used to appear only when the model had
  a matching purpose, so sensors like the EM500-PP (pipe pressure) or EM500-LGT (light) showed no Purpose option
  at all. It's now offered on every device; when a model matches no specific purpose, the selector falls back to
  the full catalogue so you can still categorise it.
  - Note: the EM500 / level range (EM500-UDL, EM500-SWL, EM310-UDL, EM410-RDL, EM400-UDL) already map to the tank
    & level purposes (water tank, fuel tank, silo, flood…). If a level device wasn't showing Purpose before, it
    will now.
  - A purpose only *takes effect* when it suits the device's sensor type (a temperature purpose needs a
    temperature sensor); the dashboards and alerts it drives stay correct, so an unmatched pick simply does
    nothing rather than creating broken cards.

## 0.83.0
- **Site name in the sidebar header (top-left), at last.** Home Assistant has no built-in setting for that
  "Home Assistant" title — it's hard-coded in the frontend, and the earlier "use the company name as HA's name"
  option only changed the instance name (browser tab), not the sidebar. Because this integration already loads
  its card bundle across the whole frontend, it now sets the sidebar title itself:
  - **On by default**, showing your **Site company name** (Gateway → Configure → Site), falling back to the Home
    Assistant instance name if no company is set.
  - **Set a custom title** or **turn it off** under Gateway → Configure → Site ("Show the site name in the
    sidebar header" + an optional custom title).
  - Applied for every user and re-applied after navigation/theme changes; it degrades silently if a future HA
    frontend changes the sidebar's structure (your dashboards are unaffected).

## 0.82.0
- **Richer device pages (all device types).** Opening a device now shows:
  - **Key metrics as a row of gauges** — the 4–5 most important readings for that device type, each colour-zoned
    (e.g. an air sensor: CO₂, temperature, humidity, PM2.5, pressure; a fridge: temperature band; a pump: current,
    power, duty). The gauges carry the alert colour, so a value out of range is obvious at a glance. (A tank keeps
    its animated level visual.)
  - **A multi-property trend** (`custom:milesight-multitrend-card`) — those same key readings on one chart, each
    auto-scaled so the shapes are comparable, with a live legend showing each one's current value, and a
    Today / 24 h / 7 d toggle.
  - **A "Readings log" table** (`custom:milesight-readings-table-card`) — the raw Activity timestamp list is
    replaced with a time-aligned table of the actual values (Time + one column per key property, ~12 rows, most
    recent first). Values past a limit are highlighted.
  - The remaining readings stay in a compact **"Other readings"** grid; controls and the walk-test action are
    unchanged. These two new cards can also be dropped onto any dashboard on their own.

## 0.81.0
- **Trendlines wired into the dashboards + device pages.**
  - **New self-discovering grid (`custom:milesight-trendline-grid-card`)** — drops a small grid of trendlines, one
    per matching sensor, found automatically (no entity ids to type). It's placed on:
    - **Cold chain → "Temperature trends"** — one per fridge/freezer.
    - **Water → "Level trends"** — one per tank.
    - **Building analytics → "CO₂ trends"** — one per CO₂ sensor.
  - **Device pages** now show the full trendline (threshold flash + day min/max) for the primary reading when that
    sensor has a purpose limit (fridge temp, tank %, CO₂); other sensors keep the compact sparkline.
  - Sensors that carry a purpose limit are tagged (`ms_trend` = `cold_chain` / `temperature` / `tank` / `air`) so
    the grid can find them; the grid also accepts a custom `match`, an `area` filter, `columns` and a `window`.

## 0.80.0
- **New trendline card (`custom:milesight-trendline-card`) with threshold flashing.** A compact daily trendline
  for any sensor:
  - **Flashes when the value crosses a threshold** — a red glow + pulsing value for a high limit, amber for a low
    one. The breached part of the line turns the alert colour with a pulsing marker at the live point, and an
    `OVER` / `UNDER` pill appears next to the reading.
  - **Day min and max with the time each happened**, marked on the line (blue = min, orange = max).
  - **Thresholds are reused from the device's purpose limits** — the cold-chain temperature alarm band, the tank
    low-level %, and the CO₂ limit are exposed on their entities (`ms_limit_high` / `ms_limit_low`) so the card
    flashes on the same limits your alerts use. Both a high and a low limit together draw a band (flash when
    outside either edge). You can also set `max` / `min` directly on the card.
  - **Window toggle** — Today (midnight→now) by default, with Last 24 h and Last 7 d; min/max follow the window.
  - The existing mini `milesight-trend-card` sparkline is unchanged.

## 0.79.0
- **New dedicated "Devices" page.** The full device list used to be a tab buried under Maintenance (and before
  that, a standalone page that was merged away); it's now back as its own always-visible sidebar page, installed
  on every site.
  - **Header + fleet-health band** at the top (online, batteries due, offline, weak signal, firmware).
  - **Every device in one sortable table** — Device, Model, Area, **Battery %**, **Last update**, RSSI, SNR, SF,
    packet loss and firmware. "Last update" shows a relative time for the last day (e.g. "4m ago") and the date
    beyond that.
  - **Filters at the top:** quick-filter chips (All / Online / Offline / Low battery / Weak signal), an **area
    dropdown**, and the free-text filter box. Click any column header to sort (your choice is remembered).
  - **Row highlighting** — a row tints amber for a low battery and red when a device is offline, with an icon in
    the first cell; individual cells past their threshold (weak RSSI/SNR, high SF, packet loss) are emphasised.
  - **Click a row to open that device's page** (signal history, battery forecast, service log and its sensors).
  - The table card gained reusable **filter chips** (`filters:`) and an **area dropdown** (`area_filter:`) that
    any dashboard can use.

## 0.78.1
- **Ecowitt WS90 wind now reads in km/h, with a readable compass direction.**
  - **Wind speed and gust default to km/h.** The station's register is 0.1 m/s; the template now scales it ×3.6
    (scale `0.36`, unit `km/h`) so the entities read in km/h out of the box. For example 0.5 m/s now shows as
    **1.8 km/h**. (Prefer m/s? Edit those two channel-map lines back to scale `0.1`, unit `m/s`.)
  - **Wind direction gets a companion "Wind direction (compass)" sensor** showing the 16-point compass point
    (N, NNE, NE, … — e.g. 258° → **WSW**). The numeric degrees sensor stays, so wind-rose history and graphs are
    unaffected.
  - New channel-map option **`compass`**: mark any bearing-in-degrees channel with it to get the readable
    compass text sensor alongside the degrees.

  **To apply to an already-configured WS90:** re-apply the Ecowitt WS90 template (integration → Configure →
  Modbus templates), or edit the stored channel-map lines — set the wind-speed/gust lines to `… ; km/h ; 0.36`
  and append ` ; compass` to the wind-direction line.

## 0.78.0
- **Overview landing page decluttered.** The masthead was repeating what the page already showed below it, and
  carried stale labels now that the dashboards have been reorganised:
  - **Removed the duplicate stat chips and nav tabs from the Overview masthead.** Those online/gateway/alert chips
    duplicated the Status band directly beneath them, and the sidebar nav tabs duplicated the Dashboards grid at
    the foot of the page. The masthead is now just the title and subtitle; the Status band and Dashboards grid are
    the single source for each. (Operational dashboards keep their masthead chips and nav — only the landing page
    drops them.)
  - **"Tanks & water" → "Water"** on the Operations domain card and its editor dropdown, matching the renamed
    Water dashboard.
  - **Open-alerts count now matches the Status band.** The masthead and the band disagreed (e.g. "19" vs "6")
    because the masthead counted every open alert including acknowledged ones. Both now count unacknowledged
    alerts, so the number is consistent everywhere.
  - **Refreshed the sibling-dashboard nav order** (`alerts, maintenance, water, analytics, farm, cold-chain,
    energy, retail, washroom, coop`) — the old order still referenced the retired `tanks` slug and omitted the
    newer Alerts, Retail and Washroom pages.

## 0.77.0
- **New dedicated Alerts dashboard — one home for every alert.** The open-alerts card was repeated on Water, Coop,
  Washroom and the landing page, all showing the same site-wide list. It's now consolidated onto a single
  **always-visible Alerts page**:
  - **Status band** (`milesight-alerts-band`): open now, escalated, acknowledged, average ack time, who's on call.
  - **Open alerts** — the interactive acknowledge / snooze card.
  - **Last 7 days** — the alert summary (count, MTTA, by category, noisiest sources).
  - **Escalation & notifications** (`milesight-escalation-card`): who's on call, the escalation chain, escalate-after
    time, quiet hours, snooze window and the notify channels — read from the gateway — with a **Configure
    notifications** button that opens the integration's settings.
  - The duplicated alerts card was removed from the other dashboards; their status bands' "Open alerts" tile now
    links to the Alerts page. The Alerts page installs on every site.

## 0.76.0
- **"Water Level" renamed to "Water" under a fresh sidebar slug (`milesight-water`).** If you'd hand-edited or
  half-deleted the old "Tanks & alerts" dashboard, it could come back blank and refuse to delete because the old
  `milesight-tanks` slug was stuck in the integration's stored state. On update the old slug is now removed and a
  **brand-new "Water" dashboard** is created with the full Water command center (band, alerts, tanks table,
  supply & refills, troughs, flood), so there's nothing stale to fight. Alert deep-links and card navigation now
  point at the new slug.

## 0.75.0
- **Distribution & quality pass.**
  - **Persistence robustness sweep.** Audited every tracker's save scheduling. Fixed a second instance of the
    "delay resets before it fires" bug (after the area / retail fix in 0.69): the gateway-stats save was scheduled
    with a 60 s delay from the 60 s tick, so on a quiet gateway it never flushed and packet counts / last-heard
    only persisted on a clean shutdown (lost on a crash). Now saved within each tick. A regression test guards the
    pattern across the area, retail and hub trackers.
  - **System Health panel.** Settings → System → System information now shows a Milesight section: gateways online,
    devices set up, and whether the built-in LoRaWAN server is running.
  - **Code owner** added to the manifest (required for HACS / hassfest and the HA Quality Scale).

## 0.74.0
- **New Smart Washroom / Facilities dashboard.** A whole new use case built from the device catalogue — Milesight's
  smart-restroom stack. Auto-installs when a washroom sensor (GS301 odour, WS201 supplies, VS330 occupancy,
  GS601 vape) or a **Toilet / washroom** purpose is present.
  - A new gateway `washroom` sensor groups every washroom device **by Home Assistant area into one card per
    restroom**, rolling up cleanliness (odour from NH₃/H₂S), consumables (soap / paper / towels %), traffic
    (visits since clean, with a cleaning-progress bar), air (CO₂), noise (dB) and events (vaping, leak, smoke).
  - **Band** (`milesight-washroom-band`): need cleaning, low supplies, odour / air, alerts, occupied now.
  - **Per-room cards** (`milesight-washroom-card`): cleanliness, occupancy, CO₂, noise, consumable bars with low
    (amber) / out (red) thresholds, cleaning progress, and red/amber event flags — the worst rooms sort first.
  - Reuses the alerts card for acknowledge / snooze, so a vaping event or an empty dispenser is actionable.

## 0.73.0
- **Electric fence monitor — new fit-for-purpose security use case.** Wire an energizer's fault relay to an
  EM300-MCS contact (closed = energized, **open = fault**) and set the device's purpose to **Electric fence
  (energizer monitor)**. A boolean per fence line, grouped under **Security**.
  - New **Perimeter and security** section on the site landing page with a `milesight-fence-card`: one tile per
    fence line, **Energized** (green) or **Fault** (red, with how long), self-discovering and area-scopeable.
  - Alerts: a **critical "Electric fence fault"** (security category) when the line stays faulted past its
    debounce — power loss, a break or a short — with acknowledge / snooze and phone push.
  - Appears automatically on the landing page once a fence is set up.

## 0.72.0
- **Flood / drain early-warning sensor — new fit-for-purpose use case.** Set a level sensor (EM500-UDL, radar …)
  mounted over a drain, culvert, under a bridge or on a river to the **Flood / drain level (early warning)**
  purpose. It reports water level (cm) and rate of rise, and now has a **danger level** setting:
  - New **Flood & early warning** section on the Water Level dashboard with a `milesight-flood-card`: a dam /
    channel visual showing the water rising toward a dashed **danger line**, the level, the rate of rise
    (↑ cm/h) and a **Normal / Rising / DANGER** status per sensor.
  - Alerts: **"Flood warning"** (critical) when the level reaches the danger mark — early warning to act — on top
    of the existing "Water rising fast" rate alarm.
  - A flood sensor installs the Water Level dashboard on its own.
- **Dam / water-body visual.** The animated level vessel already draws tanks, silos and bins; this confirms and
  uses the **dam** shape for open water bodies (dams, pools, rivers) and the flood channel, so a dam renders as a
  banked water body, not a cylinder.

## 0.71.0
- **Water troughs for livestock on the Water Level dashboard.** A new **Water trough (float switch)** purpose
  (fit-for-purpose dropdown) turns an EM300-MCS magnetic contact into a drinking-trough monitor: wire a float
  switch so the contact **opens when the trough is empty**.
  - New **Drinking troughs** card (`milesight-trough-card`): one tile per trough, Empty (red, with how long) or
    OK (green), self-discovering and area-scopeable.
  - The supply band gains a **Troughs** tile (e.g. "2/3 · 1 empty") when any trough is set up.
  - Alerts: a trough empty beyond its debounce raises **"Water trough empty"** (tank category) with
    acknowledge / snooze, instead of a generic "left open".
  - A trough tags the site for the Water Level dashboard, so the page installs itself for a trough-only site too.

## 0.70.0
- **"Tanks & alerts" is now "Water Level" — rebuilt as a production command center.** Same dashboard
  (URL unchanged, so existing links keep working), reworked from the ground up for tank / water-level operations,
  informed by how industrial tank-monitoring systems present this data:
  - **Supply band** (`milesight-tank-band`): **total stored** (auto-scaled L → m³, or tonnes for silos with a
    density), **lowest tank**, **needs refill** (with soonest days), **days of supply** (soonest to empty), and
    **leaks / drops** — self-discovering, colour-coded, tap through to the tanks.
  - **Needs attention**: the interactive open-alerts card (low / critical level, leak / sudden drop, offline) with
    acknowledge / snooze.
  - **Tanks & silos** table and a new **Supply & refills** card (`milesight-tank-supply-card`): days-of-supply
    bars sorted soonest-first with a reorder flag, plus a recent-refills list (when + amount added).
  - **Overview + Live tabs**: the Overview leads; the per-tank gauges, sliders and a combined **30-day level
    history** (native Home Assistant graph) move to the Live tab.
- Tank sensors now expose free space, mass, empty-at time and last-refill (time + amount) on the `tank` role, so
  the cards can show supply and refills without extra setup.

## 0.69.0
- **Fixed: occupancy history was lost on a crash / hard restart.** The hourly occupancy heat-map (and the new
  retail footfall series) scheduled its save with a 120 s delay, but the tracker samples every 60 s — so the
  timer was reset on every sample and *never fired*. The data only reached disk on a clean shutdown; a crash or a
  hard restart lost the day's history. The save delay is now shorter than the sample interval, so the history
  persists continuously (every ~30 s) and survives restarts. Per-device occupancy analytics (peak, sessions,
  person-minutes, people in/out) were already saved on every uplink and were not affected.
- **Every generated tab now has the full-width header.** The Maintenance **Map** tab was a panel view with no
  masthead; it is now a sections view with the standard page header. (The farm / tanks / energy / retail "Live"
  tabs already carry it — a regression test now locks that in for all of them.)
  - Note: a dashboard you edited by hand in Home Assistant is kept as-is and not regenerated. If a tab is missing
    its header, delete that dashboard (Settings → Dashboards) and reload the Milesight integration — it rebuilds
    fresh with the current layout.

## 0.68.0
- **New Retail dashboard — one page for a store.** Auto-installs when a VS-series people counter is present.
  A command-center Overview brings together footfall, dwell, cold-chain compliance, power and air:
  - **Store insights band** (`milesight-retail-band`): people in today (vs yesterday), in store now (+ peak),
    average dwell, staff-at-counter coverage, and fridge compliance — self-discovering, tap through to detail.
  - **Footfall today** (`milesight-footfall-card`): hourly in/out bars with the net-in-store line, plus a
    per-entrance in / out / net table and a store total.
  - **Zones** (`milesight-zones-card`): average customer dwell per zone (from VS121/321 AI counters) and
    staff-coverage time for any sensor set to the new **Counter / staff zone** purpose.
  - Reuses the cold-chain band + table, the mains / load-summary power cards, and the air-quality gauges, so a
    store sees fridges, energy and shopper comfort on the same page.
- **Store-level footfall engine.** A new gateway `retail` sensor aggregates the people counters: visitors today,
  in-store-now (net in − out), peak and peak time, per-entrance totals, and an hourly in/out series that survives
  restarts. **Average dwell** is measured directly from passage counters (VS350) when available, otherwise
  estimated store-wide from footfall and occupancy (Little's Law) — the tile says which.
- **New purpose: Counter / staff zone.** Assign it to a people/occupancy sensor at the till to track staff
  coverage; VS-series people counters now also tag a site "retail" so the page installs itself.

## 0.67.0
- **Grid sizing made correct by default on every always-full-width card.** Audited all eight dashboards:
  the per-device page (`milesight-device-panel`), the table card (`milesight-table-card`) and the level/fill card
  (`milesight-level-card`) now declare `getGridOptions` (columns full, min 12) in the card itself — so they size
  to full width and never show Home Assistant's "this card doesn't support resizing" notice, even when dropped in
  without `grid_options:` in YAML. The small tiles that belong in multi-column rows (gauge, trend, device, gateway)
  stay flexible on purpose. No visible change to the shipped dashboards — they already set these explicitly — this
  just makes the standard hold by default.

## 0.66.0
- **Building dashboard rebuilt as a command center.** The old single "Areas" view is now an **Overview** that
  opens with an at-a-glance **building band** of five self-discovering tiles — **Comfort** (with how many areas
  are comfortable), **Air quality** (worst-pollutant level + score), **People** (occupied areas), **Avg CO₂**,
  and **Avg temperature** — colour-coded and tapping through to the per-area detail. New `milesight-building-band`.
- **Air quality, back where it belongs.** The CO₂ / PM2.5 / TVOC / humidity gauges (pulled off the landing page in
  0.62) return here as a self-discovering **Air quality now** row — new `milesight-air-card` draws a gauge for each
  average the site actually measures (an AM307 with no PM simply shows fewer), with good / warn / bad zones and ticks.
- **Comfort, occupancy and utilisation kept.** Comfort-per-area table, the today / yesterday occupancy heatmaps,
  and the opening-hours utilisation table all stay, now under the new header.
- **Overview + Live tabs.** The generated per-area gauges (comfort, occupancy, temp, CO₂, 24 h history) move to a
  second **Live** tab behind the Overview — same two-tier pattern as Cold storage, nothing lost.

## 0.65.0
- **Cold storage rebuilt — now compliance-first.** The Overview is a cold-chain command center: a **status band**
  (in range now, excursions today, 7-day time-in-range, compressors, doors) over the units table and day-log.
  New `milesight-coldchain-band` card.
- **Compliance brought front and centre.** New `milesight-compliance-card` surfaces the report engine that was
  buried in markdown: the **time in range**, **one-tap PDF reports** (last week / month), **corrective actions**
  (excursions needing an action flagged red, click to log one), and the **recent reports** with a PDF link and a
  compliant / attention status each. Exactly what a food-safety or HACCP audit asks for.
- **Tabs rationalized.** Cold storage had a duplicate "Units" tab (one from the bundled dashboard, one generated).
  It's now one clean set — **Overview · Units · Trends · Compliance · Compressors** — and every tab has the
  full-width header.

## 0.64.0
- **Maintenance is now a fleet-health command center.** The plain-text summary line on the Overview is replaced
  by a **fleet-health band** of five self-discovering tiles — online, batteries due (with the soonest date),
  offline > 24 h (with the longest), weak signal, and firmware (mixed models) — colour-coded and tapping through
  to the relevant tab. New `milesight-fleet-band` card.
  - The Overview's **Batteries** table now lists only batteries that **need attention** (low or due within 90
    days) instead of every device; the full battery list stays on the Devices tab and in the CSV export. New
    `batteries_due` table preset.

## 0.63.0
- **Power & Energy page rebuilt.** The energy dashboard was just a loads table and a one-line mains alert; it's
  now a power command center: a **demand** strip (load now in kW — or total amps when no voltage is set —
  running loads, after-hours, highest duty) with the **top consumers by run time**, a **mains board** showing
  live/outage, the three **phase currents** as bars, **phase imbalance** and total load, and the loads table.
  - New `milesight-mains-card` and `milesight-load-summary-card` — self-discovering by role (`mains`, `load`).
  - The mains sensor now also reports **total current and total kW** (when the mains voltage is configured), so
    the cards can show real demand — data the clamp was collecting but the dashboard never showed.

## 0.62.0
- **Production command-center landing page.** The site overview is rebuilt as an operations dashboard: a
  **status band** (open alerts, site health, gateways, devices, power/mains) answering "is everything OK right
  now", the live **alerts** card, and a **purpose-fit operations grid** — one summary card per operational
  domain the site actually has (tanks, cold chain, energy, climate, farm, coop), each showing a status badge,
  two headline numbers and the one thing wrong, linking to its dashboard. The site banner moves to the foot.
  The detailed building / air-quality / per-area views remain on the Building analytics dashboard.
  - New `milesight-status-band` and `milesight-domain-card` cards — both self-discovering by role, no entity ids.
  - The grid is driven by the site's device tags, so a site only sees the domains it has.
- **Every tab now has the header.** The auto-generated **"Live" views** (per-device tank, cold-chain, farm and
  site gauges) were the last pages without a masthead — they now get the same full-width page-header, so there
  are no header-less tabs left anywhere.

## 0.61.0
- **New Chicken coop dashboard.** A ready-made coop page built from the existing cards: full-width header, open
  alerts (with acknowledge / snooze), **feed & water** levels (the feed renders as a silo, water as a tank),
  **climate** (temperature / humidity / CO₂), **door & light-level** status, a live-controls area card, and
  links to the two coop automations. It installs itself when any device is assigned to a **"Chicken coop"**
  area, and finds the sensors by that area — no entity ids to edit. Add a sensor to the coop area and it appears.
- **Coop purposes in the dropdown.** Configure → Purpose now offers **Coop drinker (water)**, **Coop feeder
  (feed)**, **Coop pop-hole / door** and **Coop climate**. They use the usual device groups (so alerts and the
  cards keep working) but set poultry-friendly defaults — frost alert at 2 °C, pop-hole left-open at 15 min — and
  tagging any device with one installs the coop page. You can set up the coop by purpose, by area, or both.
- **Cards can scope to a Home Assistant area.** The level and table cards gained an `area:` option, so the same
  cards can be pointed at one area (coop, nursery, barn 2 …). This is what makes the coop page dynamic.
- **Two coop automations (blueprints).** *Coop lights by daylight* — the EM500-LGT drives supplemental lights to
  hold a steady day length for laying, on below a lux threshold during a lighting window and off after it.
  *Coop heater by temperature* — a heater on a UC relay (or any switch) holds a minimum temperature with
  hysteresis and a fail-safe cut-out if the probe drops out. Both target any switch, including UC relay outputs.

## 0.60.0
- **Cold-chain log is now phone-friendly.** The last wide markdown table is gone. The per-unit 7-day log is a
  new `milesight-coldlog-card`: one block per fridge/freezer with a horizontally-scrollable strip of day cells,
  each showing min–max and coloured green (in range), amber (minutes out of range) or red (excursions). Reads
  cleanly on a phone, where cold-chain is most often checked.
- **See how the alerting itself is doing.** New `milesight-alert-summary-card` surfaces the "last 7 days" data
  the integration was already computing but never showed: total alerts and how many were critical, **mean time
  to acknowledge**, how many were never acknowledged or escalated, a by-category breakdown, and the **noisiest
  sources** — so you can tune thresholds and quiet the sensors that cry wolf. Added to the Tanks & Alerts page.
- **Acknowledge all.** The alerts card gained an "Acknowledge all" button when more than one alert is open.

## 0.59.0
- **The page header is always full width.** The masthead now declares a full-width layout, so it spans the page
  edge-to-edge in the sections view and no longer shows the "doesn't support resizing" warning. Same for the
  onboarding and alerts cards. Every shipped header also carries an explicit full-width option.
- **Gauges show their scale again.** The generated gauges (CO₂, PM2.5, TVOC, building health, device thresholds …)
  now draw their tick/number scale around the dial, so you can read the value against the coloured zones at a
  glance — consistently on every page, not just the per-device views.
- **Every page has the header — including the landing page.** The site landing/Overview page now leads with the
  same full-width header (site, title, live health strip and cross-page navigation) above its info banner, so it
  matches the other dashboards instead of being the odd one out.

## 0.58.0
- **Act on alerts from the dashboard.** New `milesight-alerts-card` lists the open alerts the escalation engine
  is tracking and lets anyone **Acknowledge** or **Snooze** them right there — the same actions as the phone
  push, so a problem can be closed out from the wall tablet without digging through notifications. Each alert
  shows its severity (red/amber), category, when it started, its escalation status (waiting → paged → escalated
  → acknowledged) and who acknowledged it. The card also shows **who is on call now**, so it's clear who was
  paged; it reads "All clear" when nothing is open. Deployed on the Tanks & Alerts dashboard.
  - New **`snooze_alert`** service (alert_id, optional minutes) to match the existing `acknowledge_alert`.
  - The gateway's alerts sensor now also reports **on-call / backup people** and the snooze default, so the
    card needs no configuration.
  - The first-run onboarding checklist gained an **"Alerting set up"** step, so a new install is nudged to set
    up who gets paged — not just to wire up sensors.
- **A render guard in CI so a broken card can't ship.** Every push and tag now runs a headless browser that
  instantiates every card and every table preset against sample data and **fails the build on any console
  error or empty render** (`tests/cards/render.cjs`, wired into `.github/workflows/validate.yml`). This is the
  same check that was being run by hand each release — now automatic, before HACS pushes an update to a farm.

## 0.57.0
- **Every list is now a table.** The sections that were still markdown lists are rebuilt with the highlighting
  table card, so they sort, filter, export to CSV and tint problem rows red/amber like the rest of the app:
  - **Batteries** and **Service history** (Maintenance), **Gateways** (Signal) — new `batteries`, `service`
    and `gateways` presets. Batteries sort by time-to-replace and go red when a cell is critical.
  - **Comfort per area** and **Utilisation** (Building analytics) — new `comfort` and `utilisation` presets.
    The table card gained an **attribute-match** source so it can tabulate the analytics sensors (tagged by
    `kind` / area), not only role sensors.
  - **Tanks & silos** (Tanks) now has a sortable table under the vessel graphics.
  - The occupancy heatmap, the open-alerts and irrigation/frost banners stay as they are — a table would be a
    worse fit for status and per-hour data.
- **The page header is on every tab.** The Maintenance **Devices** and **Signal** sub-views now carry the same
  masthead (site, title, health strip and cross-page nav) as every other page, so no tab looks half-built.

## 0.56.0
- **First-run onboarding checklist.** A new `milesight-onboarding` card guides a brand-new install through
  setup with a live, self-checking list — **gateway online, devices added, data arriving, purposes assigned** —
  each step reading the real state and ticking itself off as the system comes up. The whole card hides once the
  system is set up, so it never clutters an established site. It leads both the site landing page and the
  always-present Maintenance dashboard, so a fresh install sees it even before the landing page is generated.
  - Production-minded: the **"data arriving"** step turns **red** when devices are added but none are reporting
    (silent sensors are a safety risk on a farm, not a cosmetic issue) and the card stays visible in that state
    even after it was dismissed. Steps link straight to the integration/device pages that fix them.
- **Cross-page navigation in the header.** The page header now shows a navigation strip linking every Milesight
  dashboard in the sidebar (and the site landing page), with the current page highlighted, so the generated
  pages feel like one app. It discovers the pages itself from the sidebar; set `nav: false` to hide the strip.
- **Polished empty states across the cards.** Tables, the level card and the device page now show a clear,
  icon-led empty state that distinguishes **"not set up yet"** (actionable guidance — which sensor to add and
  where to assign its purpose) from **"data not arriving"**. In particular, a device table whose rows are all
  offline now shows a red **safety banner** ("Every device is offline — check the gateway and its network link")
  above the data, so an all-quiet fleet reads as a warning rather than a normal-looking table.

## 0.55.0
- **The remaining dashboards rebuilt with the card system.** Cold chain, Energy and Farm no longer use plain
  markdown tables — they now use the highlighting table card, so a problem row tints red/amber with an icon, cells
  past a threshold stand out, and each table has filtering, CSV export, sorting and click-through to the device,
  like the rest of the app.
  - New table presets: **cold_chain** (fridges/freezers — now, allowed range, min/max, time out of range, door),
    **compressors**, **loads** (energy), **pumps** and **pivots**.
  - The table card gained an **entities-by-role** data source, so it can tabulate one row per device from the
    device sensors directly (not only from a single aggregate sensor).
  - Irrigation/frost and mains stay as status alerts (the right form for them); per-unit history logs stay as a
    drill-down beneath the tables.

## 0.54.0
- **A consistent page header on every generated dashboard.** New `milesight-page-header` card gives each page a
  masthead: the site name, the page title and a one-line description of what the page is for, plus a live health
  strip — **devices online, gateways online, open alerts** — so "is everything OK?" is answered at the top of
  every page. It derives those figures itself (no entity IDs to set) and themes to light/dark.
- Deployed to all six shipped dashboards — **Maintenance, Tanks & Alerts, Farm, Cold chain, Energy, Analytics** —
  each with a fitting title, subtitle and icon. The site landing page keeps its richer banner; the device page
  keeps its own device header; so every page now reads as part of one product.

## 0.53.0
- **Gauge scale labels.** Arc and half gauges now draw a tick scale with value labels around the dial (with the
  min/max endpoints labelled), like a classic instrument — so you can read the value against the zones at a
  glance. On by default for arc/half; set `ticks: false` to hide, `tick_count:` to change density. The compact
  gauges in the generated dashboards keep ticks off to stay tidy.
- **Classic-gauge fallback.** A new **"Use Home Assistant's built-in gauges"** option (gateway → Configure → site
  info) makes the generated dashboards emit the built-in `gauge` instead of the custom card — a safety switch if
  the custom cards ever don't load. (The custom cards auto-load and Home Assistant upgrades them once the bundle
  registers, so this is rarely needed.)

## 0.52.0
- **Gauge zones drawn on the track.** The gauge now paints its severity bands as coloured arcs on the dial —
  a green safe zone with amber/red danger zones — *behind* the needle (a value marker on the ring and bar),
  so you can see how close a reading is to its limits even when it's fine. Plain gauges (no severity) keep the
  single progress fill.
- **The gauge card now replaces the built-in gauges in the generated dashboards** (building analytics, the Live
  views, cold-chain temperature), so they get the zone bands, animation and light/dark theming automatically.
- Fixed a config clash: the gauge style is now set with **`shape:`** (arc / semicircle / ring / bar) instead of
  `type:`, which Lovelace reserves for the card type — so the style is settable from YAML and the editor, not
  only the live switcher.

## 0.51.0
- **Device page: threshold-aware gauge, real controls, and an activity timeline.**
  - **Cold-chain / climate gauge** now colours itself by the device's own temperature alarm band — green in range,
    red when too cold or too warm — and sizes its scale around the thresholds. (The temperature entity now exposes
    `alarm_low` / `alarm_high` / `min_today` / `max_today`.)
  - **Controls** are now real actions: a button entity presses, a switch toggles (showing On/Off), plus a quick
    **Walk test** link to the commissioning panel.
  - **Alerts** show as chips at the top of the page (out-of-range, low level/battery, problem sensors).
  - **Activity** timeline lists the device's recent events from the Home Assistant logbook.

## 0.50.0
- **Per-device page.** Clicking a device in any table now opens a dedicated, designed **device page** laid out
  by device type: a header (name, model · area, online, signal, battery), a type-specific **hero** (a tank's
  animated vessel, a probe's temperature gauge, an air sensor's CO₂ gauge, a pump's run-state + current gauge),
  a **trend** of the key metric, a tidy grid of the device's other **readings**, and any **controls**. It's a new
  self-contained card (`milesight-device-panel`) that reads the device from the page URL, shown in a new
  **Device** sub-view (with a back button) on the maintenance dashboard.
  - The device cards gained a chrome-less **bare mode** so they compose cleanly inside the page.
  - Table rows route to this page by default; set `link: more-info` on a table to keep the old dialog behaviour.

## 0.49.0
- **Table card: filter box, CSV export, remembered sort.** Tables with more than a few rows get a live **Filter**
  box; any table offers a **⭳ CSV** download of the current (filtered + sorted) rows; and the column sort you pick
  is **remembered per card** between visits.
- **New animated gauge card** (`milesight-gauge-card`) — a general gauge for any numeric entity that can replace
  the built-in ones. Four styles — **Arc**, **Half**, **Ring** and **Bar** — and the viewer can **switch style
  live** on the card (the choice is remembered). The value **animates** smoothly when it changes (needle sweep /
  arc fill), with severity bands (good / warning / critical) via `segments` or Home-Assistant-style `severity`.
  Themes to light and dark, with a visual config editor.

## 0.48.0
- **Table card: three more presets, click-through and sorting.**
  - **Presets** `offline`, `weak` and `firmware` join `devices`. The maintenance dashboard's **Offline**, **Weak or
    lossy** and **Firmware** sections are now tables too (the firmware table groups by model and flags mixed
    versions). Each preset carries its own columns, filter and highlight rules.
  - **Click a row → the device.** Rows open the device's more-info dialog (or its device page), so you can jump
    straight from a problem to the device. (A `device_id` is now included per device for this.)
  - **Click a column header to sort** (numeric or text, ascending/descending), with an arrow on the active column.
- The table remains fully overridable (columns, thresholds, row rules) and self-contained.

## 0.47.0
- **New table card with issue highlighting** (`milesight-table-card`). A compact, sortable device table that
  **faintly tints a whole row** when something's wrong — red for offline, amber for low battery — and **emphasises
  individual cells** past their threshold (weak RSSI/SNR, high spreading factor, packet loss), so problems jump out
  at a glance. Works in light and dark, with an optional "only show issues" mode. Ships a `devices` preset (columns
  + thresholds for the Milesight device shape); columns and rules are fully overridable.
- **Maintenance dashboard "All devices" is now this table** instead of a text list.
- Fixed: the **Tanks dashboard** animated-level grid (added in 0.46.0) is now actually wired into the shipped
  dashboard — the earlier change had been reverted by the resource-sync step before release.

## 0.46.0
- **Visual config editors for every card.** Adding a Milesight card now shows a proper form — entity pickers,
  dropdowns (vessel shape, contents), number boxes and toggles — instead of hand-edited YAML.
- **The Level card has an auto mode.** With no `entity` set it finds every tank/silo device on the site and draws
  a responsive grid of animated vessels (shape and colour per device, low/critical states). The shipped **Tanks &
  alerts** dashboard now shows this grid above the existing text summary — the emoji fill bar is replaced by real
  animated vessels, still with zero entity IDs to configure.

## 0.45.0
- **Four self-contained Lovelace cards**, shipped with the integration and auto-loaded — no HACS, no ApexCharts,
  no manual resource. They appear in the dashboard "Add card" picker as "Milesight …" and theme themselves to
  the user's dashboard (light and dark):
  - **Milesight Gateway** (`milesight-gateway-card`) — online, packets today, devices heard, connection path,
    location and clock.
  - **Milesight Device** (`milesight-device-card`) — battery ring, signal bars (RSSI quality), online + last-seen,
    the headline reading and an inline trend sparkline. Finds the device's battery/signal siblings automatically.
  - **Milesight Trend** (`milesight-trend-card`) — a lightweight SVG line/area chart over history for any sensor.
  - **Milesight Level** (`milesight-level-card`) — an animated fill that takes the shape of the vessel from the
    device's purpose: tank, silo, dam or waste bin, with a moving liquid surface, low-level colour states, and
    volume / capacity / days-left read from the sensor's attributes.
  Point a card at an entity and it fills in the rest; the cards also work with any Home Assistant entity, not
  only Milesight ones.

## 0.44.1
- **Configure now also sets the gateway clock.** Since "Configure gateway" is already logged in, it now pushes
  Home Assistant's time to the gateway as part of the same run (reported as "clock set from Home Assistant"). So
  every gateway setup/re-apply keeps the clock right — the closest to hands-off off-grid timekeeping without
  storing the admin password. Refresh stays read-only and does not touch the clock. The standalone "Sync clock
  from Home Assistant" button remains for on-demand use.

## 0.44.0
- **Sync the gateway clock from Home Assistant (off-grid time source).** A new "Sync clock from Home Assistant"
  button on a gateway's Settings sets the gateway's time to Home Assistant's current time, in the gateway's own
  timezone. For off-grid sites with no internet NTP, Home Assistant is the time source — no NTP server needed.
  Verified on UG65 fw60 (`yruo_system` set `time`, `set_type` 2). The admin password is used only for that login
  and never stored, so the sync is a deliberate action rather than an automatic background job.

## 0.43.0
- **Gateway location, stored in Home Assistant.** Each gateway's Settings now has a Latitude / Longitude field
  (with "Use Home Assistant's location" to fill it from HA's own coordinates). It's saved in Home Assistant, not
  on the gateway, so it works on every model regardless of whether the gateway firmware has a location field. The
  coordinates show in the Gateways list and are available for maps and coverage.

## 0.42.2
- **Clearer button label.** The gateway setup button is now "Configure gateway" for both a new and an
  already-added gateway (it previously read "Re-apply settings" when editing one, which didn't match the
  "Configure" wording used elsewhere).

## 0.42.1
- **Fix `POST …/integrations/mqtt → HTTP 409` when re-configuring a gateway.** A gateway whose application
  already had an MQTT integration (e.g. it was set up before on the old shared topics) rejected a second POST
  with 409. Configure now updates the existing integration in place (PUT) instead of trying to create another,
  so moving a gateway onto its per-gateway `milesight/ns/<eui>/…` topics works on gateways that were already
  configured.

## 0.42.0
- **Register a new device on a specific gateway's embedded network server.** When you add a device by hand
  (scan or type it in) and more than one gateway has its embedded MQTT server set up, the Add screen now shows
  an **"On which gateway"** picker, and the device is registered on that gateway's own network server only.
  - Each gateway configured for MQTT now gets its **own ns-api management channel** (`milesight/ns/<eui>/request`
    and `/response`) while the data pipeline stays shared (`milesight/uplink`), so Home Assistant can address one
    gateway's embedded server without the add-device request going to every gateway at once (which previously
    risked duplicate OTAA joins).
  - **Discovered** devices are unaffected: they register on the gateway that heard them, with no picker — the
    picker is only for a new device you add by hand.
  - Existing gateways get their per-gateway channel the next time you run **Configure → Add devices to the
    gateway** in the panel. The config-flow gateway remains a registration target via the hub-wide connection.
- Only the embedded-MQTT path is affected. The Semtech path is unchanged: there, all gateways feed Home
  Assistant's built-in network server and a device is registered once and heard by every gateway.

## 0.41.1
- **Add-a-device screen now names the gateways that will cover a device.** The per-network-server picker only
  appears when there is more than one network server set up; with a single network server (the usual case) the
  two gateways share one topic namespace and feed one network server, so a registered device is heard by both
  automatically. The screen now says so — e.g. "Covered by both gateways: Local Gateway, UG65 …" — instead of
  showing nothing. (The "On which gateway" dropdown was correctly hidden before; it is for multiple independent
  networks, not multiple gateways on one network.)

## 0.41.0
Milestone release consolidating the gateway and commissioning work since 0.40.0.

### Highlights
- **Zero-touch gateway configuration over the LAN, verified on real hardware (UG65 fw 60, UG56):** Home Assistant
  logs into the gateway and sets it up — points the Semtech packet forwarder at HA and/or creates the embedded
  network-server MQTT application — with nothing touched on the gateway's own web page. The firmware-specific login
  (router web session for `/cgi`, JWT for the REST API) is handled automatically.
- **Commissioning panel — Gateways tab:** add & configure, a live gateway list with status, **Refresh from gateway**
  (reads the real Semtech/MQTT config and sets the connection label authoritatively), re-apply settings, and forget.
- **Discovered devices & gateways in the panel:** the items Home Assistant auto-discovers now appear in the panel
  with Add / Configure / Ignore, so an installer never has to leave the screen.
- **Choose which gateway to register a device on** when more than one is set up for provisioning.
- Connection labels reflect what was configured (not only what has been heard), and the Gateways tab shows the real
  connection paths ("Semtech UDP + MQTT").

### Fixed
- Integration going red after a reload (an unload callback returned a Task on HA/Python 3.14).
- Gateway device-list attributes trimmed under the recorder's 16 KB limit.
- Removed dead/conflicting gateway device-registration helpers that used the wrong profile key.

(See 0.40.1–0.40.11 below for the detailed per-release notes.)

## 0.40.11
### Changed
- The Gateways tab's status column now shows the real **connection paths** (e.g. "Semtech UDP + MQTT") instead of
  the raw discovery code ("lan_dhcp"), so a Configure or Refresh is reflected there. Gateways not heard yet show how
  they were found.

## 0.40.10
### Added
- **"Refresh from gateway"** in the Gateways tab: logs into the gateway and reads its *actual* configuration — the
  Semtech destinations and the MQTT application — then sets the connection label authoritatively from that
  (`Semtech UDP`, `MQTT`, or both), without changing anything on the gateway. Use it to reconcile a gateway whose
  label is stale, or that was set up outside the panel. The admin password is sent only to the gateway and never stored.

## 0.40.9
### Fixed
- **A gateway's connection label now reflects what was configured, not only what has been heard.** Configuring a
  gateway (Semtech + MQTT) from the panel now records both paths immediately, so it shows "Semtech UDP + MQTT"
  right away instead of only "Semtech UDP" until the first MQTT uplink happens to arrive. (Re-run **Configure** on
  an already-set-up gateway to correct its label.)

## 0.40.8
### Fixed
- **Add a device → "register on the gateway" now lets you choose which gateway** when more than one is set up for
  provisioning. Previously it silently used the first one. The New-device form shows an "On which gateway" picker
  (labelled by gateway name) whenever there are two or more; with a single gateway it's unchanged.

## 0.40.7
### Added
- **Discovered devices and gateways now appear in the commissioning panel.** The same items Home Assistant shows
  under Settings → Devices & services → Discovered are now listed right where the installer works:
  - **Add a device tab** → a *Discovered devices* list (heard but not set up), each with its guessed model and
    **Add** / **Ignore** — Add opens the pre-filled device form so there's no need to leave the panel.
  - **Gateways tab** → a *Discovered gateways* list (found on the network), each with its IP and **Configure** /
    **Ignore** — Configure pre-fills the gateway IP so you just enter the admin login.

## 0.40.6
### Added
- **Gateways tab in the commissioning panel.** The installer panel now manages gateways end to end, not just devices:
  - **Add & configure a gateway over the LAN** — enter the gateway IP and admin login, pick *Semtech + MQTT*,
    *Semtech only* or *MQTT only* and the frequency band, and Home Assistant logs in and sets it up (points the
    Semtech packet forwarder at HA and/or creates the network-server MQTT application) with nothing touched on the
    gateway's own web page. MQTT credentials default to Home Assistant's own broker.
  - **A live list of gateways** with online status, IP, model, firmware, connection type and packets today.
  - **Update settings / re-apply** (e.g. after Home Assistant's IP changes) and **Forget** per gateway.
  - The admin password is sent only to the gateway and is never stored or logged.
### Changed
- The gateway LAN configuration used by the panel, the `configure_gateway` service and the config flow now share one
  verified helper (`run_gateway_config`), so all three behave identically.

## 0.40.5
### Changed
- Maintenance release — version bump to publish a clean HACS release. No functional changes since 0.40.4; the gateway
  LAN flow (router login, Semtech, and the network-server MQTT application) remains verified end-to-end against a
  real UG65 (firmware 60.0.0.50).

## 0.40.4
### Changed
- Removed dead, conflicting gateway device-registration helpers (`pick_profile`, `device_body`, `async_add_device`
  in `gateway_api.py`) that were never wired in and used the wrong profile key (`deviceProfileID` instead of
  `profileID`). Device registration on the network server is handled solely by the MQTT provisioning path
  (`ns_api.py` / `provisioning.py`), which uses `profileID` correctly. No behaviour change.
- Verified end-to-end against a real UG65 (fw 60.0.0.50): the gateway LAN flow logs in, points the Semtech packet
  forwarder at Home Assistant, and creates the network-server application with its MQTT integration (Manual mode,
  broker = HA IP:1883, `milesight/*` topics, `%devEUI%` payload).

## 0.40.3
### Fixed
- **Gateway LAN configuration now works on UG65 firmware 60** ("gateway refused yruo_status.get (summary)" /
  "Session not found"). The gateway has two separate logins: the router OS (`/cgi`, the `yruo_*` calls) uses a
  `td` session cookie set by the web login (`core: user`, `function: login`, `base: web_login`), while the embedded
  network server (`/api/...`) uses the JWT. The client now performs the router web login first, holds the `td`
  session, and the v0.40.0 change that sent HTTP Basic auth on every request — which this firmware rejects as
  "wrong password" — has been removed (Basic is kept only as a fall-back for older firmware). Verified end-to-end
  against real UG65 (fw 60.0.0.50) traffic.
- Gateway errors now include the gateway's actual reply, so a refusal is diagnosable instead of opaque.

### Changed
- The gateway login is bounded to very few attempts and the real request shape is tried first, so a wrong password
  can no longer walk the account into its lockout.

## 0.40.1
### Fixed
- A failed or interrupted reload could leave the gateway entry stuck ("Error unloading entry"): unload is now
  resilient — a cleanup or stop error is logged and the entry still unloads, so a reload or restart recovers it.
- "State attributes … exceed maximum size of 16384 bytes" on the *Devices on gateway* sensor: the device list is
  now compact and capped (with `devices_total` kept as a count), so it stays well under the recorder limit on
  gateways with many devices.

## 0.40.0
### Fixed
- **Gateway configuration over the LAN now logs in correctly** (UG65 / firmware 60 returned HTTP 500): the gateway
  authenticates its web calls with HTTP Basic auth, which the client now sends (and the network-server REST calls
  use the login token). Verified against real UG56 and UG65 traffic.
### Added
- Gateway → Configure → **Site information**: *Use the company name as Home Assistant's name* renames this Home
  Assistant instance (the name shown top-left) to your site's company name.
### Changed
- Gateway login is also tried in several forms (the password transform and content-type have varied across gateway
  firmware), so configuring works on more UG firmware versions.
- A gateway server error (HTTP 5xx) during configuration is reported as such instead of "wrong username or
  password", and the MQTT step shows the broker address the gateway will actually use (Home Assistant's IP when the
  broker is the Mosquitto add-on).

## 0.39.3
### Fixed
- Configuring a gateway over the LAN failed with *gateway refused …*: the gateway expects its web calls as a
  form-encoded JSON body and authorises with the login token as both a header and a cookie. The client now matches
  the gateway's own web page exactly (verified against real UG56 / UG65 traffic).
### Changed
- The MQTT step now **prefills the broker login from Home Assistant's own MQTT integration** – leave it blank to
  reuse it, so there is nothing to type for the common case.
- Choosing *Semtech* no longer shows the MQTT fields: the MQTT broker login is asked on a second step, only when
  *MQTT* or *Both* is selected.

## 0.39.2
### Added
- **Configure over LAN** button on every gateway device: set a gateway up from its device page even when Home
  Assistant already has it (so it never appears under Discovered). Press it, enter the gateway's admin login and
  what to set up (Semtech / MQTT / both). The gateway's IP is used when known, or you can type it in.

## 0.39.1
### Added
- **Forget a gateway**: delete a gateway from the Home Assistant device page (a *Delete* option is now offered), or
  the service `milesight_lorawan.forget_gateway` (by EUI). It is removed from the integration's statistics so it can
  be discovered and set up again – useful for re-testing the automatic configuration.
- **Configure the gateway from Home Assistant over the LAN** – no visit to its web page. On a discovered gateway
  (with an IP address) tick *Configure this gateway for me* and enter its admin login; Home Assistant can:
  - point the gateway's packet forwarder at Home Assistant's built-in network server (a Semtech destination), and / or
  - set up the gateway's own embedded network server: create an application and its MQTT data transmission (broker,
    uplink/downlink/ack/join and ns-api request/response topics) so uplinks arrive over the broker.
  Also as a service `milesight_lorawan.configure_gateway` (host, admin login, mode: semtech / mqtt / both) for
  gateways already added. The admin password is sent only to the gateway, encrypted the way its own login page does,
  and is never stored or logged. Works with UG65 / UG67 / UG56 / UG63 firmware that has the web API.
  For the off-the-shelf product: the customer plugs the gateway in, it is discovered, they enter its password once,
  and both the gateway and Home Assistant are set up end to end.

## 0.38.0
### Added
- **How each gateway is connected and was found**: gateway devices show the connection in their model line
  (*LoRaWAN gateway · MQTT*, *· Semtech UDP*, *· MQTT + Semtech UDP*) and get a **Connection** sensor (diagnostic) –
  *MQTT · gateway network server*, *MQTT · ChirpStack* or *Semtech UDP · Home Assistant network server* – with
  *found via* (LAN · DHCP, LAN · network scan, QR code, Semtech UDP · first packet, MQTT · first uplink), IP and MAC
  address, web page and first seen as attributes. Discovery cards say how the gateway was found
  (e.g. *UG65 FA2994 (LAN · 192.168.1.50)*).
- **Network scan for gateways**: 90 s after start, every 6 hours and with the new **Scan network for gateways**
  button, Home Assistant looks for Milesight gateways on its network. Known gateways get their IP address and a
  link to their web page; new ones are offered under *Discovered*. DHCP discovery alone only sees a gateway when it
  asks for an address (after a restart or lease renewal), so gateways that were already running were missed.

## 0.37.0
### Added
- **Gateway discovery on the network**: a Milesight gateway that joins the network (DHCP, MAC prefix 24:E1:24) is
  offered under *Discovered*. Name it and pick an area; the card shows what to set on the gateway (Semtech packet
  forwarder → Home Assistant's IP, port 1700). On a new installation it sets up the integration with the built-in
  network server, no MQTT broker needed; on an MQTT site it can switch the built-in network server on.
- **Gateway discovery from traffic**: a gateway heard for the first time (built-in network server or MQTT uplinks)
  is offered as *New gateway sending to Home Assistant*.
- **Gateway QR codes** in *LoRaWAN commissioning*: gateway EUI, MAC, JSON or label text → name and area; adopted
  at once if it already sends, else from its first packet.
- Gateways announced beforehand are matched to their first packet by EUI or IP address, renamed, put in their
  area, linked to their web page, with a notification and the event `milesight_lorawan_gateway_connected`.
### Changed
- MQTT is no longer a hard dependency: an installation that only uses the built-in network server works without
  an MQTT broker (MQTT is still used when a gateway entry has an uplink topic).

## 0.36.0
### Added
- **Cold storage dashboard** (was *Cold chain*), built for production sites: **Overview** with the site status (units
  in range, in alarm, drifting within the delay, doors open, worst time in range over 7 days), red / amber alerts and
  every unit by area; **Units** detail; **Trends** (hourly and daily min / mean / max over 7 and 30 days);
  **Compliance**; plus the existing **Table** and **Compressors** tabs.
- **Cold-room compliance reports**: a PDF per fridge, freezer or cold room, weekly and / or monthly, e-mailed
  automatically through a notify service (PDFs attached) – min / max / mean / mean kinetic temperature, time out of
  range, excursions with peak, duration and corrective action, door-open time, data coverage and gaps, daily table,
  chart and sign-off. Gateway → Configure → *Cold-chain compliance reports*; buttons for last week / last month;
  service `milesight_lorawan.compliance_report`; sensor *Compliance reports*; event
  `milesight_lorawan_compliance_report`. No extra Python packages (built-in PDF writer).
- **Corrective actions** for cold units: a *Log corrective action* field on the device (saved with the user's name),
  also `log_service` kind `corrective_action`; they are printed in the reports.
- *Time in range 7 days* sensor for every fridge / freezer probe.
### Changed
- Current clamps: **Estimated power** is now real power in **W** (current × voltage × power factor) and is enabled
  by default; the VA value is now called *Apparent power*.

## 0.35.0
### Added
- Current clamps (CT101/CT103/CT303/CT310…): **Voltage**, **Power factor** and **Running above** are now typed-in
  fields under *Configuration* on the device page.
- **Energy for clamps without an energy counter**: once a voltage is entered, *Energy* (kWh) is worked out from the
  clamp's cumulative current: Ah × voltage × power factor (default 0.85). It counts up like a meter, so it works
  in the HA Energy dashboard, and *Pump energy today* and *m³ per kWh* use it.
### Changed
- *Pump normal current* and *Pump max starts per hour* are typed-in boxes (under Configuration) instead of
  sliders, with steps of 0.01 A.
- **Running threshold is automatic by default**: 30 % of the pump normal current when one is set (0.8 A →
  running from 0.24 A), otherwise 0.2 A. The old fixed 0.5 A that earlier versions saved without asking counts as
  automatic; type a value into *Running above* to fix it.

## 0.34.2
### Fixed
- Gauges on the farm, tank, cold-chain, energy, analytics and landing pages showed "Entity is non-numeric" while
  their sensor had no value yet (device not heard yet, offline, or a value the model does not report). They now
  show a small tile with the sensor's state until a number arrives, then the gauge.
- Maintenance → Overview lists devices that were **never heard** since they were added, with what to check.
- The *Network server* sensor keeps its capitals ("Gateway (Embedded NS)").

## 0.34.1
### Fixed
- **Alert notifications**: tapping a notification no longer jumps to a dashboard (the app asked "Open URL?" and
  the alert itself could not be read). The dashboard is a button instead – **View on map** for devices that have a
  location, otherwise **Open dashboard** – next to Acknowledge and Snooze.
- **"Use my phone's location" said permission denied** although the app had location access: pages served over
  http:// are not allowed to read GPS. The button now falls back to the Home Assistant app's own location tracking:
  it asks your phone for a fresh position (up to 20 s) and saves it with its accuracy and which phone it came from.

## 0.34.0
### Added
- **Device location**: every device can have a fixed location – on site in **LoRaWAN commissioning → Walk test →
  Use my phone's location** (the phone's GPS, with its accuracy), or device → Configure → *Location* with a map
  picker. It becomes the device's **Location** entity (shown on Home Assistant's map), a **Map** tab on the
  Maintenance dashboard, and a column / map link in the handover report ("No location captured" is listed as an
  open point). Settings profiles never copy it.
### Changed
- **One Maintenance dashboard with tabs**: *Overview* (batteries, offline, firmware, service history), *Devices*
  (every device once: status, battery and due date, signal, network server, firmware, last command, last seen),
  *Signal* (gateways, weak or lossy devices) and *Map*. The separate *LoRaWAN fleet* and *LoRaWAN signal*
  dashboards are removed from the sidebar – their content is in the tabs, without the duplicated lists (the old
  "needs attention" and two "all devices" tables). Phone links for gateway and command alerts open the matching tab.
- The built-in network server, network-server label, smart alerts and maintenance features are out of beta.

## 0.33.1
### Fixed
- **Site landing page did not appear**: a landing page made before 0.30 (no fingerprint) was treated as "edited by
  hand" and never updated, and problems were only logged at debug level. It is now replaced once (your old copy
  is kept in storage), retried while the gateway's sensors are still starting, and failures are logged as warnings.
- The landing page is named after the **site / company** (Site information → Company, else Home Assistant's
  location name) instead of the gateway entry ("Milesight gateway (milesight/uplink/#)"), and a notification with
  a link appears when it is created.

## 0.33.0
### Added – battery and maintenance
- **Battery forecast**: *Battery replacement due* (date) and *Battery days left* on every battery device, from the
  daily battery trend, corrected for changes in the reporting rate; new batteries detected by themselves or via
  the **Battery replaced** action.
- **Maintenance dashboard** (every site): batteries due, offline more than 24 h, weak signal, firmware per model
  (mixed versions flagged) and the **service history** – battery replacements, firmware changes and applied
  profiles are logged automatically; **Log service** action for your own entries. Device alerts open it.
- **Settings profiles**: device → Configure → *Settings profile* – copy a device's options and over-the-air
  settings to other devices of the same model, save / load / delete named profiles; action
  `apply_settings_profile`. Only differing settings are sent and confirmed like any command.
- **Installer handover report**: gateway button *Create handover report* / action `handover_report` – printable
  page (print or save as PDF) and CSV in /config/www/milesight/ with open points, gateways and every device's
  area, purpose, network server, signal, battery and due date, firmware, last seen and walk-test result.

## 0.32.0
### Added – smart alerts
- **Phone buttons**: *Acknowledge*, *Snooze 1 h* and *Open dashboard* on every alert (tapping the notification
  opens the dashboard too). The dashboard matches the alert: Tanks & alerts, Farm, Cold chain, Energy & HVAC,
  Building analytics, Signal / Fleet, otherwise the site landing page. A snoozed alert pauses reminders and
  escalation and comes back as *Still active* if it has not cleared; snooze time is a setting.
- **On-call rota**: lines like `Mon-Fri 07:00-17:00: notify.mobile_app_juan`, overnight shifts and weekends;
  the person on call is told first, outside the rota *Notify first*.
- **Escalation to the next person**: *Escalate to* is now an ordered list – each escalation adds the next person,
  one at a time (with one backup it behaves as before).
- **Quiet hours per category**: e.g. `building: 18-07`, `tank: none`; other categories keep the general quiet hours.
- **Weekly alert summary** (default Monday 08:00): alerts by category, the noisiest devices and the mean time to
  acknowledge, to *Notify first* and the rota. Gateway sensor **Alerts last 7 days** (with who is on call now)
  and button **Send alert summary**. Alert history is kept 5 weeks.

## 0.31.2
### Fixed
- Network-server label missing on most devices: it was only added after a device's next uplink, and devices set
  up together with the gateway at start-up were skipped. All devices are now labelled about a minute after
  start-up (and at every start); a device that has not reported yet is labelled from its set-up (AppKey for the
  built-in network server → Home Assistant, otherwise the gateway's network server).

## 0.31.1
### Added
- **How each device is connected**: a *Network server* diagnostic sensor on every device (*Gateway (Embedded NS)*,
  *ChirpStack* or *Home Assistant (packet forwarder)*) and a matching device label – **LoRaWAN · Gateway network
  server** / **LoRaWAN · Home Assistant network server** – shown as a chip in Settings → Devices and usable as a
  filter. The label swaps by itself when a device moves from one network server to the other; your own labels
  are kept.

## 0.31.0
### Added
- **Built-in LoRaWAN network server.** Gateways send their packet forwarder traffic (Semtech UDP, port 1700)
  to Home Assistant – on Milesight gateways as an extra *Multi-Destination* row next to the Embedded NS. Devices
  join Home Assistant directly with their AppKey: no device list on the gateway, and any gateway forwarding to
  Home Assistant carries any of your devices.
  - OTAA joins (LoRaWAN 1.0.x) with MIC check and DevNonce replay protection; join-accept through the gateway
    that heard the device best; device addresses from the site's own block (site number 0–511).
  - Data frames: MIC, 32-bit frame counters, replay protection, decryption, duplicates from several gateways
    merged (best signal first); uplinks go through the normal path, so decoders, entities, dashboards, alerts and
    command confirmation work unchanged.
  - Class A downlinks: commands for devices joined here are queued and sent in the receive window after the next
    uplink; confirmed downlinks report the device's ACK; LinkCheck and DeviceTime (clock sync) answered.
  - Devices that try to join appear in **Discovered** with a form for the AppKey; **Configure → Network server
    keys** on each device; **Configure → Built-in network server** on the gateway.
  - Gateway sensor **Network server devices** with gateways, downlink airtime, counters and recent
    joins / refusals. Keys are stored in Home Assistant only and never logged or shown in diagnostics.
- Scope: EU868, class A, no ADR yet. The gateway's MQTT feed keeps working alongside.

## 0.30.0
### Added
- **Site landing page** for each gateway, now created and refreshed **automatically** (at start-up and when
  devices change – not only with the button). Sidebar title: the site's name. It shows the banner (site name,
  company, address, facilities contact, logo, status), **buttons to every installed dashboard**, overall health,
  **open alerts** and *Needs attention*, air quality, system health, **People** (in the building now, people per
  area, compact heat map), a section per area, and the site's **tanks, irrigation, pivot map, pumps, cold chain
  and energy**. A landing page you edited by hand is left alone; the gateway button (renamed **Update site
  dashboard**) regenerates it. If you had generated the old Building dashboard before, press the button once.
- **Building analytics** gets a *Live* view: per area comfort and occupancy gauges, temperature, CO₂, humidity and
  a 24 h graph.

### Changed
- **Building analytics**, **Farm** and **Tanks & alerts** dashboards rebuilt as sections views with
  phone-friendly cards instead of wide tables:
  - occupancy heat maps are one row of squares per area (06:00–21:00) with people now and today's share – no more
    sideways scrolling;
  - utilisation shows a bar, or *closed today / outside opening hours* instead of "– %";
  - comfort per area: score with a coloured dot, temperature, humidity and CO₂ on one line;
  - tanks: fill bar, litres, use per day and days left; pumps and pivots: status line, progress bar and details;
  - irrigation advice as a coloured banner with a soil-moisture bar.

## 0.29.1
### Added
- **Edit applied sensor templates** (device → Configure → Sensor templates → *Edit*): the form opens with the
  template's values, first channel, address and name prefix; change them and submit. The old channels are replaced
  in the channel map and, on a UC100, **only the channels that changed** are sent again (moved or dropped channels
  are removed from the controller). No more remove-and-re-apply.

## 0.29.0
### Added
- **Live view** on the Farm, Tanks & alerts, Cold chain and Energy & HVAC dashboards, built from the devices that
  are set up (rebuilt when devices change, unless you edited the dashboard):
  - **Pivot map**: the AT101 on the end tower with its track of the last 12 hours and the pivot centre, plus a
    *Round done* gauge, status, angle, speed, finish time and the *Pivot stopped* button.
  - **Gauges** with coloured bands from the device's own limits: pump current (dry-run / normal / overload),
    starts per hour, tank fill (low alarm), soil moisture (irrigation target), cold-chain temperature (allowed
    band), compressor and load duty cycle, phase imbalance.
  - **Sliders** to change limits from the dashboard.
- **Setpoint sliders** (number entities): tank low alarm, pump normal current and max starts per hour, pivot
  stall time, temperature alarm below / above and left-open time (purposes), and on the gateway the irrigation
  target soil moisture, irrigation time and frost temperature. Moving one updates the device's options.
- The pivot centre is drawn on map cards (*Distance from pivot centre* carries its coordinates).

## 0.28.1
### Changed
- LuxPower template: *Energy today* values are unticked by default (the Energy dashboard and utility meters work
  out daily kWh from the lifetime totals) – 26 values by default, leaving 6 of the UC100's 32 channels free.
- The UC300 has 32 Modbus channels (Milesight's codec), not 16; the UC50x keeps 16.

## 0.28.0
### Added
- **Send sensor templates to the UC100** (firmware v1 and v2) over LoRaWAN: Modbus channels (slave ID, register,
  type, quantity, signed), channel names and – on v2 – the RS485 port settings, packed into downlinks of at most
  50 bytes. Each channel is tracked in *Command status* and confirmed when the UC100 echoes it. Optional 1-minute
  reporting for 30 minutes so the queued downlinks arrive sooner. Byte format identical to Milesight's encoders.
- Removing a template can also delete its channels on the UC100; applying a template over another one removes the
  old channels the new one does not reuse.
- The UC100 decoders read the device's answers to channel commands instead of stopping at them.

### Changed
- The UC100 has 32 Modbus channels (not 64): the LuxPower template ticks 32 values by default (SOH, grid frequency
  and min cell voltage are optional).

### Note
- The UC300 and UC50x have no Modbus channel downlinks in Milesight's protocol; their channels stay a ToolBox job.

## 0.27.0
### Added
- Sensor template **LuxPower LXP / EG4 hybrid inverter** for the **UC100** (Modbus RTU converter): 46 values in
  groups – PV, Battery (SOC, SOH, charge / discharge power, BMS current, cell voltages and temperatures), Grid
  (voltage, frequency, import / export power), Inverter (output, backup, temperature), Energy today and lifetime
  totals (Energy dashboard ready), fault and warning codes. 35 ticked by default.
- Sensor templates know each controller's channel count: 64 on the UC100, 16 on the UC300 / UC50x.
- 32-bit values in templates (quantity 2, INT32, byte order CDAB in ToolBox) and channel-map options `lo8` / `hi8`
  for values packed into one byte of a register (LuxPower SOC / SOH).
- Channel map device class `battery`.

## 0.26.2
### Changed
- CWT 7-in-1 soil / NPK template follows the tested UC50x setup: address 1, 9600 baud, input registers 0–8, all
  signed, nitrogen / phosphorus / potassium included by default, ToolBox names (Humidity, Temperature,
  Conductivity, PH, Nitrogen, Phosphorus, Potassium, Salinity, TDS).
- The ToolBox list shows each template's register type (Holding / Input Register) and the ToolBox channel name.

### Added
- Sensor template **WoMaster WS101LL liquid level sensor** (RS485): Measure Value as *Water level* (mm), Unit
  Type, Decimal Points, Full Point; Zero Point, Offset and SlaveID optional.

## 0.26.1
### Changed
- Sensor templates: the ToolBox list now has ToolBox's own columns (Channel ID, Name, Slave ID, Address, Quantity,
  Type, Byte order, Signed), WS90 names match ToolBox (Gust speed, Pressure) and the rain counter is included by
  default (10 channels, registers 357–366).
- Device → Configure → *Sensor templates* shows the templates applied to the controller (sensor, channels, slave
  ID) and can **remove** them (their channels leave the channel map). Applying a template on channels another one
  uses replaces that one as a whole.

## 0.26.0
### Added
- **Sensor templates for RS485 / Modbus probes** on UC controllers (device → Configure → *Apply a sensor
  template*): Ecowitt WS90 / WN90LP weather station and CWT THCPH-S / 7-in-1 NPK soil sensor. Pick the values, the
  first channel and the address; the channel map gets named, scaled lines and a confirmation page lists what to
  set in Milesight ToolBox (slave ID, register, data type), with a warning when the probes' baud rates differ.
  Several templates per controller.
- Channel map options column: `s16` / `s32` (signed registers) and `invalid=65535` (no reading → unknown).
- Soil-moisture channels of UC controllers join the irrigation advice.

### Fixed
- The integration's documentation and issue links pointed to a placeholder instead of the GitHub repository.

## 0.25.1
### Fixed
- Device → Configure → *Pump (current clamp)* showed an empty "Error" dialog: the power-factor box was built with
  an empty unit, which Home Assistant rejects.

## 0.25.0
### Added
- **Purpose** per device – what it is fitted to (≈50 purposes: fridge, freezer, pump, air conditioner, compressor,
  motor, geyser, lighting, mains, door, window, gate, garage door, cabinet, tank lid, server room, pipe, silo, bin,
  flood level, rain gauge, toilet, panic button, vehicle, field soil …). Chosen on the commissioning page, *Add a
  device*, the discovery card, the bulk list (6th column) or device → Configure → Purpose; 3-channel clamps per
  channel.
- The purpose sets grouped labels (*Milesight · Cold chain*, *· HVAC*, *· Energy*, *· Security*, *· Water*,
  *· Facilities*, *· Assets & vehicles* …), entity names / device classes / icons (Window, Gate, Compressor …) and
  default limits, editable on an *Alarm limits* page.
- Cold chain: delayed out-of-range alarm, time out of range and excursions per day, 31-day log; compressor duty
  cycle, running too long, not running.
- Loads on clamps and smart sockets: duty cycle, run time, starts, on after hours, service interval; mains outage
  and phase imbalance.
- After-hours activity for doors, gates, cabinets, lids and intrusion motion; geyser / pipe / server-room
  temperature watch; silo hot spots; waste-bin fill and full-in; flood level rising fast; rain gauge (rain today /
  24 h, used by the irrigation advice); soil sensors join the irrigation advice by themselves; toilet visits and
  cleaning due; panic and service-request buttons.
- **Cold chain** and **Energy & HVAC** dashboards, installed when the site has such a device.
- Alert categories *cold chain*, *security*, *energy*, *facilities* (switched on, also for older saved settings).
- Binary sensors now show their attributes (alarm since / peak, button pressed at …).

### Changed
- The *Pump / motor* label is now *Milesight · Pumps & motors*.

## 0.24.0
### Added
- **Pump analytics** for current clamps (device → Configure → Pump): run hours, starts in the last hour / 24 h,
  short-cycling, dry-run (current below normal) and overload (above normal) against a set or learned normal
  current, energy today (counter or estimate), and with a water meter *Pumped today* and *Water per kWh*.
  Event `milesight_lorawan_pump`.
- **Centre-pivot analytics** from an AT101 on the end tower (device → Configure → Centre pivot): arm angle, % of
  the round done, speed, time to finish / finish time, status, and a **stall alarm** when the position stops
  changing during a round (checked every minute). *Pivot stopped (end round)* button. Event
  `milesight_lorawan_pivot`.
- **Forecast-aware irrigation and frost** (gateway → Configure → Irrigation and frost): *Irrigation advice*
  (irrigate / skip with reason and minutes) from the weather forecast and soil moisture, *Rain expected*, *Frost
  tonight* from the afternoon before. Event `milesight_lorawan_frost`.
- The valve schedule blueprint can follow the irrigation advice (skip on rain / moist soil, shorter runs).
- **Farm** dashboard (irrigation & frost, pumps, pivots); installed when the site has a pump, pivot, valve
  controller or irrigation forecast. Tags *Milesight · Pump / motor* and *Milesight · Irrigation*.
- Alert categories *pumps* (dry-run, overload, short-cycling) and *irrigation* (pivot stalled, frost); they start
  switched on, also for alert settings saved with an earlier version.

## 0.23.1
### Changed
- Version bump (same features as 0.23.0) so HACS offers the update.

## 0.23.0
### Added
- **Commissioning mode** for installers: sidebar page *LoRaWAN commissioning* (administrators).
  - Scan a device's QR code with the Companion app's scanner (offline), the phone camera or a photo, or type the
    DevEUI. TR005, JSON, labelled text and bare DevEUI codes are read; DevEUI, AppKey and model are filled in.
    *Add device* creates it in Home Assistant and registers it on the gateway in one step.
  - Live walk test: every uplink of the device with verdict, RSSI, SNR, SF, margin and gateways, beep and
    vibration, the spot you are standing at, *Fast reporting (30 min)* with automatic restore of the normal
    interval, and *Save result* as the device's commissioning record (Signal quality attributes, diagnostics).

## 0.22.2
### Fixed
- Occupancy today / yesterday (per area, per hour) was only kept in memory, so every restart, update or change of
  the gateway's options started the day again with "no data". It is now saved and restored. Hours while Home
  Assistant was not running stay "no data".

## 0.22.1
### Fixed
- *Devices on gateway* stayed "unknown" until *Sync devices with gateway* was pressed: the gateway's device list is
  now read 45 s after start and every 6 hours. The Tanks & alerts card says "not read yet" instead of
  "unknown devices … All registered devices are in Home Assistant".

## 0.22.0
### Added
- Devices are tagged by what they are used for, from their model: Tank / silo, People & occupancy, Air & comfort.
  The tags become Home Assistant labels on the devices (*Milesight · …*), for filtering devices, entities and
  automations.
- Dashboards follow the tags: Tanks & alerts is only in the sidebar when the site has a tank or silo sensor and
  Building analytics only with comfort or occupancy sensors; they appear as soon as such a device is added (and
  leave the sidebar when the last one is removed). LoRaWAN fleet and LoRaWAN signal are always there.

## 0.21.1
### Fixed
- LoRaWAN fleet, LoRaWAN signal and Tanks & alerts dashboards showed "UndefinedError: … has no attribute
  'milesight_role'": the cards now skip sensors without that attribute. The installed dashboards are updated
  automatically after the update (unless you edited them).

## 0.21.0
### Added
- Blueprints and ready-made dashboards now ship inside the integration (HACS only installs the integration
  folder). After every update they are put in place automatically: blueprints in
  `config/blueprints/automation/milesight_lorawan/`, and the LoRaWAN fleet, LoRaWAN signal (installer), Tanks &
  alerts and Building analytics dashboards in the sidebar. Copies edited in Home Assistant are kept. New gateway
  button *Install dashboards and blueprints*; a notification lists what was installed.
- tools/sync_resources.py copies blueprints/ and dashboards/ into the package before a release.

## 0.20.3
### Fixed
- Devices with a payload codec switched on in the Milesight gateway (e.g. AM107 with the gateway's AM107 codec)
  send their decoded values instead of the raw payload; these uplinks were ignored, so the device was never
  discovered. They are now accepted (the model is taken from the gateway's device name).

## 0.20.2
### Changed
- Add a device: the AppKey field is filled in with the gateway's default AppKey; the model list is alphabetical
  (discovery guesses still come first).

## 0.20.1
### Fixed
- Add devices to the gateway: answers from gateway firmware that does not echo the request's `type` / `id` were
  ignored, so the connection test timed out. Any answer on the response topic is now matched to the waiting request.
- The "gateway did not answer" message now says whether nothing arrived on the response topic or what did arrive,
  and every answer is logged at debug level.
- *Sync devices with gateway* only offers devices of the gateway application chosen for Home Assistant (not every
  application on the gateway); *Last seen* uses the gateway's timestamp.
- AppKeys and session keys in the gateway's answers are masked in logs and error messages.


## 0.20.0
### Added
- **Add devices to the gateway** from Home Assistant: gateway → Configure → *Add devices to the gateway* (Milesight
  ns-api request / response topics; the connection is tested and the application and device profile are picked
  from the gateway's lists). Manual and bulk add can register the DevEUI (with an optional AppKey – new 5th column
  in the bulk list) on the gateway. *Devices on gateway* sensor, *Sync devices with gateway* button (devices on the
  gateway but not in Home Assistant are offered under Discovered) and services `add_to_gateway`,
  `remove_from_gateway`, `sync_gateway_devices`.
- **Tanks and silos** for level / distance sensors (Configure → *Tank or silo*): upright / lying cylinder,
  rectangular, cone-bottom silo or any shape → Contents (L), Tank fill, Liquid level, Usage per day, Days until
  empty, Empty around, Last refill, optional Contents weight, Tank low, Sudden drop (theft / leak) with *Clear* and
  *Tank refilled* buttons, `milesight_lorawan_tank` events and service `tank_refilled`. Jumps are confirmed by the
  next reading; slow refills are recognised. Dashboard dashboards/tanks_and_alerts.yaml.
- **Alert escalation** (gateway → Configure → *Alert escalation*): Companion-app notifications with Acknowledge
  (and an optional *Start pump*-style action), escalation to backup people, reminders, quiet hours (critical alerts
  always go through as critical notifications), flapping suppression, resolved messages. *Open alerts* sensor,
  *Acknowledge all alerts* button, service `acknowledge_alert`, event `milesight_lorawan_alert`.
- **Modbus / analog channel map** for UC controllers (Configure → *Channels*): name, unit, scale (or a range like
  `4-20>0-10`), offset, device class, decimals and state class per channel; existing entities keep their history.
- Diagnostics include the last raw payload and fPort of each device (for decoder questions).

### Changed
- Device options are a menu (Device settings / Channels / Tank or silo) for controllers and level sensors; the
  empty distance of level sensors moved to *Tank or silo*. Gateway options menu: Site information, Alert
  escalation, Add devices to the gateway, Gateway connection.

### Fixed
- UC300: Modbus and other readings that follow a reply to a settings command (reporting interval, output control
  …) in the same uplink were dropped.

## 0.19.1
### Fixed
- Example and ready-made dashboards used wrong entity ids (`sensor.milesight_gateway_…`). A gateway added with
  the default topic is called "Milesight gateway (milesight/uplink/#)", so its entities are
  `sensor.milesight_gateway_milesight_uplink_…`. fleet_overview.yaml and signal_quality.yaml now find the gateway
  sensors themselves (no entity ids to edit, works for any gateway name); building_overview.example.yaml uses the
  correct defaults (tools/make_example_dashboard.py).
- Gateway sensors (fleet, building, site, network counters) carry `milesight_role` and `site` attributes so
  dashboards and templates can find them whatever their entity id.

## 0.19.0
### Added
- **Building dashboard**: the gateway's new *Update building dashboard* button (or *Site information* → submit)
  creates a *Building – <site>* dashboard from built-in cards only: company banner, badges, overall health gauge,
  air quality gauges and CO₂ history, system health with *Needs attention*, a section per area and the occupancy
  heat map. Example: dashboards/building_overview.example.yaml.
- **Site information** (gateway → Configure → Site information): uses Home Assistant's name, country, time zone,
  Home zone, areas and a person as facilities contact; adds address, phone, e-mail, logo, area order, outside sensor
  and CO₂ alert level. The gateway options are now a menu (Site information / Gateway connection).
- Gateway sensors: Site, Building health, Building comfort, Air quality, Systems health, People in building, Alerts
  (with the list and start time) and building averages (temperature, humidity, CO₂, PM2.5, PM10, TVOC,
  formaldehyde, pressure – only for measures the site's devices have).

### Fixed
- PM2.5 / PM10 / TVOC (μg/m³) and soil conductivity (μS/cm) now use Home Assistant's unit spelling (Greek μ instead
  of the micro sign µ), which removes the "unit not valid for device class" warnings. Home Assistant may ask once
  (Developer tools → Statistics) to confirm the unit change for these sensors' long-term statistics.

## 0.18.0
### Added
- Command confirmation: every command, setting and display update is tracked (*Command status*: pending /
  retrying / delivered / confirmed / failed / sent) and confirmed by the device's echo, its status report
  (switches, outputs, valves, thermostat target) or the DS3604's update result. Unanswered commands are resent
  after two uplinks (Configure → Retries, default 2); failed switches / outputs fall back to the reported state.
  Optional LoRaWAN confirmed downlinks with network ACKs. `milesight_lorawan_command` event and
  *Command not confirmed* blueprint.
- Signal quality per device: Signal quality (with advice), Spreading factor, Gateway (all gateways in range as an
  attribute), Gateways in range, Packet loss today (from frame-counter gaps); link margin, uplinks today,
  frequency, frame counter (disabled by default). Duplicate frames from several gateways are counted once.
  Installer dashboard dashboards/signal_quality.yaml; the fleet device list includes the signal data.
- DS3604 display content: text entities per block (both templates, QR code), Displayed template select,
  Refresh / Beep / Read display content buttons, Button and Template switch button switches, service
  `milesight_lorawan.display_content` (packs blocks into as few downlinks as fit, skips unchanged blocks) and the
  *DS3604 room sign* blueprint. Encoders checked against Milesight's ds3604-encoder.js (tools/checks/ds3604_enc.py);
  the decoder now reads display content and update results.
- Gateway health: a device per gateway (Online, Packets today / this hour, Devices heard today, Last packet; CPU
  temperature, firmware and WAN / cellular status from Milesight Gateway Information reports; ChirpStack gateway
  stats and connection state), network counters on the gateway entry (Gateways online, Uplinks, Downlinks, Joins,
  ACKs today), gateway offline / online events and blueprint. ACK, join and gateway status topics are set under the
  gateway entry's *Notification / gateway status topics*.
- Join notifications fire `milesight_lorawan_device_joined`.

## 0.17.0
### Added
- Device settings as entities for 89 models: child lock, LED indicator, buzzer switches and alarm thresholds
  (condition select + low / high numbers), generated from Milesight's encoders and checked against them in CI
  (tools/checks/set_g1.py, set_g23.py).
- Stored data (57 models): *Fetch stored data* button, *Data storage* / *Resend missed data* switches,
  *Stored data received* sensor and an option to fetch automatically after an outage. Stored readings are imported into
  long-term statistics for the hours that are missing (tools/checks/hist_*.py).
- Pulse meters: EM300-DI / DI-HALL, UC11xx, UC300, UC50x pulse counters as water / gas / energy meter sensors
  (unit, pulses per unit, starting reading) for the Energy dashboard.
- Building analytics: per-area comfort score and occupancy sensors (hourly heat map, utilisation) on the gateway,
  plus dashboards/building_analytics.yaml.

### Fixed
- dashboards/fleet_overview.yaml: tables rendered on one line (folded YAML block); now literal blocks.

## 0.16.0
### Added
- Bulk onboarding: paste a list of DevEUI, model, name, area (from a spreadsheet) to add many devices at once;
  devices are assigned to Home Assistant areas. Area field on the single-device forms too.
- Fleet overview: gateway sensors for devices total / online / offline / low battery with device lists, plus a
  ready-made dashboard (dashboards/fleet_overview.yaml).
- Per device: Online (connectivity) and Battery low sensors (threshold under Configure), online / offline events.
- Blueprints: device offline, battery low, door left open, leak, alarms, temperature out of range, button actions,
  valve schedule.
- Settings confirmation: Last command sensor (sent / confirmed / no confirmation) and confirmed_by_device attribute
  on interval settings; firmware / hardware version on the device page follow the device's reports.

## 0.15.0
### Added
- Device commands for 112 models: Reboot, Sync time and Request update buttons, Reporting interval and Collection
  interval settings (number entities), generated from Milesight's official encoders (downlinks.json) and checked
  against them in CI (tools/checks/dl_*.py, 1,600+ cases).
- UC controllers: UC300 DO1 / DO2, UC501 / UC502 GPIO outputs and UC511 / UC512 valves as switches, UC521 valve
  opening (0–100 %); GS101 valve and relay; VS373 digital output.
- Services `milesight_lorawan.output_command` (on / off / timed / pulse-count / opening) and
  `milesight_lorawan.send_downlink` (raw hex).
- Downlinks use the fPort from the device's encoder (85 for all current models).

## 0.14.0
### Added
- AM range: AM102 / AM102L, AM103 / AM103L, AM104, AM107, AM304L, AM305L.
- EM range: EM300-CL, EM300-MLD, EM300-DI-HALL, EM310-UDL, EM310-TILT, EM320-TILT, EM320-TH (firmware v1 and v2),
  EM410-RDL, EM411-RDL.
- VS range: VS132, VS133, VS135, VS330, VS350, VS351, VS360.
- DS3604 e-ink display (button events).
- People-counter statistics: people in / out today, yesterday, this / last week, this / last month and people
  inside today; VS133 / VS135 lines and regions appear as they report.
- Extra decoder checks (tools/checks/) against Milesight's official decoders for the new models, run in CI.
### Fixed
- Hardware version minor digit shown in decimal like Milesight's decoders (e.g. v1.10 instead of v1.a).
- EM300-DI water value rounding matches the official decoder on exact ties.

## 0.13.0
### Added
- CTH01 multi-circuit energy meter: current per CT (12), voltage per phase (3), active / reactive / apparent power,
  imported / exported active and reactive energy and apparent energy (per circuit A–D or per CT), power factor,
  current / voltage THD, voltage unbalance, temperature, power-loss alarm and per-channel threshold alarms.
- Entities are created per channel as the meter reports them (unused CTs never appear).
- Crosscheck covers the CTH01 decoder (both official variants, 20,500+ payloads in total).

## 0.12.0
### Added
- WT range: WT101 and WT102 radiator thermostats, WT201 (firmware v1 and v2) and WT211 HVAC thermostats, WT301 /
  WT302 and WT303 / WT304 fan-coil thermostats, WT401 smart thermostat.
- New climate platform: current / target temperature, HVAC mode (heat, cool, heat-cool, dry, fan only, off) and
  fan mode, all settable from Home Assistant via gateway downlinks. All 32 command types are checked against
  Milesight's official encoders.
- Heating and cooling run-time statistics (time and starts per day / week / month), valve opening, window open,
  freeze protection, mode and stage status, fan status, schedules, relays, temperature alarms.
- WT401: occupancy statistics from its presence sensor, F1–F3 keys as event entities.
- Crosscheck covers the WT decoders (20,000+ payloads in total against Milesight's official decoders).
- Supports the renamed thermostat properties of Home Assistant 2026.x as well as older versions.

## 0.11.0
### Added
- WS range: WS101, WS136, WS156 buttons / scene panels; WS201, WS202, WS203, WS301, WS302, WS303 sensors;
  WS501 / WS502 / WS503 wall switches (firmware v1–v3, EU / US, CN and v4); WS513 / WS515 (incl. v3) wall sockets;
  WS523 / WS525 portable sockets; WS558 8-channel light controller.
- **Control:** new switch platform – switches and sockets are switched from Home Assistant via gateway downlinks
  (Milesight gateway or ChirpStack v4 format; new *Downlink MQTT topic* / *Downlink format* gateway settings).
  Commands are checked against Milesight's official encoders.
- New event platform: button presses as event entities, plus a `milesight_lorawan_button` bus event.
- Power metering (power, energy for the Energy dashboard, voltage, current, power factor), socket on-time statistics,
  motion statistics (WS202), door (WS301), leak (WS303) and occupancy (WS203) statistics.
- Discovery picks the model named in the gateway's device name (e.g. "WS301 back door").
- Crosscheck covers the WS decoders and downlinks (18,000+ payloads against Milesight's official decoders / encoders).

## 0.10.0
### Added
- AT range: AT101 GNSS / Wi-Fi asset tracker.
- New device tracker platform: the tracker's position appears on the Home Assistant map and works with zones.
- Moving statistics (moving since, time moving, trips per day / week / month, longest trip) and geofence statistics
  (time outside, exits).
- Distance travelled today / yesterday / this week / last week / this month / last month (GNSS jitter and
  impossible jumps are ignored).
- Tests now check every entity's device class against the list in Home Assistant core.
- Crosscheck covers the AT101 decoder (12,400+ payloads against Milesight's official decoders).

## 0.9.0
### Added
- GS range: GS101 gas detector, GS301 odour detector (NH3 / H2S), GS524N smoke detector, GS601 vape detector.
- Gas / smoke / vaping *detected* binary sensors with statistics (since, duration, today / week / month, events,
  longest), latched until the device reports the all-clear.
- GS101: valve and relay state, remaining sensor life, device fault and end-of-life warning.
- GS301: odour level (Fresh / Noticeable / Strong) from NH3 and H2S.
- GS601: vaping index, PM1 / PM2.5 / PM10, TVOC, burning alarm, interference, tamper, buzzer and occupancy statistics.
- Crosscheck covers the GS decoders (12,200+ payloads against Milesight's official decoders).

## 0.8.0
### Added
- CT range: CT101, CT103, CT105 (1 channel) and CT303, CT305, CT310 (3 channels), firmware v1 and v2.
- Current, cumulative current (Ah), energy (kWh, firmware v2), current alarms (threshold / over range), temperature,
  temperature alarm, low-voltage event and sensor status.
- Load running statistics for CT devices (running since, run time and starts per day / week / month, longest and
  average run), based on the new *Running above (A)* setting.
- Optional estimated power (VA) from the new *Voltage for power estimate (V)* setting.
- Crosscheck covers the CT decoders (11,400+ payloads against Milesight's official decoders).

## 0.7.1
### Changed
- Integration icon is now the Milesight "M" (`brand/icon.png`, `brand/icon@2x.png`).

## 0.7.0
### Added
- EM400 range: EM400-UDL, EM400-TLD, EM400-MUD (distance, temperature, tilt, distance / temperature alarms, battery).
- Fill level % for bins and tanks, calculated from the new *Empty distance (mm)* setting under **Configure**.
- Crosscheck covers the EM400 decoders (9,000+ payloads against Milesight's official decoders).

## 0.6.0
### Added
- UC range: UC11-T1, UC11xx (UC1114 / UC1122 / UC1152), UC11-N1, UC300, UC501, UC502, UC511, UC512, UC521,
  UC100 (firmware v1 and v2).
- Per-channel entities for controllers: digital inputs / outputs, pulse counters, PT100, analog inputs (with
  statistics), Modbus channels (incl. multi-register and 64-bit values on UC100 v2), SDI-12, valves, pipe pressure.
- Entities for configurable controllers are created the first time a channel reports, so unused channels never
  appear as *unknown*.
- Crosscheck covers the UC decoders (now 8,400+ payloads against Milesight's official decoders).
### Fixed
- Floating-point values are rounded exactly like Milesight's decoders (ties away from zero).
### Notes
- UC711 (thermostat controller) is not supported yet.

## 0.5.0
### Added
- TS101, TS201 / TS201 v2, TS301, TS302, TS601, TS602.
- TS301 / TS302 *(older firmware)* models for devices that use the older alarm codes; picked automatically when detectable.
- Alarm binary sensors + alarm status text for all TS models (threshold alarms latch until the device reports the release).
- TS601 / TS602: tilt and light alarms, probe connected, battery low, location and tilt angles (disabled by default).
### Changed
- Alarm binary sensors start as *off* instead of *unknown*.

## 0.4.0
### Added
- EM500-CO2, EM500-LGT, EM500-PP, EM500-PT100, EM500-SMTC, EM500-SWL, EM500-UDL with daily min/max.
- *Sensor status* for probe errors (0xFFFF / 0xFFFD) instead of false readings.

## 0.3.0
### Added
- VS321 (people counting + temperature / humidity), VS340 / VS341 desk occupancy, VS370 radar occupancy.
- VS373 fall detection: fall and other alarms, room / person / breathing status, `milesight_lorawan_alarm` event.
- Presence-only sensors use the same occupancy analytics as the VS121 (without people-specific values).

## 0.2.0
### Added
- AM307, AM308, AM319 HCHO / HCHO-IR / HCHO (Well) / O3 with CO2-limit statistics.
- `tools/crosscheck.py` and CI job comparing decoders with Milesight's official decoders.
### Fixed
- EM300-SLD / EM300-ZLD leak status was read from the wrong channel.
- EM300-DI water meter value.

## 0.1.1
### Added
- Integration icon, *Add device* button, change model under **Configure**.
### Fixed
- Raw payload is always decoded, even when a gateway payload codec is set.

## 0.1.0
- First release: gateway hub with auto-discovery, VS121 occupancy analytics, EM300 door / leak / input statistics.
