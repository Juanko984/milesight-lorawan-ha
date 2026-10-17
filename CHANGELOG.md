# Changelog

All notable changes to this integration. Versions follow the GitHub releases / HACS updates.

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
