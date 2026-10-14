# Changelog

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
