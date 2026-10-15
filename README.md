# Milesight LoRaWAN for Home Assistant

[![Release](https://img.shields.io/github/v/release/Juanko984/milesight-lorawan-ha?label=version)](https://github.com/Juanko984/milesight-lorawan-ha/releases)
[![HACS](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue.svg)
![Models](https://img.shields.io/badge/supported%20models-45-brightgreen.svg)

**Current version: 0.7.1** · [Version history](#version-history)

Adds Milesight LoRaWAN sensors to Home Assistant **without YAML or Node-RED**.
Connect the gateway once; every new sensor that sends data shows up under
**Settings → Devices & services → Discovered**. Click **Add**, confirm the model, give it a name – done.

## Supported devices at a glance

| Range | Models | Typical use |
|---|---|---|
| **VS** – people counting & occupancy | VS121, VS321, VS340, VS341, VS370, VS373 | Meeting rooms, desks, utilisation, elderly-care fall detection |
| **AM300** – indoor air quality | AM307 / AM307L, AM308 / AM308L, AM319 HCHO / HCHO-IR / HCHO (Well) / O3, AM319L | Offices, classrooms, CO2 / PM / TVOC monitoring |
| **EM300** – environment & contacts | EM300-TH, EM300-MCS, EM300-SLD, EM300-ZLD, EM300-DI | Temperature & humidity, doors / windows, leaks, pulse meters |
| **EM400** – ultrasonic distance & bins | EM400-UDL, EM400-TLD, EM400-MUD | Tank / silo level, waste-bin fill level, distance |
| **EM500** – industrial sensors | EM500-CO2, EM500-LGT, EM500-PP, EM500-PT100, EM500-SMTC, EM500-SWL, EM500-UDL | CO2, light, pipe pressure, probes, soil, water level, distance / tank level |
| **TS** – temperature probes & cold chain | TS101, TS201 / TS201 v2, TS301, TS302, TS601, TS602 | Fridges, freezers, cold rooms, transport |
| **UC** – controllers | UC11-T1, UC11xx, UC11-N1, UC300, UC501, UC502, UC511, UC512, UC521, UC100 (v1 / v2) | Digital / analog I/O, PT100, pulse counting, Modbus RS485, SDI-12, irrigation valves |

Every decoder is checked against Milesight's official decoders ([Milesight-IoT/SensorDecoders](https://github.com/Milesight-IoT/SensorDecoders)) on thousands of payloads before each release.

## What each device gets

All devices also get RSSI, SNR and *Last seen* (diagnostic). Durations update **every minute** (not only when the
sensor reports), and day / week / month totals roll over at local midnight using Home Assistant's time zone.
Statistics are stored by Home Assistant and survive restarts.

### VS range – people counting & occupancy

| Model | What you get |
|---|---|
| **VS121** people counter | People count, occupied (debounced), occupied since / duration, last & longest session, occupied today / yesterday, sessions, peak people + time, person-minutes, average people, utilisation % within opening hours |
| **VS321** occupancy & people counting | Everything the VS121 has, plus temperature, humidity, battery, light (dim / bright) and occupancy per region (10 regions, disabled by default) |
| **VS340 / VS341** desk occupancy | Occupied (debounced), occupied since / duration, last & longest session, occupied today / yesterday, sessions, utilisation %, battery |
| **VS370** radar occupancy | As VS340 plus light (dim / bright) |
| **VS373** radar fall detection | Fall detected, motionless / out-of-bed / dwell / lying-down / abnormal-breathing alarms, last alarm + time, room status, person status, breathing + respiratory rate, room in use now / today, occupancy statistics, per-region occupancy and out-of-bed time (disabled by default) |

### AM300 range – indoor air quality

| Model | What you get |
|---|---|
| **AM307 / AM307L** | Temperature, humidity, feels-like, motion (PIR), light level, CO2, air quality (Good / Moderate / Poor), TVOC, pressure, battery, daily min/max, *CO2 high* alarm and time above the CO2 limit today / yesterday / week / month |
| **AM308 / AM308L** | As AM307 plus PM2.5 and PM10 (+ PM2.5 max today) |
| **AM319 HCHO / HCHO-IR / AM319L HCHO-IR** | As AM308 plus formaldehyde (HCHO) |
| **AM319 HCHO (Well sensor)** | As AM319 HCHO without PM10 |
| **AM319 O3 / AM319L O3** | As AM308 plus ozone |

### EM300 range – environment & contacts

| Model | What you get |
|---|---|
| **EM300-TH** | Temperature, humidity, battery, feels-like, daily min/max |
| **EM300-MCS** door / window | As EM300-TH plus door open / closed, *door left open* alarm, open duration (live), open time & number of openings today / yesterday / this week / last week / this month / last month, longest & average opening |
| **EM300-SLD / EM300-ZLD** leak | As EM300-TH plus leak detected and leak statistics (same periods as door) |
| **EM300-DI** | As EM300-TH plus digital input statistics, pulse counter and converted water value |

### EM400 range – ultrasonic distance & bins

| Model | What you get |
|---|---|
| **EM400-UDL** | Distance (mm) + daily min/max, distance alarm, temperature, tilt alarm, battery; level % (disabled by default) |
| **EM400-TLD** trash bin | As UDL, plus **fill level %** |
| **EM400-MUD** multifunctional | As UDL, plus **fill level %** |

Fill level needs the *empty distance* (sensor to the bottom of the empty bin / tank, in mm): open the device →
**Configure** → *Empty distance (mm)*. 0 % = empty, 100 % = surface at the sensor.

### EM500 range – industrial sensors

| Model | What you get |
|---|---|
| **EM500-CO2** | CO2, air quality, *CO2 high* alarm + time above limit, temperature, humidity, feels-like, pressure, battery, daily min/max |
| **EM500-LGT** | Illuminance (lx) + daily min/max, battery |
| **EM500-PP** | Pipe pressure (kPa) + daily min/max, battery |
| **EM500-PT100** | Temperature + daily min/max, sensor status, battery |
| **EM500-SMTC** | Soil temperature, soil moisture (%), soil conductivity (µS/cm) + daily min/max, sensor status, battery |
| **EM500-SWL** | Water level (cm) + daily min/max, sensor status, battery |
| **EM500-UDL** | Distance (mm) + daily min/max, battery |

### TS range – temperature probes & cold chain

| Model | What you get |
|---|---|
| **TS101** | Temperature + daily min/max, temperature alarm (on / off + type), battery |
| **TS201 / TS201 v2** | As TS101 plus probe status; humidity + humidity alarm for humidity probes (disabled by default) |
| **TS301** / **TS301 (older firmware)** | As TS201 plus contact for magnetic-contact probes (disabled by default) |
| **TS302** / **TS302 (older firmware)** | Two probes: temperature 1 & 2 (+ min/max), alarm per probe, humidity / contact per probe (disabled by default), battery |
| **TS601 / TS602** | Temperature, humidity (+ min/max), temperature / humidity / tilt / light alarms, probe connected, battery low, probe status; location and tilt angles (disabled by default) |

### UC range – controllers

Controllers are configured per site (which inputs are wired, which Modbus registers are read), so their entities are
created **per channel the first time it reports** – unused channels never show up as *unknown*.

| Model | What you get |
|---|---|
| **UC11-T1** | Temperature, humidity (+ min/max), battery |
| **UC11xx** (UC1114 / UC1122 / UC1152 …) | Digital inputs / outputs, pulse counters, analog inputs (+ min / max / avg, disabled by default), Modbus channels |
| **UC11-N1** | GPIO 1 / 2, pulse counter, analog inputs, Modbus channels, battery |
| **UC300** | Digital inputs 1–4, pulse counters, digital outputs 1–2, PT100 1–2, analog current 1–2, analog voltage 1–2 (+ statistics), Modbus channels 1–16 with read-error status |
| **UC501 / UC502** | Digital inputs / outputs, pulse counters, analog inputs 1–2 (+ type and statistics, threshold alarms), SDI-12 readings, Modbus channels with alarms, battery |
| **UC511 / UC512** | Valve 1 / 2 open / closed, valve pulse counts (flow), GPIO 1 / 2, pipe pressure + pressure alarm, battery |
| **UC521** | Valve 1 / 2 opening %, valve type and direction, valve pulses, GPIO, pipe pressure 1 / 2 + alarms, battery |
| **UC100** / **UC100 v2** | Every configured Modbus channel (v2 also register 2–4 of multi-register channels and 64-bit values), alarm status per channel |

Modbus values are shown as the controller reports them (raw register value); set a unit or scaling with a
template sensor if needed. The UC711 thermostat controller is not supported yet.

## Requirements

* Home Assistant 2024.12 or newer with the **MQTT** integration set up.
* A Milesight gateway (UG6x / UG56 / UG65 / UG67 …) using its built-in network server, publishing uplinks to the same MQTT broker.

## 1 – Gateway set-up (once per site)

On the gateway: **Network Server → Applications → (your application) → Data Transmission → MQTT**

* Broker: the MQTT broker Home Assistant uses (e.g. the Mosquitto add-on), with a user/password.
* **Uplink data topic**: e.g. `milesight/uplink/$deveui` (anything works – you enter it in step 2).
* Payload: leave the default JSON with Base64 `data`. No payload codec is needed – the integration decodes.

## 2 – Install the integration (once per site)

**HACS (recommended)**
1. HACS → ⋮ → *Custom repositories* → add `https://github.com/YOUR_GITHUB/milesight-lorawan-ha`, type *Integration*.
2. Install **Milesight LoRaWAN**, restart Home Assistant.

*Manual:* copy `custom_components/milesight_lorawan` into `/config/custom_components/` and restart.

Then **Settings → Devices & services → Add integration → Milesight LoRaWAN** and enter the uplink topic
(wildcards allowed, e.g. `milesight/uplink/#`).

## 3 – Onboard devices (every new sensor)

1. Add the sensor to the gateway as usual (DevEUI, AppKey, OTAA) and power it on.
2. As soon as it sends data, Home Assistant shows **"New LoRaWAN device found"** under *Discovered*.
3. Click **Add**, check the detected model against the device label, enter a name (e.g. *Front door*) → **Submit**.

The device appears with all its entities, already filled with the first reading.
Not appearing? Use **Add integration → Milesight LoRaWAN → Add a device manually** and type the DevEUI.

### VS373 alarms and automations

Every VS373 alarm is also fired as a Home Assistant event, `milesight_lorawan_alarm`, with `device`, `alarm_type`
(`fall`, `motionless`, `out_of_bed`, `dwell`, `lying_down`, `bradynea`, `tachypnea` …), `alarm_status`
(`alarm_triggered`, `alarm_deactivated`, `alarm_ignored`) and `region_id`. Use it as an automation trigger for
instant notifications. Alarm binary sensors stay on until the device reports the alarm deactivated or ignored.

> **Important:** this integration is not a certified safety, medical or emergency-call system. Don't rely on it as
> the only way to detect falls or other emergencies; test notifications at every site.

### TS range alarms

TS sensors raise their own threshold alarms (configured on the device with Milesight ToolBox). The *… alarm* binary
sensor turns on when the device reports an alarm and off when it reports the release; *… alarm status* shows the last
alarm type (e.g. *Below threshold alarm*, *Mutation alarm*). Mutation (rapid change) alarms only update the status.

TS301 and TS302 changed their alarm codes in newer firmware. Discovery picks *current firmware* unless the device
sends an older-firmware message; if alarms look inverted, switch the model to *(older firmware)* under **Configure**.

## Settings per device

Open the device's integration entry → **Configure** (⚙️). Picked the wrong model during onboarding? Change **Model** here; afterwards delete the old, now-unavailable entities from the device page.

| Setting | Devices | Default |
|---|---|---|
| Offline gap (min) – time isn't counted across longer gaps | all | 120 |
| Door left open after (min) | EM300-MCS | 10 |
| CO2 limit (ppm) | AM300 range, EM500-CO2 | 1000 |
| Count as empty after (min at 0 people / vacant) | VS121, VS321, VS340, VS341, VS370, VS373 | 2 |
| Opening hour / closing hour / open days (for utilisation %) | VS-range | 08–17, Mon–Fri |

## Troubleshooting

* **Download diagnostics** on the device page shows the last decoded values and stored statistics – attach it to support requests.
* Debug logging:
  ```yaml
  logger:
    logs:
      custom_components.milesight_lorawan: debug
  ```
* A device stuck sending *JnReq/JnAcc* in the gateway log never gets as far as sending data; fix the join on the gateway first (RX2/channel plan, gateway downlink).

TVOC is reported either as an index or in µg/m³ depending on the device setting. The index sensor is enabled by default; enable *TVOC* (µg/m³) on the device page if your devices report that instead.

EM500 probes report Milesight's error markers (0xFFFF / 0xFFFD) as *Sensor status* ("collection failed" / "out of range") instead of a bogus value. Milesight's own EM500-SMTC decoder misses this for temperature; this integration handles it.

## Icon

The integration ships its own icon in `custom_components/milesight_lorawan/brand/` (used by recent Home Assistant versions).
Older versions only show icons from the [home-assistant/brands](https://github.com/home-assistant/brands) repository –
add `custom_integrations/milesight_lorawan/icon.png` (256×256) and `icon@2x.png` (512×512) there via a pull request.

## Adding support for a new Milesight model

Milesight publishes a decoder for every device in [Milesight-IoT/SensorDecoders](https://github.com/Milesight-IoT/SensorDecoders). Adding a model is:

1. **Decoder** – in `decoders.py`, reuse a family decoder (`decode_em300`, `decode_am300`, …) if the channel map matches, or add a new `decode_xxx()` from the official `*-decoder.js` (only the `channel_id / channel_type` blocks matter; stop on unknown channels).
2. **Model** – add an entry to `MODELS` in `models.py` with the decoder and its *features* (e.g. `env`, `battery`, `co2`, `pm`, `door`).
3. **Entities** – features that already exist get their sensors automatically. For a new measurement add an `EntitySpec` (key = decoded field name, unit, device class).
4. **Auto-detection** – add a rule to `guess_model()` so discovery suggests the right model.
5. **Verify** – add the model to `tools/crosscheck.py` and run it against the official decoder:
   ```bash
   git clone --depth 1 https://github.com/Milesight-IoT/SensorDecoders
   python tools/crosscheck.py SensorDecoders     # must report 0 mismatches
   ```
6. **Release** – bump `version` in `manifest.json`, push, publish a GitHub release. Sites update through HACS.

## Version history

| Version | Changes |
|---|---|
| **0.7.1** | Integration icon changed to the Milesight "M". |
| **0.7.0** | EM400 range added: EM400-UDL, EM400-TLD, EM400-MUD, with fill level % from a configurable empty distance. |
| **0.6.0** | UC range added: UC11-T1, UC11xx, UC11-N1, UC300, UC501, UC502, UC511, UC512, UC521, UC100 (v1 / v2). Controllers get entities per channel as data arrives. |
| **0.5.0** | TS range added: TS101, TS201 / TS201 v2, TS301, TS302 (current and older firmware), TS601, TS602. Alarm states default to *off* instead of *unknown*. |
| **0.4.0** | EM500 range added: EM500-CO2, LGT, PP, PT100, SMTC, SWL, UDL. Probe error markers shown as *Sensor status*. |
| **0.3.0** | VS range added: VS321, VS340, VS341, VS370, VS373 (fall detection, alarm events for automations). |
| **0.2.0** | AM300 range added: AM307, AM308, AM319 variants. **Fix:** EM300-SLD / ZLD leak detection and EM300-DI water meter. Decoders cross-checked against Milesight's official decoders. |
| **0.1.1** | Integration icon, *Add device* button, model can be changed under **Configure**, always decode the raw payload. |
| **0.1.0** | First release: VS121, EM300-TH / MCS / SLD / ZLD / DI, auto-discovery, occupancy and door analytics. |

Full details per release: [CHANGELOG.md](CHANGELOG.md) and the [GitHub releases](https://github.com/Juanko984/milesight-lorawan-ha/releases).

## License

GPL-3.0. The payload decoders are based on Milesight's GPL-3.0 decoders in Milesight-IoT/SensorDecoders.

## Development

```bash
python -m pytest tests/test_pure.py          # decoders + analytics
python tests/test_runtime_stubbed.py         # hub -> device -> entity wiring
python tools/crosscheck.py SensorDecoders    # decoders vs Milesight's official ones
```
GitHub Actions also runs Home Assistant's `hassfest` and the HACS validator on every push.
