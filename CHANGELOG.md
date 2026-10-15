# Changelog

All notable changes to this integration. Versions follow the GitHub releases / HACS updates.

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
