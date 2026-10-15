# Changelog

All notable changes to this integration. Versions follow the GitHub releases / HACS updates.

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
