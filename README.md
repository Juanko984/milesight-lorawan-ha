# Milesight LoRaWAN for Home Assistant

[![Release](https://img.shields.io/github/v/release/Juanko984/milesight-lorawan-ha?label=version)](https://github.com/Juanko984/milesight-lorawan-ha/releases)
[![HACS](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue.svg)
![Models](https://img.shields.io/badge/supported%20models-118-brightgreen.svg)

**Current version: 0.39.1** · [Version history](#version-history)

Adds Milesight LoRaWAN sensors to Home Assistant **without YAML or Node-RED**.
Connect the gateway once; every new sensor that sends data shows up under
**Settings → Devices & services → Discovered**. Click **Add**, confirm the model, give it a name – done.

## Supported devices at a glance

| Range | Models | Typical use |
|---|---|---|
| **VS** – people counting & occupancy | VS121, VS132, VS133, VS135, VS321, VS330, VS340, VS341, VS350, VS351, VS360, VS370, VS373 | Meeting rooms, desks, utilisation, elderly-care fall detection |
| **AM** – indoor air quality | AM102 / AM102L, AM103 / AM103L, AM104, AM107, AM304L, AM305L, AM307 / AM307L, AM308 / AM308L, AM319 HCHO / HCHO-IR / HCHO (Well) / O3, AM319L | Offices, classrooms, CO2 / PM / TVOC monitoring |
| **EM300 / EM310 / EM320** – environment, contacts, level & tilt | EM300-TH, EM300-MCS, EM300-SLD, EM300-ZLD, EM300-MLD, EM300-DI, EM300-DI-HALL, EM300-CL, EM310-UDL, EM310-TILT, EM320-TH (v1 / v2), EM320-TILT | Temperature & humidity, doors / windows, leaks, pulse meters |
| **WS** – buttons, sensors, switches & sockets | WS101, WS136, WS156, WS201, WS202, WS203, WS301, WS302, WS303, WS501 / WS502 / WS503 (v1–v3, EU / US, CN, v4), WS513, WS515 (incl. v3), WS523, WS525, WS558 | Scene buttons, washroom refills, motion, doors, noise, leaks, **switching lights and sockets** with energy metering |
| **WT** – thermostats & radiator valves | WT101, WT102, WT201 (v1 / v2), WT211, WT301, WT302, WT303, WT304, WT401 | **Thermostat control from Home Assistant** – radiators, HVAC, fan coils; heating / cooling run time |
| **AT** – asset trackers | AT101 | Vehicles, containers, equipment, bins – position on the map, trips, distance, geofence |
| **CT** – current transformers & energy meter | CT101, CT103, CT105, CT303, CT305, CT310 (firmware v1 / v2), CTH01 | Machine / pump / compressor run time, circuit load, energy (v2); CTH01: 12-circuit sub-metering with power, energy and power quality |
| **GS** – gas, odour, smoke & vape | GS101, GS301, GS524N, GS601 | Gas leaks (with valve / relay), washroom odour, smoke alarms, vape detection in schools & washrooms |
| **EM400 / EM410** – ultrasonic & radar distance, bins | EM400-UDL, EM400-TLD, EM400-MUD, EM410-RDL, EM411-RDL | Tank / silo level, waste-bin fill level, distance |
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
| **VS132 / VS133 / VS135** ToF people counters | People in / out per report, device totals, **people in / out today, yesterday, this / last week, this / last month**, people inside (in − out today); VS133 / VS135 also per line (4) and per region (people, children, dwell times) and lens-blocked alarms |
| **VS350 / VS351 / VS360** passage people counters | As above (in / out statistics), count alarms, temperature (VS350 / VS351), power source (VS351), receiver battery and alignment alarms (VS360) |
| **VS330** bathroom occupancy | Occupancy statistics (occupied since, sessions, utilisation), distance, battery |
| **VS373** radar fall detection | Fall detected, motionless / out-of-bed / dwell / lying-down / abnormal-breathing alarms, last alarm + time, room status, person status, breathing + respiratory rate, room in use now / today, occupancy statistics, per-region occupancy and out-of-bed time (disabled by default) |

### AM range – indoor air quality

| Model | What you get |
|---|---|
| **AM102 / AM102L** | Temperature, humidity, feels-like, daily min / max, battery |
| **AM103 / AM103L** | As AM102 plus CO2 (+ air quality, daily max, time above limit) |
| **AM104** | As AM102 plus illuminance (lx) and motion activity |
| **AM107** | As AM104 plus CO2, TVOC (ppb) and pressure |
| **AM304L / AM305L** | Temperature, humidity, motion + **occupancy statistics**, light level, illuminance, motion count, temperature alarm; AM305L also CO2 + CO2 alarm |
| **AM307 – AM319** | see below |

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

### DS3604 e-ink display

Button presses as an event entity (single / double click, short / long press), current template, battery – and
the screen content from Home Assistant, see [DS3604 display content](#ds3604-display-content).

### WS range – buttons, sensors, wall switches, sockets

| Model | What you get |
|---|---|
| **WS101** smart button | **Event entity** (short / double / long press) for automations, battery |
| **WS136 / WS156** scene panels | One event entity per button (WS156: short / double / long press, WS136: press), battery |
| **WS201** fill level monitor | Remaining % (tissue, soap, paper towels), distance, battery |
| **WS202** PIR & light | **Motion** with statistics (motion now / since, time and events per day / week / month), light (dim / bright), battery |
| **WS203** motion & T/H | **Occupancy statistics** (presence), temperature, humidity, feels-like, daily min/max, temperature alarm, battery |
| **WS301** door / window | **Door statistics** (as EM300-MCS: open now / since, left open, open time and count per period), tamper, battery |
| **WS302** sound level | Sound level (dB, with frequency / time weighting e.g. LAF) + daily min/max, Leq + daily max, period max, battery |
| **WS303** leak | **Leak** with statistics, battery |
| **WS501 / WS502 / WS503** wall switches | **Switch entities per gang – control from Home Assistant**; EU / US and v4 also power (W) + daily max, energy (kWh, Energy dashboard), voltage, current, power factor; v4 overcurrent, overtemperature and device fault alarms |
| **WS513 / WS515** wall sockets | **Socket switch** (control), power, energy, voltage, current, power factor, temperature (+ alarms on v3), on-time statistics |
| **WS523 / WS525** portable sockets | **Socket switch** (control), power, energy, voltage, current, power factor, on-time statistics |
| **WS558** light controller | **8 switch entities** (control), power, energy, voltage, total current, power factor |

Button presses also fire a `milesight_lorawan_button` event (`deveui`, `device`, `model`, `button`, `event_type`).

**Switching:** turning a switch on/off sends a downlink (fPort 85) through the gateway – set the gateway's downlink
topic (see step 1). The switch shows the new state immediately and the device confirms it with its next uplink.
Class A devices only receive the command after their next uplink; WS switches and sockets are Class C, so commands
are applied straight away. Firmware variants (v1–v3, EU/US, CN, v4, v3 sockets) use different commands – pick the
matching model (the device label / gateway firmware info tells you; the integration suggests one).

Tip: include the model in the device name on the gateway (e.g. *WS301 back door*) and discovery picks that model
automatically – handy for devices whose messages look alike (WS301 / WS202 / VS370, WS303 / VS340 …).

### WT range – thermostats & radiator valves

Every WT device gets a **thermostat (climate) entity**: current temperature, target temperature, mode and fan mode –
all **settable from Home Assistant** (dashboard thermostat card, automations, voice assistants).

| Model | Modes you can set | What else you get |
|---|---|---|
| **WT101 / WT102** radiator valves | Heat / Off, target (WT101 in whole °C) | Valve opening %, window open, freeze protection, removed from radiator, motor calibration; WT102 also battery low, mandatory heating, auto away, temperature alarm; **heating time and starts** per day / week / month |
| **WT201 (v1 / v2) / WT211** HVAC thermostats | Heat, Cool, Heat/Cool (auto), Off; fan auto / on / circulate | Humidity, mode and stage status (e.g. *stage-2 heat*), fan status, schedule, active relays, temperature alarm, **heating and cooling run time** |
| **WT301 / WT302** fan-coil thermostats | Heat, Cool, Fan only, Off; fan auto / low / medium / high | Key card inserted, button lock, control mode |
| **WT303 / WT304** fan-coil thermostats | Heat, Cool, Fan only, Off; fan auto / low / medium / high | Humidity, heating / cooling targets, valve, fan status, relays, schedule, temperature alarm, heating and cooling run time |
| **WT401** smart thermostat | Heat, Cool, Heat/Cool, Dry, Fan only, Off; six fan modes | Humidity, presence + **occupancy statistics**, schedule, F1–F3 keys as event entities, battery |

Thermostat commands are sent as downlinks (fPort 85) like the WS switches – set the gateway's downlink topic (step 1).
The new value shows straight away; battery-powered radiator valves (Class A) apply it after their next uplink.
WT201 firmware v1 and v2 use different commands – pick *WT201 (firmware v1)* if your thermostat is the older one.

### AT range – asset trackers

| Model | What you get |
|---|---|
| **AT101** GNSS / Wi-Fi tracker | **Map position** (device tracker – shows on the HA map and works with zones), motion (start / moving / stop), **moving statistics** (moving since, time moving and number of trips today / week / month, longest trip), **distance travelled** today / yesterday / this & last week / this & last month, **geofence** (time outside and exits per period), temperature + daily min/max, temperature alarm, tilt, removed from mount, battery |

Distance is the straight-line sum between GNSS fixes, so it is a lower bound of the real route (more frequent
reporting = closer to the real distance). Moves under 50 m are treated as GNSS jitter.
Wi-Fi-only fixes contain access-point MACs, not coordinates – they do not move the map position (the Wi-Fi scan
details are available as diagnostic entities).

### CT range – smart current transformers

| Model | What you get |
|---|---|
| **CT101 / CT103 / CT105** (1 channel) | Current (A) + daily min/max, cumulative current (Ah), current alarm (threshold / over range), temperature, sensor status; **energy (kWh)** on firmware v2 |
| **CT303 / CT305 / CT310** (3 channels) | The same per channel (Current 1–3), plus combined current of all channels |
| All CT models | **Load running** with run-time statistics: running now / since, run time today, yesterday, this / last week, this / last month, starts per period, longest and average run; optional **estimated power (VA)** |

| **CTH01** multi-circuit energy meter | 12 CT inputs (4 circuits A–D of 3 CTs) and 3 voltage phases: current per CT, voltage per phase, **active / reactive / apparent power** and **energy imported / exported** (per circuit or per CT, as configured on the meter – kWh sensors work in the Energy dashboard), power factor, current and voltage THD (disabled by default), voltage unbalance, temperature, power-loss alarm, threshold alarms per channel |

CTH01 entities are created as the meter reports each value, so only the CTs and circuits you have wired and
configured appear. Circuit totals are named *circuit A–D*, single CTs *CT 1–12* (circuit A = CT 1–3, B = CT 4–6,
C = CT 7–9, D = CT 10–12). Readings the meter flags as errors are skipped and listed in *Sensor status*.

*Running* means the current (on any channel) is at or above **Running above (A)** (default 0.5 A) – set it under
**Configure** to just above the idle current of the machine. For *Estimated power*, enter the phase voltage
(e.g. 230 V) under **Configure**; the power sensors are disabled by default – enable them on the device page.
The energy sensors (v2) work directly in the Home Assistant **Energy dashboard**.

### GS range – gas, odour, smoke & vape detectors

| Model | What you get |
|---|---|
| **GS101** gas detector | **Gas detected** with statistics (since, duration, today / week / month, events), valve and relay output state, remaining sensor life (days), device fault, end-of-life warning, last device event |
| **GS301** odour detector | Ammonia (NH3) and hydrogen sulfide (H2S) in ppm with daily min/max, **odour level** (Fresh / Noticeable / Strong), temperature, humidity, feels-like, battery, sensor status (e.g. *polarizing* after power-up) |
| **GS524N** smoke detector | **Smoke detected** with statistics, last event (alarm, silenced, test, removed …), smoke concentration, temperature, battery and battery low, removed from base, device fault |
| **GS601** vape detector | **Vaping detected** with statistics, vaping index + daily max, PM1 / PM2.5 / PM10, TVOC, temperature, humidity, burning / fire alarm, sensor interference, tamper, buzzer, **occupancy statistics** (presence), alarms per measurement (disabled by default) |

Gas, smoke and vape alarms stay on until the device reports the all-clear, and each has the same statistics as the
door sensors (detected since, duration, today / yesterday / week / month, number of events, longest).
The odour level is a rough guide (Strong from 5 ppm NH3 or 0.1 ppm H2S, Noticeable from 1 ppm NH3 or 0.02 ppm H2S).

### EM300 / EM310 / EM320 additions

| Model | What you get |
|---|---|
| **EM300-MLD** membrane leak | Leak with statistics (as EM300-SLD), battery |
| **EM300-DI-HALL** pulse counter | As EM300-DI |
| **EM300-CL** capacitive level | Liquid level (full / critical / uncalibrated), critical-level alarm, calibration result |
| **EM310-UDL** ultrasonic distance | Distance + daily min / max, tilted |
| **EM310-TILT / EM320-TILT** | Angle X / Y / Z, per-axis threshold alarms, tilted |
| **EM320-TH** (v1 / v2) | Temperature, humidity, feels-like, daily min / max; v2 also temperature / humidity alarms |

### EM400 range – ultrasonic distance & bins

| Model | What you get |
|---|---|
| **EM400-UDL** | Distance (mm) + daily min/max, distance alarm, temperature, tilt alarm, battery; level % (disabled by default) |
| **EM400-TLD** trash bin | As UDL, plus **fill level %** |
| **EM400-MUD** multifunctional | As UDL, plus **fill level %** |

**EM410-RDL / EM411-RDL** radar sensors get the same entities as the EM400-UDL plus radar signal strength,
distance change and blind-spot / no-target alarms.

Fill level needs the *empty distance* (sensor to the bottom of the empty bin / tank, in mm): open the device →
**Configure** (→ *Tank or silo* for the level sensors). 0 % = empty, 100 % = surface at the sensor.
For tanks and silos see [Tanks and silos](#tanks-and-silos) – litres, usage per day, days until empty, refills and
theft alarms.

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

Modbus values arrive as the controller reports them (raw register value). Give them a name, unit and scale under
**Configure → Channels** – see [Modbus and analog channels](#modbus-and-analog-channels). The UC711 thermostat
controller is not supported yet.

## Requirements

* Home Assistant 2024.12 or newer with the **MQTT** integration set up.
* A Milesight gateway (UG6x / UG56 / UG65 / UG67 …) using its built-in network server, publishing uplinks to the same MQTT broker.

## 1 – Gateway set-up (once per site)

On the gateway: **Network Server → Applications → (your application) → Data Transmission → MQTT**

* Broker: the MQTT broker Home Assistant uses (e.g. the Mosquitto add-on), with a user/password.
* **Uplink data topic**: e.g. `milesight/uplink/$deveui` (anything works – you enter it in step 2).
* Payload: leave the default JSON with Base64 `data`. No payload codec is needed – the integration decodes.
* **Downlink data topic** (needed for any command from Home Assistant): e.g.
  `milesight/downlink/$deveui`. In the integration's gateway settings the same topic is written as
  `milesight/downlink/{deveui}` (the default).
* Optional, for [command confirmation](#command-confirmation) and [gateway health](#gateway-health):
  **ACK Notification** → `milesight/ack`, **Join Notification** → `milesight/join`, and – on gateways that have it
  (UG63, SG50) – **Gateway Information** → `milesight/gateway`. Enter these under the integration's gateway
  settings as *Notification / gateway status topics*: `milesight/ack, milesight/join, milesight/gateway`.

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

## Rolling out to a site

### Bulk onboarding

Add the gateway first, then **Add device → Add many devices (paste a list)** and paste one device per line –
straight from a spreadsheet (comma, semicolon or tab separated):

```
DevEUI, Model, Name, Area, AppKey, Purpose
24E124136B322135, EM300-MCS, Back door, Warehouse, , door
24E124538C220481, AM307, Meeting room 1, 1st floor, , meeting_room
24E124600B251990, VS121, Reception, Ground floor, 00112233445566778899aabbccddeeff
24E124136B322199, TS301, Cold room 2, Kitchen, , fridge
```

The *Purpose* column takes a key or label from [the purpose list](#purposes--what-a-device-is-fitted-to).

With [gateway provisioning](#add-devices-to-the-gateway-from-home-assistant) set up, tick *Also add them to the
gateway* and every DevEUI is registered on the gateway's network server too (AppKey column optional – empty uses the
gateway setting, the Milesight factory key by default).

Model names are matched loosely (`em300 mcs`, `WS501 v4`). Every device is created straight away – no confirm
dialogs – and placed in its **area** (created if it doesn't exist). Devices that already exist are skipped and
mistakes are listed line by line. The single-device forms (manual and discovered) also have an *Area* field.

### Fleet overview

The gateway device gets four sensors: **Devices**, **Devices online**, **Devices offline** and **Devices with low
battery**. Their attributes list the devices (name, model, area, battery, RSSI / SNR, last seen).
They feed the **Maintenance** dashboard ([`dashboards/maintenance.yaml`](dashboards/maintenance.yaml)): tabs
*Overview*, *Devices* (every device with battery, signal, network server, firmware and last seen), *Signal* and
*Map*.

Every device also has an **Online** sensor (off after the *Offline gap*, default 120 min, without an uplink)
and – for battery devices – a **Battery low** sensor (threshold per device under **Configure**, default 20 %).
Going offline / online also fires `milesight_lorawan_device_offline` / `milesight_lorawan_device_online` events.

### Blueprints and dashboards are installed for you

HACS only installs the integration folder, so the blueprints and ready-made dashboards ship *inside* the
integration and it puts them in place itself:

* **After every update** (first start of a new version) the blueprints are copied to
  `config/blueprints/automation/milesight_lorawan/` and the dashboards appear in the sidebar: **Maintenance**
  (tabs Overview, Devices, Signal, Map), **Tanks & alerts**, **Building analytics**, **Farm**, **Cold storage** and
  **Energy & HVAC** (each only when the site
  needs it, see below). A notification lists what changed.
* **Only what the site needs**: every device is tagged by what it is used for, from its model – *Tank / silo*
  (EM400-UDL / -MUD, EM410 / EM411-RDL, EM310-UDL, EM500-UDL, EM500-SWL), *People & occupancy* (VS range, people
  counters, desk sensors) and *Air & comfort* (temperature + humidity or CO₂ sensors). Maintenance is always
  there; **Tanks & alerts** appears when the first tank / silo sensor is added and
  **Building analytics** with the first comfort or occupancy sensor, **Farm** with the first pump, pivot, valve
  controller or the gateway's irrigation forecast, **Cold chain** with the first fridge / freezer and **Energy &
  HVAC** with the first air conditioner, lighting circuit, geyser or mains clamp (see [Purposes](#purposes--what-a-device-is-fitted-to)). *Pump / motor* and *Irrigation* also follow a device's options
  (a clamp set up as a pump, a tracker set up on a pivot). Remove the last one and the dashboard leaves
  the sidebar again (its content is kept for later).
* The tags are also Home Assistant **labels** on the devices (*Milesight · Tank / silo*, *Milesight · People &
  occupancy*, *Milesight · Air & comfort*), so you can filter devices, entities and automations by them. A label
  you remove by hand is not added back.
* **Any time**: the gateway's **Install dashboards and blueprints** button.
* Blueprints or dashboards you edited in Home Assistant are **kept** (the notification says so). To get ours back,
  delete your copy and press the button.
* The site landing page (below) is generated per gateway and links to these dashboards.

Developers: the files are edited in `blueprints/` and `dashboards/` and copied into the package with
`python3 tools/sync_resources.py` (a test fails if they differ).

### Blueprints

Installed automatically (above), or import one by one:

| Blueprint | Use |
|---|---|
| [Device offline / back online](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/device_offline.yaml) | Notify when any device stops reporting |
| [Battery low](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/battery_low.yaml) | Notify when a battery drops below the per-device threshold |
| [Door left open](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/door_left_open.yaml) | Pick the *Door left open* sensors (EM300-MCS, WS301) |
| [Leak detected](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/leak.yaml) | Leak sensors – e.g. notify and close a valve |
| [Gas, smoke, vape or other alarm](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/alarm.yaml) | Any Milesight alarm sensor (GS range, CO2 high, threshold alarms) |
| [Temperature out of range](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/temperature_out_of_range.yaml) | Fridges, freezers, server rooms – low / high limit for N minutes |
| [Button actions](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/button_actions.yaml) | Short / double / long press → actions (WS101, WS156, WS136, DS3604, WT401) |
| [Irrigation / valve schedule](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/valve_schedule.yaml) | Open a UC511 / UC512 / UC521 valve or UC300 output at set times for a duration |
| [Command not confirmed](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/command_failed.yaml) | Notify when a command / setting fails after its retries |
| [Gateway offline / back online](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/gateway_offline.yaml) | Notify when a gateway stops forwarding packets |
| [DS3604 room sign](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https://github.com/Juanko984/milesight-lorawan-ha/blob/main/blueprints/automation/milesight_lorawan/ds3604_room_status.yaml) | Room name, free / occupied, current or next meeting and booking QR code on a DS3604 |

Each one has an editable action list (notification by default) – point it at your phone, Telegram, e-mail etc.

### Settings confirmation

After a setting is sent (e.g. *Reporting interval*), the device's **Last command** sensor shows *sent*, and
*confirmed* once the device echoes the new value (most Milesight devices do on their next uplink); the interval
entity's `confirmed_by_device` attribute shows the same. Firmware and hardware versions on the device page update
whenever the device reports them.

### Site landing page

A ready-made landing page for each site (sidebar: the site's name), built from Home Assistant's own cards only
(no HACS):
* a **banner** with the site name, company, address, facilities contact and logo, and an *all normal* / *needs
  attention* strip;
* **buttons to the other dashboards** in the sidebar (Farm, Tanks & alerts, Building analytics, Cold chain …);
* overall health gauge, **open alerts** and *Needs attention*, air quality gauges, system health;
* **People**: in the building now, people per area and a compact occupancy heat map (one row of squares per area,
  fits a phone);
* a section per area, then **tanks** (fill gauges), **irrigation** (forecast, advice, soil), the **pivot map**,
  **pumps**, **cold chain** and **energy** for the devices that are set up.

It is created and refreshed **by itself** (at start-up and when devices change) once the gateway's sensors exist.
If you edit it in Home Assistant, it is left alone; the gateway's **Update site dashboard** button regenerates
it.

1. Gateway entry → **Configure** → **Site information**. Home Assistant already provides the **company name**
   (Settings → System → General → Name), country, time zone, the Home zone, the **areas** (Settings → Areas) and the
   **facilities contact** (a person from Settings → People). Fill in only what Home Assistant does not know:
   address, phone, e-mail, logo, which areas to show and in what order, an optional outside temperature sensor,
   and the CO₂ alert level (default 1,200 ppm). *Company name* overrides the Home Assistant name when they differ;
   the site name is the gateway entry's name.
2. Submit. The landing page appears in the sidebar under the site's name (URL `/building-<site>`). The banner,
   badges, gauges, heat map and alerts update by themselves.

Logo: copy the file into the `www` folder of your configuration (File editor / Samba add-on) and enter
`/local/<file name>` (default `/local/logo.png`).

The gateway device gets the sensors behind it, also usable in your own dashboards and automations:

| Sensor | |
|---|---|
| **Site** | Company name; attributes: site, address, contact (+ picture), phone, e-mail, logo, country, time zone, areas, status |
| **Building health** | 0–100: 40 % comfort, 40 % air quality, 20 % systems (devices online with good batteries, gateways online) |
| **Building comfort** | Average area comfort; comfortable areas as an attribute |
| **Air quality** | Good / Moderate / Poor / Unhealthy – the worst of CO₂, PM2.5, PM10, TVOC, formaldehyde; score as an attribute |
| **Systems health**, **People in building**, **Alerts** | Alerts lists what needs attention (high CO₂ / humidity / temperature per area, offline devices and gateways, low batteries, failed commands) with the time it started |
| **Average temperature / humidity / CO₂ / PM2.5 / PM10 / TVOC / formaldehyde / pressure** | Over online devices – only measures your devices have (TVOC only from devices reporting µg/m³) |

The dashboard is saved like any dashboard edited in the UI, so it can be changed afterwards – but pressing
*Update site dashboard* again replaces it. To keep your own changes, copy it (⋮ → Edit → ⋮ → Raw
configuration editor) into a dashboard of your own. If Home Assistant refuses the direct save, the YAML is written
to `/config/milesight_building-<site>.yaml` with a notification on how to paste it.
[`dashboards/building_overview.example.yaml`](dashboards/building_overview.example.yaml) shows what is generated.

**Entity ids** of the gateway's sensors follow the gateway entry's name: with the default topic it is
"Milesight gateway (milesight/uplink/#)", so e.g. `sensor.milesight_gateway_milesight_uplink_building_health`.
The generated dashboard and the ready-made dashboards look the sensors up themselves; in your own templates
you can do the same with the `milesight_role` attribute, e.g.
`{{ states.sensor | selectattr('attributes.milesight_role', 'eq', 'building_health') | map(attribute='state') | first }}`.

### Building analytics

Give devices an area (bulk onboarding, the onboarding form, or the device page) and the gateway device gets, per area:

* **&lt;Area&gt; comfort** (0–100): temperature 20–24 °C, humidity 30–60 % and CO2 up to 800 ppm count as fully
  comfortable, falling to 0 at 15 / 29 °C, 15 / 80 % and 1800 ppm. Attributes: average temperature, humidity, CO2.
* **&lt;Area&gt; occupancy**: share of today the area was occupied (people counters, PIR / desk sensors, VS range,
  GS601), with `occupied_now`, `people_now`, `utilisation_today` (within opening hours) and an hourly heat map
  (`hourly_today`, `hourly_yesterday` – % of each hour occupied).

Dashboard: [`dashboards/building_analytics.yaml`](dashboards/building_analytics.yaml) – comfort table, occupancy
heat map for today and yesterday, utilisation per area. No entity ids to edit.

## Device settings as entities

Settings from Milesight's encoders appear on the device page under **Configuration** (89 models), generated from and
checked against the official encoders in CI (`tools/checks/set_*.py`, 1,100+ cases):

* **Switches**: child lock, LED indicator, buzzer (where the device has them).
* **Alarm thresholds**: a *condition* select (disable / below / above / between / outside) plus *low* / *high*
  numbers – temperature, humidity, CO2, PM2.5, TVOC, current, distance, illuminance, pressure, people counts, …

Changing one sends the whole setting to the device on its next receive window. Devices don't report most of these
back, so the entities show the last value sent (*assumed state*); **Last command** shows whether it was confirmed.

## Stored data / backfill (57 models)

Most Milesight sensors store readings while the gateway or network is down. Devices that support it get:

* **Fetch stored data (24 h)** button – asks the device to resend the last 24 h of stored readings.
* **Data storage** and **Resend missed data** switches (the device's own data-storage settings).
* **Stored data received** sensor – when stored readings were last imported and how many.
* Option **Fetch stored data after an outage** (Configure, on by default) – fetches automatically when a device comes back after a
  gap longer than the *Offline gap*.

Stored readings are written to Home Assistant's **long-term statistics** for the matching sensors (hourly mean / min /
max), filling only hours that have no statistics yet – the gap disappears from history graphs and statistics cards.
The live state history is not rewritten.

## Pulse counters → water / gas / energy meters

For EM300-DI, EM300-DI-HALL, UC11xx, UC300 and UC50x, open **Configure** and choose a **Pulse meter type** (water,
gas or electricity), the **unit**, **pulses per unit** and the **meter reading at start** (the number on the physical
meter). The device gets a *Water / Gas / Energy meter* sensor (`total_increasing`) that you can add under
**Settings → Dashboards → Energy** (water consumption, gas consumption, or grid consumption).
Example: a 1 pulse = 0.5 L water meter showing 1 000 L → pulses per unit 2, unit L, reading at start 1000.

## Device commands (downlinks)

With the gateway's downlink topic set (see step 1), each device page also gets – where the device supports it:

| Entity | What it does |
|---|---|
| **Reboot** button | Restarts the device |
| **Sync time** button | Synchronises the device clock (or sends Home Assistant's time where the device has no sync command) |
| **Request update** button | Asks the device to report now |
| **Reporting interval** / **Collection interval** (Configuration) | Sets how often the device reports / measures – unit (s or min) and allowed range per model |
| **Output / valve switches** | UC300 DO1 / DO2, UC501 / UC502 GPIO outputs, UC511 / UC512 valves, GS101 valve & relay, VS373 digital output |
| **Valve opening** number | UC521 motorised valves (0–100 %) |

All commands were generated from and checked against Milesight's official encoders (1,600+ cases).
The interval fields show the last value set from Home Assistant (devices don't report their interval).
Battery-powered (Class A) devices receive commands after their next uplink.

Two services are available for automations and scripts:

* `milesight_lorawan.output_command` – `output` (e.g. `gpio_output_1`, `valve_1`, `valve_1_opening`), `action`
  (`on`, `off`, `on_for` / `off_for` – UC300, value in ms –, `open_for` – UC511 / UC512 seconds, UC521 minutes –,
  `open_until_pulses`, `set`), `value`. Example: open a UC511 valve for 10 minutes:
  ```yaml
  action: milesight_lorawan.output_command
  data:
    device_id: <your device>
    output: valve_1
    action: open_for
    value: 600
  ```
* `milesight_lorawan.send_downlink` – send any raw command in hex (advanced; see Milesight's device user guide), e.g.
  `ff10ff` = reboot.

UC11xx / UC11-N1 / UC11-T1: Milesight publishes no downlink encoder for these, so their outputs stay read-only (use
`send_downlink` with the commands from the user guide if needed).

## Command confirmation

Every command, setting and display update is tracked until the device answers it. The **Command status** sensor
(diagnostic) shows the latest one:

| Status | Meaning |
|---|---|
| *pending* | Sent to the gateway, waiting for the device (Class A devices pick it up after their next uplink) |
| *retrying* | No answer after two uplinks – sent again (default 2 retries, **Configure → Retries**) |
| *delivered* | Confirmed downlink acknowledged by the device's radio, waiting for its status report |
| *confirmed* | The device echoed the setting, its status report shows the new state (switches, outputs, valves, thermostat target), the DS3604 reported the block updated, or – for commands nothing else can check – the network ACK arrived |
| *failed* | No answer after all retries, or rejected by the device (e.g. DS3604 *content is too long*). Switches and outputs fall back to the last reported state |
| *sent* | The device does not answer this kind of command and confirmed downlinks are off – nothing to check |

The integration learns per device whether it echoes settings (most current Milesight firmware does; older EM300
firmware does not), so devices that never answer are not retried pointlessly. **Configure → Confirmed downlinks**
asks for a LoRaWAN ACK on every command (needs the gateway's ACK notification topic, step 1). Each final state also
fires a `milesight_lorawan_command` event (`command`, `status`, `attempts`, `detail`) – the
[Command not confirmed](#blueprints) blueprint notifies on failures.

## Signal quality

Every device gets diagnostic sensors that help installers place sensors and gateways:

| Sensor | |
|---|---|
| **Signal quality** | excellent / good / fair / poor from the *link margin* (SNR above what the spreading factor needs) and RSSI. Attribute `advice` says what to do, e.g. "Weak link: move the sensor … or add a gateway" |
| **RSSI**, **SNR** | Best gateway; kept in the history / long-term statistics |
| **Spreading factor** | SF7 – SF12 (higher = slower, more battery) |
| **Gateway** | The gateway that heard it best; attribute `gateways` lists every gateway in range with RSSI / SNR |
| **Gateways in range** | How many gateways heard it in the last 24 h |
| **Packet loss today** | From gaps in the frame counter (a rejoin is not counted); yesterday's value as an attribute |
| *Link margin*, *Uplinks today*, *Frequency*, *Frame counter* | Disabled by default |

The same frame forwarded by two gateways is counted once. For installers: the
Maintenance dashboard's *Signal* tab – gateways and weak / lossy devices.

## DS3604 display content

The DS3604 shows two templates designed in Milesight ToolBox, each with up to 10 text blocks and a QR code.
Home Assistant fills the blocks:

* **Template 1 text 1 – 3** text entities on the device page (all other blocks and template 2 can be enabled) –
  type a value and it is sent. The entity shows what the display reports, or what was last sent.
* **Displayed template** select, **Refresh display**, **Beep** and **Read display content** buttons.
* Service `milesight_lorawan.display_content` for automations (templates allowed):
  ```yaml
  action: milesight_lorawan.display_content
  data:
    device_id: <your display(s)>
    template: 1
    content:
      text_1: Meeting room 1
      text_2: "{{ 'Occupied' if is_state('binary_sensor.room_1_occupancy', 'on') else 'Free' }}"
      text_3: "Next: {{ state_attr('calendar.room_1', 'message') }}"
      qrcode: https://example.com/book/room-1
  ```
  Unchanged blocks are skipped (saves battery and airtime; `force: true` sends them anyway). Blocks are packed
  into as few downlinks as fit – at most 51 bytes each by default, which works at every EU868 data rate
  (**Configure → Max bytes per display downlink**; up to 222 near a gateway, 11 for US915 SF10).
* Blueprint [DS3604 room sign](#blueprints): room name, free / occupied from a sensor or the calendar, the
  current or next meeting, booking QR code.

Each block update is confirmed by the display itself (*Command status*); a rejected block shows in
**Display error** (e.g. "text_3: content is too long" – the text does not fit the block in the template).

## Gateway health

Each LoRaWAN gateway that forwards packets appears as its own device (linked to the gateway entry), with:

* **Online** – off when the gateway has forwarded nothing for *Gateway offline after* minutes (default 15,
  gateway settings) – or, with status reports, when it reports itself offline. Fires
  `milesight_lorawan_gateway_offline` / `_online` events ([blueprint](#blueprints)).
* **Packets today**, **Packets this hour** (attribute: last 24 hours), **Devices heard today** (with names),
  **Last packet**.
* With status reports: **CPU temperature**, firmware / model on the device page, WAN / cellular status as
  attributes (Milesight *Gateway Information*, UG63 / SG50), **Radio packets received / sent today** (ChirpStack
  gateway stats, topic `gateway/+/event/stats` with the JSON marshaler, and connection state
  `gateway/+/state/conn`).

The gateway entry itself gets **Gateways online**, **Uplinks today** (duplicates / errors as attributes),
**Downlinks today**, **Joins today** and **Downlink ACKs today**.

UG65 / UG56 / UG67 do not publish their own status over MQTT; for them everything is derived from the packets
they forward, which is reliable as long as some devices report more often than the offline time. (Their HTTP API
needs a password copied from the browser's developer tools, so it is not used.)

## Built-in network server

Home Assistant can be the LoRaWAN network server itself. Gateways send their **packet forwarder** traffic to
Home Assistant; devices join Home Assistant with their AppKey. No device list on the gateway, and **any gateway
that forwards to Home Assistant carries any of your devices** – the basis for a shared farm network.

```
gateway A ─┐  Semtech UDP 1700    ┌─ joins, keys, frame counters, duplicates from several gateways
gateway B ─┼────────────────────> │  built-in network server ──> decoders, entities, dashboards, alerts
gateway C ─┘   <── downlinks ──── └─ commands sent through the gateway that heard the device best
```

**Set up**

1. Gateway entry → **Configure** → **Built-in network server**: tick *Enable*, keep port **1700**, frequency
   plan **EU868**, receive delay **3 s**, and a site number (0–511, unique per site in a community network).
2. On each gateway (UG65 / UG67 / UG56 …): **Packet Forwarder → General → Multi-Destination → +** → Type
   **Semtech**, Server Address = Home Assistant's IP address, Port Up **1700**, Port Down **1700**, Enable.
   Keep the *Embedded NS* row: devices registered on the gateway keep working there.
3. Add a device: power it on (or press its reset). It appears under **Settings → Devices & services →
   Discovered** as *wants to join*: choose the model, a name and enter its **AppKey** (Milesight's default key is
   filled in). It joins on its next attempt. Or add it by hand (*Add device* with the AppKey field).
4. To move a device from the gateway's network server: open it → **Configure → Network server keys**, enter its
   AppKey, delete it from the gateway's device list, and power-cycle it.

**Rules**

* A device must be on **one** network server only – the gateway's Embedded NS *or* Home Assistant.
* Home Assistant must be reachable from the gateways on UDP 1700 (Home Assistant OS listens on the host;
  in Docker, publish `1700/udp`). Over the internet use a VPN or a port forward.
* Every device shows how it is connected: the *Network server* diagnostic sensor and a label chip
  (**LoRaWAN · Gateway network server** or **LoRaWAN · Home Assistant network server**) in Settings → Devices –
  filter by it to see which devices are on which server.
* The gateway entry gets **Network server devices** (joined devices; attributes: gateways connected, downlink
  airtime per gateway, counters, recent joins and refusals). Keys are never logged or shown in diagnostics.

**Scope**: EU868, class A, OTAA (LoRaWAN 1.0.x), confirmed / unconfirmed up- and downlinks,
LinkCheck and DeviceTime (clock sync). Not yet: ADR (devices keep their data rate), class C, Basics Station,
other regions, duty-cycle enforcement on the gateway.

## Gateway discovery

Home Assistant finds Milesight gateways by itself, three ways:

* **Network scan** – 90 s after start, every 6 hours and with **Scan network for gateways** (gateway entry), Home
  Assistant looks for Milesight MAC addresses on its own network (/24). Needs Home Assistant on the host network
  (Home Assistant OS, or Docker with host networking); gateways on another subnet are not seen.
* **On the network** – a gateway plugged into the same network shows up under **Settings → Devices & services →
  Discovered** as *Milesight gateway found* (Home Assistant's DHCP discovery, Milesight MAC prefix 24:E1:24). Add it
  with a name and an area. On a new installation this also sets up the integration with the **built-in network
  server** – no MQTT broker needed. The card says exactly what to set on the gateway (packet forwarder → Semtech →
  Home Assistant's IP, port 1700) if it is not prepared for Home Assistant already.
* **From its first packet** – a gateway that forwards to Home Assistant (built-in network server, or uplinks over
  MQTT) and is not known yet is offered as *New gateway sending to Home Assistant*.
* **By QR code** – scan the gateway's label or your own sticker in **LoRaWAN commissioning** (gateway EUI, MAC
  address, JSON such as `{"gateway_eui": "24E124FFFEFA2994", "model": "UG65"}`, or labelled text).

Every gateway device shows how it connects in its model line (*LoRaWAN gateway · MQTT* / *· Semtech UDP*) and in
its **Connection** sensor, with how it was found, its IP / MAC address and a link to its web page.

A gateway added before it sends is matched to its first packet by EUI (a Milesight gateway EUI is its MAC address
with FFFE in the middle), or by IP address when it forwards with another interface's EUI. It is then named, put in
its area, linked to its web page (*Visit* on the device page) and a notification says it is connected; event
`milesight_lorawan_gateway_connected`.

**Configure the gateway from Home Assistant** (no web page visit): on a discovered gateway with an IP address, tick
*Configure this gateway for me* and enter its admin login. Home Assistant logs in over the LAN and points the
packet forwarder at itself (built-in network server), and / or sets up the gateway's embedded network server with an
application and MQTT data transmission (broker and all topics, including the ns-api request/response topics for
adding devices). Also the service `milesight_lorawan.configure_gateway`. The admin password is sent only to the
gateway, encrypted the way its login page does, and is never stored. Supported on UG65 / UG67 / UG56 / UG63 with the
web API.

**Off-the-shelf kits**: prepare each gateway before shipping – packet forwarder Semtech destination pointing at the
customer's Home Assistant, frequency plan – and stick a QR code with its EUI. The customer installs Home Assistant
and this integration, plugs in the gateway (discovered), then scans the sensors' QR codes.

## Add devices to the gateway from Home Assistant

No more typing DevEUIs into the gateway's web page: Home Assistant registers new devices on the Milesight gateway's
built-in network server through MQTT (Milesight *ns-api*).

1. On the gateway: **Network Server → Applications →** your application → **Data Transmission → MQTT**: set
   **Request Data Topic** (e.g. `milesight/request`) and **Response Data Topic** (e.g. `milesight/response`) –
   they must be different. Same broker as the uplinks.
2. In Home Assistant: gateway entry → **Configure → Add devices to the gateway**: enter the two topics (and the
   default AppKey – Milesight devices ship with `5572404c696e6b4c6f52613230313823`). Home Assistant reads the
   gateway's device list to check the connection, then asks for the **application** and **device profile** new
   devices go into (ClassA-OTAA for battery sensors).
3. **Add a device manually** and **Add many devices** now have *Also add it to the gateway* (manual add also an
   *AppKey* field). A device that is already registered is left as it is.

The gateway device gets **Devices on gateway** (with the list, and which ones Home Assistant doesn't have yet) and a
**Sync devices with gateway** button – devices registered on the gateway but missing in Home Assistant are offered
under *Discovered*, with the model guessed from their name. Services: `milesight_lorawan.add_to_gateway`,
`remove_from_gateway`, `sync_gateway_devices`. AppKeys are never stored by Home Assistant (the default key is
redacted in diagnostics); note that MQTT debug logging prints the request, key included.

## Commissioning mode (installers)

Sidebar → **LoRaWAN commissioning** (administrators only), made for a phone on site:

**1 · Add a device – scan its QR code**
* **Scan with the app**: the Home Assistant Companion app's own scanner (iPhone and Android, works without
  internet).
* **Use the camera** (browsers on https) or **Take / pick a photo**; or type / paste the DevEUI.
* Reads Milesight label codes – LoRa Alliance TR005 (`LW:D0:…`), JSON, "DevEUI: … AppKey: …" text or the bare
  DevEUI – and fills in the DevEUI, AppKey and model (from the code, or from the device's first uplink if the
  gateway already hears it).
* **Add device** puts it in Home Assistant (name, area) and, with *Add devices to the gateway* set up, registers
  it on the gateway in the same step.

**2 · Walk test – live signal while you walk the site**
* Pick the device (or one the gateway hears that is not set up yet). Every uplink appears at once: signal verdict
  (excellent / good / fair / poor), RSSI, SNR, spreading factor, link margin and every gateway that heard it,
  with a beep and vibration – different tones for good and poor.
* Type where you are ("Barn, north wall, 2 m") – it is saved with each uplink, so the table compares spots.
* **Fast reporting (30 min)** sets the device to report every minute while you walk and puts its normal interval
  back afterwards by itself (also after a restart). The device takes the change at its next report – press its
  button to make it report straight away.
* **Save result** keeps the test on the device (count, RSSI / SNR range, gateways, worst verdict, advice, spot,
  note, who) – shown on its *Signal quality* sensor and in the diagnostics download, as the commissioning record.

## Tanks and silos

Level and distance sensors (EM400-UDL / -MUD, EM410 / EM411-RDL, EM310-UDL, EM500-UDL, EM500-SWL) turn into tank
gauges: device → **Configure → Tank or silo**.

| Shape | Size to enter |
|---|---|
| Upright cylinder | diameter, height |
| Lying cylinder | diameter, length |
| Rectangular | length, width, height |
| Silo with cone bottom | diameter, total height, cone height |
| Any other shape | capacity (L) and height – litres follow the level |

Distance sensors also need the *distance reading when empty* (sensor to floor); the submersible EM500-SWL needs the
probe's height above the floor. The form shows the resulting capacity.

New entities: **Contents** (L), **Tank fill** (%), **Liquid level**, **Usage per day** (L/d, over the last week,
refills and sensor jitter ignored), **Days until empty**, **Empty around**, **Last refill**, **Space left**
(disabled), optional **Contents weight** (density, e.g. diesel 840 kg/m³, feed pellets 650), **Tank low** (below
20 % by default) and a **Tank refilled** button.

**Sudden drop** (theft or leak – e.g. diesel): set *Sudden-drop alarm when it falls by* (% of the capacity) *within*
(minutes). The binary sensor stays on until **Clear sudden-drop alarm** is pressed or the tank is refilled.
Refills (also slow pump refills) and sudden drops fire `milesight_lorawan_tank` (`type: refill | sudden_drop`,
`added` / `amount` in litres). A big jump is only believed when the next reading confirms it, so a single bad echo
doesn't raise an alarm. Dashboard: [`dashboards/tanks_and_alerts.yaml`](dashboards/tanks_and_alerts.yaml).

## Modbus and analog channels

Third-party probes on a UC300 / UC50x / UC11xx / UC100 (pressure transmitters, flow meters, level probes, energy
meters) become proper sensors: device → **Configure → Channels**, one line per channel:

```
channel; name; unit; scale; offset; device class; decimals; state class
3;       Line pressure; bar;  0.01
3.2;     Flow;          m³/h; 0.1; 0; volume_flow_rate; 1
adc_1;   Borehole level; m;   4-20>0-10
pt100_1; Cold room;     °C
```

* **channel** – the Modbus channel number from Milesight ToolBox (`3`; `3.2` = channel 3 register 2 on UC100 v2) or
  the input: `adc_1`, `adv_1`, `analog_input_1`, `pt100_1`, `gpio_counter_1`.
* **scale** – a multiplier, or a range `4-20>0-10` that maps the raw span onto the real one (4–20 mA → 0–10 m).
* **device class** is taken from the unit when left empty (bar → pressure, °C → temperature, m³/h → flow …).
* Empty columns (or `-`) keep the default; `#` starts a comment. Mistakes are listed line by line in the form.

The entity keeps its id and history, it just gets the new name, unit and scaled value. The form lists the channels
the controller has reported so far with their raw values. (Which registers are read is still set on the controller
in Milesight ToolBox – the Milesight encoders have no downlink for it.)


### Sensor templates (RS485 / Modbus)

Device → **Configure → Sensor templates** lists the templates applied to the controller, edits or removes them,
and applies new ones (editing a UC100 template re-sends only the channels that changed). Applying fills the channel map for common RS485 probes and tells you what
to enter in Milesight ToolBox. Pick the sensor, tick the values you want, choose the first free Modbus channel and
the probe's address; the values take consecutive channels. Several templates can go on one controller (UC300 /
UC50x: 16 Modbus channels, UC300 and UC100: 32), e.g. a soil / NPK probe (address 1) on channels 1–9 and a WS101LL level sensor (address 2) on 10–16.

| Template | Default address / bus | Values |
|---|---|---|
| Ecowitt WS90 / WN90LP weather station | 0x90 (144) or 1, 9600 8N1, registers 357–366 (0x0165–0x016E) | light, UV index, temperature, humidity, wind speed, gust, wind direction, rainfall, pressure, rain counter |
| CWT 7-in-1 soil / NPK sensor (THCPH-S) | 1, 9600 8N1, input registers 0–8 (signed) | moisture, temperature, conductivity, pH, nitrogen, phosphorus, potassium, salinity, TDS |
| WoMaster WS101LL liquid level sensor | 1 (set to 2 next to another probe), 9600 8N1, input registers 2–6, 13, 2000 | water level (Measure Value), unit code, decimal points, full point; zero point, offset and address optional |
| LuxPower LXP / EG4 hybrid inverter (UC100) | 1, 19200 8N1, input registers 0–106 (32-bit totals CDAB) | PV, battery / BMS, grid, inverter, energy today and totals, fault codes (46 values, 26 by default) |

All probes on one RS485 bus need the same baud rate – the confirmation page warns when the defaults differ (the
CWT soil sensor is set to 9600 by writing 2 to register 0x07D1). The channel map now also takes options: `s16`
for signed registers and `invalid=65535` for the "no reading" value, which then shows as unknown instead of a
huge number. Soil-moisture channels join the irrigation advice by themselves.


**UC100: set up over LoRaWAN.** On a UC100 (firmware v1 or v2) the confirmation page has *Send to the controller*:
the channels (slave ID, register, type, quantity, signed) and their names go to the device as downlinks – no
ToolBox needed. On firmware v2 the RS485 port settings (baud, data bits, parity, stop bits) are sent too; on v1
set them once in ToolBox. The UC100 takes one downlink after each uplink, so *Report every minute for 30 minutes*
is on by default (the normal interval comes back by itself). Every channel shows up in *Command status* and is
confirmed when the UC100 echoes it. Removing a template can also delete its channels from the UC100. The byte
format is the one Milesight's own encoders use. The UC300 and UC50x have no Modbus downlinks in Milesight's
protocol – set their channels up in ToolBox.

## Alert escalation

Gateway entry → **Configure → Alert escalation** sends alerts to phones (Home Assistant Companion app) and makes
sure someone reacts:

* **On-call rota** (optional) – who is told first, by day and time; the first matching line wins, outside the
  rota *Notify first* is used:
  ```
  Mon-Fri 07:00-17:00: notify.mobile_app_juan
  Weekdays 17-07: notify.mobile_app_piet          # overnight, runs into the next morning
  Weekend: notify.mobile_app_sam, notify.mobile_app_ann
  ```
* **Escalate to** – an ordered list. Nobody presses *Acknowledge* within *Escalate after* (default 15 min) → the
  **next person** on the list is added, then the next, one at a time; optional reminders.
* **Quiet hours** – non-critical alerts wait until the morning. **Per category** you can override them
  (`building: 18-07`, `devices: 20:00-06:30`, `tank: none` = never held). Leaks, smoke, gas, falls, sudden tank drops and
  gateway outages always go through, as critical alerts (they sound on a muted iPhone / use the Android alarm
  stream).
* **Duplicates** – a sensor that flaps on and off continues the same alert; *Resolved* is only sent once it stays
  resolved for a few minutes.
* **Buttons on the phone** – **Acknowledge**, **Snooze 1 h** (reminders and escalation pause; if it is still
  active it comes back as *Still active*; the time is a setting) and **Open dashboard** (the dashboard for the
  alert: Tanks, Farm, Cold chain, Energy, Building analytics, Maintenance, else the site landing page; it is
  **View on map** when the device has a location). Tapping the notification only opens it.
  Tank-low alerts can show an extra button instead (e.g. *Start pump*) that runs
  a switch, script or button (Android shows three buttons).
* **Weekly summary** – every Monday 08:00 (day and hour are settings) a message to *Notify first* and the rota:
  alerts of the last 7 days by category, the noisiest devices (with repeats) and the mean time to acknowledge.
* **Alerts to send** – safety, tanks, pumps (dry-run, overload, short-cycling), irrigation (pivot stalled, frost
  tonight), building (CO₂ / temperature / humidity), devices (offline, battery), gateways offline, commands not
  confirmed. Categories added in a later version start switched on.

The gateway gets **Open alerts** (with the list and who acknowledged), **Alerts last 7 days** (the summary, who
is on call now), **Acknowledge all alerts** and **Send alert summary**; service
`milesight_lorawan.acknowledge_alert`; every message also fires `milesight_lorawan_alert` for your own automations.

## Cold storage and compliance reports

The **Cold storage** dashboard (installed once a device's purpose is *Fridge / cold room* or *Freezer*) has:

* **Overview** – how many units are in range, in alarm, drifting (out of range but still within the alarm delay)
  and have the door open, the worst *time in range over 7 days*, red / amber alerts per unit, and every unit by
  area: a temperature gauge (blue below, green inside, red above the limits) with alarm, door, time in range and
  compressor duty.
* **Units** – per unit: temperature, limits, out of range and excursions today, door, compressor, the last 24 h,
  the alarm limits (typed in), battery and connection.
* **Trends** – hourly min / mean / max over 7 days and daily over 30 days (long-term statistics), time in range.
* **Compliance** – the reports with their status and PDF link, buttons for *last week* / *last month*, the
  **corrective actions** (type what was done; it is saved with your name and time) and a 14-day log per unit.
* **Table** and **Compressors** – the all-units table, 7-day log and the compressor duty table.

**Compliance reports** (gateway → Configure → *Cold-chain compliance reports*): one PDF per fridge, freezer or cold
room for food-safety / HACCP audits – minimum, maximum, mean and **mean kinetic temperature**, **time out of
range**, **excursions** (out of range longer than the alarm delay) with start, end, peak and the **corrective
action** recorded, short excursions (door openings, defrost), **door-open time** and count, doors left open,
**data coverage and gaps**, a daily table, a chart with the allowed band and a sign-off block. The status is
*Compliant*, *Deviations – actioned* (every excursion has a corrective action) or *Not compliant* (an excursion
without an action, or less than 95 % data coverage).

* **Weekly** (Monday–Sunday, made on Monday), **monthly** (made on the 1st), both, or off; default weekly at 06:05.
  If Home Assistant was off at that time, the missing report is made at the next start.
* **E-mail**: choose a notify service (e.g. the [SMTP integration](https://www.home-assistant.io/integrations/smtp/)
  with your auditor / QA address). The PDFs are attached and linked. Without one, the reports are kept and shown
  in a notification and on the dashboard.
* Files: `/config/www/milesight/compliance/<year>/` with an unguessable name (the `/local/` folder is not behind the
  login). Raw history comes from the recorder (10 days by default); older parts of a month use the hourly
  long-term statistics – set `recorder: purge_keep_days: 35` for full detail in monthly reports.
* On demand: buttons *Cold-chain report: last week / last month*, or the service
  `milesight_lorawan.compliance_report` (period `week`, `month` or `custom` with start / end, optional devices,
  send or not – it returns the links). Event `milesight_lorawan_compliance_report` for your own automations (e.g.
  copy the PDFs to a NAS).
* Corrective actions: the unit's **Log corrective action** field, or `milesight_lorawan.log_service` with kind
  `corrective_action`.

## Battery and maintenance

**Battery forecast** – every battery device gets **Battery replacement due** (a date) and **Battery days left**.
The forecast fits a line through one reading per day over the last months (Milesight reports whole percent, so
it needs about two weeks of history; until the level first drops it says *no drop yet*). When the reporting
rate changed it scales the drain to the current rate. It counts down to the device's *battery low* level. New
batteries are detected by themselves (level jumps up to 80 % or more), or use the action **Battery replaced**.
Devices that only report a voltage use a rough lithium curve (3.6 V full, 3.0 V empty).

**Maintenance dashboard** (installed for every site): batteries due (red ≤ 30 days, orange ≤ 90), devices
offline more than 24 h, weak signal with advice, firmware per model (mixed versions flagged, older devices
listed) and the **service history**. Battery replacements, firmware changes and applied settings profiles are
logged by themselves; add your own with the action **Log service** (`milesight_lorawan.log_service`: device,
kind, note). Device alerts (offline, battery) open this dashboard from the phone.

**Settings profiles** – device → **Configure → Settings profile**: copy this device's set-up to other devices of
the same model in one go, save it under a name, or load a saved one. It copies the options (limits, purpose,
opening hours, meters, channel map – optional) and, optionally, the settings sent to the device (reporting
interval, alarm thresholds …) – only what differs is sent, queued and confirmed like any command. Options that
belong to one device (pivot centre, applied Modbus templates, meter offset) are not copied. Also as the action
`milesight_lorawan.apply_settings_profile`.

**Device location** – a fixed point per device: on site open **LoRaWAN commissioning** in the Home Assistant app
→ *Walk test* → pick the device → **Use my phone's location** (uses the page's GPS on https://, otherwise asks the
Home Assistant app for a fresh position from its own location tracking – turn location on in the app), or device →
**Configure → Location** with a map picker. It becomes the device's **Location** entity (Home Assistant's Map
too), the Maintenance dashboard's **Map** tab and a column in the handover report.

**Installer handover report** – the gateway's **Create handover report** button (or the action
`milesight_lorawan.handover_report`) writes a printable page and a CSV to `/config/www/milesight/` and shows
links: site and contact, gateways, open points (offline, weak signal, single gateway with little margin, low
battery, no area) and every device with area, purpose, network server, signal, battery and due date, firmware,
last seen and the walk-test result, with signature lines. *Print / save as PDF* from the browser.

## Live dashboard views (gauges, sliders, maps)

The Farm, Tanks & alerts, Cold chain and Energy & HVAC dashboards get a first **Live** view built from your
devices: the pivot on a map (AT101 track and pivot centre) with a *Round done* gauge, gauges for pump current,
tank fill, soil moisture, cold-chain temperatures and duty cycles (coloured from each device's own limits), and
**sliders** for the limits themselves – tank low alarm, pump normal current and starts per hour, pivot stall time,
temperature band and left-open time, irrigation target / time / frost temperature. A slider writes the device's
option (the device reloads with it, and the gauge bands follow). The view is rebuilt when devices are added or
changed; if you edit the dashboard in Home Assistant your version is kept.

## Purposes – what a device is fitted to

The model says what a device *measures*; the **purpose** says what it is *fitted to*. A WS301 can be on a door, a
window, a gate or a fridge; a CT101 on a pump, an air conditioner or a compressor; an EM300-TH in an office or a
freezer. Pick it when you add the device (commissioning page, *Add a device*, the discovery card, the bulk list) or
later under device → **Configure → Purpose**. The purpose:

* **labels** the device by group – *Milesight · Cold chain*, *· Pumps & motors*, *· HVAC*, *· Energy*,
  *· Security*, *· Water*, *· Tank / silo*, *· Irrigation*, *· Facilities*, *· Assets & vehicles*, *· Air & comfort*,
  *· People & occupancy*;
* changes **how entities look** – a contact becomes *Window*, *Gate*, *Garage door* (with the matching device
  class), a clamp's *Load* becomes *Compressor* / *Air conditioner*, a probe gets a fridge / boiler / pool icon;
* sets **default limits** – a fridge door is *left open* after 2 min, a gate after 30; a fridge alarms outside
  0–5 °C after 15 min, a freezer outside −25…−15 °C after 20 min. Change them on the *Alarm limits* page that
  follows (empty a box to switch that alarm off);
* adds **analytics and alerts** (below) and puts the device on the right **dashboard** (*Cold chain*,
  *Energy & HVAC*, *Farm*, *Tanks & alerts*).

One purpose per device – the same one for every sensor on one thing: the fridge's probe, its door contact and the
clamp on its compressor are all *Fridge / cold room*. 3-channel clamps (CT303 / CT305 / CT310) can give each
channel its own purpose (*Channel 1–3*) when the channels measure different loads.

**What the purposes add**

* **Cold chain** (fridge, freezer): *Temperature out of range* only after the delay, so door openings and defrost
  do not alarm (with a door contact on the same device the delay restarts once the door closes); *Time out of range
  today*, *Temperature excursions today* and a **31-day cold-chain log** (min / max / minutes out of range /
  excursions per day, for HACCP records); door left open; compressor **duty cycle** today and over 24 h,
  *running too long* (it cannot keep up) and *not running* (tripped or failed).
* **Loads** (air conditioner, lighting, geyser, air compressor, motor, washer, appliance – CT clamps and smart
  sockets): duty cycle, run time and starts today, run hours; *on after hours* (running 30 min outside working hours
  – energy waste, or an air leak for compressors); *service due* every N run hours with a *serviced* button.
* **Mains** (CT303 / CT310 on the distribution board): *Power outage* (no current on any phase) and *Phase
  imbalance* (> 25 % between phases).
* **Openings** (door, gate, garage, cabinet / safe, tank lid) and **Security (intrusion)** motion: *After-hours
  activity* when opened / triggered outside working hours (cleared when the next working day starts).
* **Temperature watch** for geysers (below 55 °C = legionella risk), pipes (frost below 3 °C), server rooms (above
  27 °C) and **silo hot spots** (+3 °C in 24 h).
* **Waste bin** (EM400-TLD / -UDL in the lid): *Bin fill*, *Bin full* (80 %), fill rate per day and *full in* days.
  **River / flood level**: water level above the lowest point and *Water rising fast* (10 cm/h).
* **Rain gauge** (pulse counter, *pulses per mm* in Device settings): rain today and in the last 24 h – the
  irrigation advice skips watering after rain that has already fallen.
* **Soil** (field, greenhouse, garden): added to the irrigation advice by itself.
* **Toilet / washroom**: visits since cleaned, *Cleaning due* after 50, *Cleaned* button.
* **Panic / SOS** button: a critical alert for 30 min (*Clear panic alarm* button); **Service request**: a
  facilities alert.
* **Air** (classroom, warehouse …): the CO₂ limit for the room type.

Working hours (for *after hours*) are set on the *Alarm limits* page: default 08:00–17:00, Monday to Friday.
Events: `milesight_lorawan_temperature` (`out_of_range`, `back_in_range`), `milesight_lorawan_load`
(`after_hours`), `milesight_lorawan_after_hours`, `milesight_lorawan_panic`, `milesight_lorawan_service`.
New alert categories *cold chain*, *security*, *energy* and *facilities* (on by default).

<details><summary>All purposes</summary>

| Purpose (bulk key) | Label group | Fits | Defaults |
|---|---|---|---|
| Fridge / cold room (`fridge`) | Cold chain | clamp / socket, contact, temperature | temp low 0, temp high 5, temp delay min 15, left open min 2, max run h 3, no run h 3 |
| Freezer (`freezer`) | Cold chain | clamp / socket, contact, temperature | temp low -25, temp high -15, temp delay min 20, left open min 2, max run h 4, no run h 4 |
| Pump (`pump`) | Pumps & motors | clamp / socket | – |
| Air compressor (`air_compressor`) | Pumps & motors | clamp / socket | after hours True, max run h 1 |
| Motor / conveyor / machine (`motor`) | Pumps & motors | clamp / socket | service h 500 |
| Air conditioner / heat pump (`ac`) | HVAC | clamp / socket | after hours True |
| Geyser / water heater (`geyser`) | Energy | clamp / socket, leak, temperature | temp low 55, temp delay min 60 |
| Lighting circuit (`lighting`) | Energy | clamp / socket | after hours True |
| Mains / distribution board (`mains`) | Energy | clamp / socket | – |
| Other machine / appliance (`appliance`) | Energy | clamp / socket | – |
| Door (`door`) | Security | contact | left open min 10, after hours True |
| Window (`window`) | Security | contact | left open min 60 |
| Gate (`gate`) | Security | contact | left open min 30, after hours True |
| Garage / roller door (`garage`) | Security | contact | left open min 15, after hours True |
| Cabinet / safe / server rack (`cabinet`) | Security | contact | left open min 5, after hours True |
| Tank lid / hatch (`lid`) | Security | contact | left open min 10, after hours True |
| Room / office (`room`) | Air & comfort | air, motion / people, temperature | – |
| Meeting room (`meeting_room`) | People & occupancy | air, motion / people | – |
| Classroom (`classroom`) | Air & comfort | air, motion / people | co2 limit 1000 |
| Warehouse / factory (`warehouse`) | Air & comfort | air, motion / people, temperature | co2 limit 1500 |
| Server room (`server_room`) | Security | air, contact, leak, temperature | temp high 27, temp delay min 10, left open min 15 |
| Pool / water (`pool`) | Water | temperature | – |
| Pipe (frost watch) (`pipe`) | Water | temperature | temp low 3, temp delay min 30 |
| Outdoor (`outdoor`) | Air & comfort | temperature | – |
| Washing machine / dishwasher (`washer`) | Water | clamp / socket, leak | – |
| Basement / sump (`basement`) | Water | leak | – |
| Roof / ceiling (`roof`) | Water | leak | – |
| Water tank (`water_tank`) | Tank / silo | level | – |
| Fuel tank (`fuel_tank`) | Tank / silo | level | – |
| Silo / grain / feed (`silo`) | Tank / silo | level, temperature | temp rise day 3 |
| Waste bin (`bin`) | Facilities | level | bin depth mm 1000, full pct 80 |
| River / flood level (`flood`) | Water | level | empty distance mm 3000, rise cm h 10 |
| Water meter (`water_meter`) | Water | pulse | – |
| Electricity meter (`electricity_meter`) | Energy | pulse | – |
| Gas meter (`gas_meter`) | Energy | pulse | – |
| Rain gauge (`rain_gauge`) | Irrigation | pulse | – |
| Production / footfall counter (`counter`) | – | pulse | – |
| Desk (`desk`) | People & occupancy | motion / people | – |
| Toilet / washroom (`toilet`) | Facilities | air, motion / people | clean visits 50 |
| Security (intrusion) (`intrusion`) | Security | motion / people | after hours True |
| Panic / SOS button (`panic`) | Security | button | latch min 30 |
| Service request (cleaning, help) (`service`) | Facilities | button | latch min 60 |
| Doorbell (`doorbell`) | – | button | – |
| Scene / light control (`scene`) | – | button | – |
| Asset (`asset`) | Assets & vehicles | tracker | – |
| Vehicle (`vehicle`) | Assets & vehicles | tracker | – |
| Livestock (`livestock`) | Assets & vehicles | tracker | – |
| Centre pivot (`pivot`) | Irrigation | tracker | – |
| Field soil (`field`) | Irrigation | soil | – |
| Greenhouse (`greenhouse`) | Irrigation | soil, temperature | – |
| Garden / turf (`garden`) | Irrigation | soil | – |
| Irrigation valve (`irrigation_valve`) | Irrigation | valve | – |
| Water main valve (`water_valve`) | Water | valve | – |

</details>

## Pumps (current clamps)

A CT101 / CT103 / CT303 / CT310 (any clamp with *Load running*) on a pump or motor → device **Configure → Pump**,
tick *This clamp measures a pump* (on a 3-channel clamp the channels are taken as the phases of one motor and
added up):

* **Pump run hours**, **starts last hour / 24 h** and **Pump short-cycling** (more starts per hour than allowed,
  default 6 – a failing pressure switch or a waterlogged pressure tank).
* **Pump dry-run** – running at less than 60 % of its normal current (lost prime, empty borehole, broken shaft) –
  and **Pump overload** above 125 % (blockage, seized bearing, low voltage). Two readings in a row are needed; a stop
  ends the alarm. *Normal running current*: type it in, or leave 0 and it is learned (median of the last 7 days'
  running readings, shown as *Pump normal current*).
* **Running**: from *Running above* (Configuration). 0 = automatic: 30 % of the normal current when one is set,
  otherwise 0.2 A.
* **Pump energy today** from the clamp's energy counter. Clamps without one (CT101/CT103) get an *Energy* sensor
  once you type a **Voltage** under Configuration: cumulative current (Ah) × voltage × **Power factor** (default
  0.85), and **Estimated power** in W (current × voltage × power factor; *Apparent power* in VA is there too).
* Choose a **water meter** (e.g. an EM300-DI / UC pulse counter set up as a water meter) and you also get
  **Pumped today** and **Water per kWh** (m³/kWh) – a falling figure means a worn impeller or a dropping water table.

Events `milesight_lorawan_pump` (`start`, `stop`, `dry_run`, `overload`, `short_cycling`) and alerts in the
*pumps* category. Rated for dry-run protection? Use the alert / event to switch the pump off with your own
automation – the integration only warns.

## Centre pivots (AT101)

Mount an AT101 on the pivot's end tower → device **Configure → Centre pivot**, drag the marker to the pivot point,
set *Degrees in a full round* (360, or the sector of a part-circle pivot) and *Stalled after* (default 30 min):

* **Pivot angle** (0° = north, clockwise), **Pivot round done** (%), **Pivot speed** (°/h), **Pivot finishes in**
  and **Pivot finishes at**, **Pivot status** (running, stalled, finished, stopped), **Distance from pivot centre**.
* **Pivot stalled** – no movement for the set time during a round (checked every minute, also when the tracker
  stops sending). Alert in the *irrigation* category and event `milesight_lorawan_pivot` (`started`, `stalled`,
  `finished`). Stopped it on purpose? Press **Pivot stopped (end round)**.
* Part-circle pivots that reverse at the ends start a new pass on every reversal. GPS fixes more than 1.5 km from
  the centre are ignored, movements under 1° count as GPS noise.

Set the tracker's reporting interval to 5–10 minutes while the pivot runs.

## Forecast-aware irrigation and frost

Gateway entry → **Configure → Irrigation and frost**: choose a **weather entity** with a forecast (Met.no,
Open-Meteo, OpenWeatherMap …) and optionally **soil moisture sensors** (EM500-SMTC …). The gateway gets:

* **Irrigation advice** – *irrigate* or *skip*, with the reason and suggested **minutes**: skip when at least
  5 mm of rain is forecast within 24 h (with a probability of 60 % or more when the forecast gives one) or when
  the soil is at the target (30 %); otherwise *irrigation time for dry soil* scaled by how dry the soil is, minus
  a share for smaller rain on the way.
* **Rain expected** and **Frost tonight** – on from 15:00 the afternoon before when the forecast low until 10:00
  the next morning is at or below the frost temperature (default 2 °C). Event `milesight_lorawan_frost` once per
  night and an alert in the *irrigation* category.
* The **Milesight – irrigation / valve schedule** blueprint takes the advice: it skips on *skip* and shortens the
  duration by the suggested minutes.

Hourly forecasts are used when the weather integration has them, else daily ones. The forecast is read every
30 minutes – the only part that needs the internet; with the link down the advice keeps the last forecast for up
to 6 hours and then falls back to soil moisture alone.

## Settings per device

Open the device's integration entry → **Configure** (⚙️). Picked the wrong model during onboarding? Change **Model** here; afterwards delete the old, now-unavailable entities from the device page.

| Setting | Devices | Default |
|---|---|---|
| Offline gap (min) – time isn't counted across longer gaps | all | 120 |
| Door left open after (min) | EM300-MCS | 10 |
| CO2 limit (ppm) | AM300 range, EM500-CO2 | 1000 |
| Empty distance (mm) – for fill level % | EM400-TLD (level sensors: under *Tank or silo*) | 0 (off) |
| Tank or silo – shape, size, low level, refill / sudden-drop alarm | level & distance sensors | off |
| Channels – name / unit / scale per Modbus register or analog input | UC controllers | – |
| Running above (A) – for run time and starts | CT range | 0.5 |
| Voltage for power estimate (V) | CT range | 0 (off) |
| Count as empty after (min at 0 people / vacant) | VS121, VS321, VS340, VS341, VS370, VS373, GS601 | 2 |
| Opening hour / closing hour / open days (for utilisation %) | VS-range, GS601 | 08–17, Mon–Fri |
| Confirmed downlinks (network ACK) | devices with commands | off |
| Retries for unanswered commands | devices with commands | 2 |
| Max bytes per display downlink | DS3604 | 51 |

Devices with these extra sections show a menu under **Configure**: *Device settings*, *Channels*, *Tank or silo*.

Gateway entry → **Configure**: *Site information*, *Alert escalation*, *Add devices to the gateway* and *Gateway
connection* (uplink / downlink topics, *Notification / gateway status topics* – ACK, join, gateway information,
comma separated, wildcards allowed – and *Gateway offline after*, min, default 15).

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
| **0.39.1** | Configure the gateway from Home Assistant over the LAN (Semtech and/or embedded NS + MQTT); configure_gateway and forget_gateway services; delete a gateway from the device page. |
| **0.38.0** | Gateway connection and "found via" shown; network scan for gateways. |
| **0.37.0** | Gateway discovery: on the network (DHCP), from the first packet, by QR code; first gateway sets up the built-in network server. |
| **0.36.0** | Cold storage dashboard (Overview, Units, Trends, Compliance); weekly / monthly compliance PDFs by e-mail; corrective actions; estimated power in W. |
| **0.35.0** | Voltage, power factor and running threshold fields for clamps; energy from Ah × V; typed-in pump settings. |
| **0.34.2** | Gauges show a tile instead of "non-numeric" until data arrives; never-heard devices on Maintenance. |
| **0.34.1** | Alert notifications: View on map / Open dashboard as a button (no jump on tap); phone location via the app's own tracking. |
| **0.34.0** | Maintenance dashboard with tabs (Overview, Devices, Signal, Map) replaces Fleet and Signal; device location captured with the phone. |
| **0.33.1** | Site landing page created reliably, named after the site, with a notification. |
| **0.33.0** | Battery forecast, Maintenance dashboard with service history, settings profiles, installer handover report. |
| **0.32.0** | Smart alerts – Snooze and Open dashboard buttons, on-call rota, one-by-one escalation, quiet hours per category, weekly summary. |
| **0.31.2** | Network-server label on every device from start-up. |
| **0.31.1** | Network-server chip (label) and sensor on every device. |
| **0.31.0** | Built-in LoRaWAN network server – gateways' packet forwarders send to Home Assistant, devices join with their AppKey. |
| **0.30.0** | Site landing page (auto-created, dashboard buttons, people, alerts, tanks, farm …); phone-friendly Building analytics, Farm and Tanks & alerts dashboards. |
| **0.29.1** | Edit applied sensor templates; on the UC100 only changed channels are re-sent. |
| **0.29.0** | Live dashboard views: pivot map, gauges with limit bands, setpoint sliders (tank, pump, pivot, temperature, irrigation). |
| **0.28.1** | LuxPower template slimmed to 26 default values (daily kWh from the totals); UC300 has 32 Modbus channels. |
| **0.28.0** | Sensor templates are sent to the UC100 over LoRaWAN (channels, names, RS485 port on v2) and confirmed; removing a template deletes its channels on the UC100. UC100 limited to its 32 channels. |
| **0.27.0** | LuxPower / EG4 inverter template for the UC100 (64 channels, 32-bit totals, packed SOC / SOH). |
| **0.26.2** | Sensor templates: CWT 7-in-1 NPK updated to the tested ToolBox setup, new WoMaster WS101LL liquid level template. |
| **0.26.1** | Sensor templates: ToolBox-style channel list, applied templates shown and removable, WS90 rain counter by default. |
| **0.26.0** | RS485 sensor templates for UC controllers (Ecowitt WS90 weather station, CWT soil / NPK probe); channel-map options s16 and invalid=…; soil channels feed the irrigation advice. |
| **0.25.1** | Fix: the Pump options form (current clamps) opened with an empty "Error". |
| **0.25.0** | Purposes: what a device is fitted to (≈50, from fridge to gate to panic button) – grouped labels, entity looks, default limits, cold-chain log, duty cycle, after-hours, bins, flood, rain gauge, toilets, panic; Cold chain and Energy & HVAC dashboards. |
| **0.24.0** | Pump analytics (run hours, short-cycling, dry-run, overload, m³ per kWh), centre-pivot analytics from an AT101 (angle, % done, speed, time to finish, stall alarm), forecast-aware irrigation advice and frost warnings, Farm dashboard. |
| **0.23.1** | Version bump of 0.23.0. |
| **0.23.0** | Commissioning mode: scan a device's QR code to add it (and register it on the gateway), live walk test with fast reporting and saved results. |
| **0.22.2** | Area occupancy history kept across restarts. |
| **0.22.1** | Gateway device list read automatically (start + every 6 h). |
| **0.22.0** | Devices are tagged by use (tank, people, comfort) as Home Assistant labels; dashboards appear only when a site has devices that need them. |
| **0.21.1** | Fixed the UndefinedError on the fleet, signal and tanks dashboards. |
| **0.21.0** | Blueprints and dashboards ship inside the integration and are installed / updated automatically (HACS update), with an *Install dashboards and blueprints* button. |
| **0.20.3** | Devices with a gateway payload codec (e.g. AM107) are discovered and decoded. |
| **0.20.2** | AppKey prefilled when adding a device; alphabetical model list. |
| **0.20.1** | Gateway provisioning accepts answers from more gateway firmware; clearer error when the gateway does not answer. |
| **0.20.0** | Add devices to the gateway from Home Assistant (ns-api over MQTT, also bulk), tanks and silos (litres, usage, days left, refills, sudden-drop theft alarm), alert escalation with actionable phone notifications, named / scaled Modbus and analog channels; UC300 Modbus readings after a settings reply fixed. |
| **0.19.1** | Dashboards find the gateway's sensors by themselves (entity ids depend on the gateway's name); corrected example entity ids. |
| **0.19.0** | Building dashboard: Site information (from Home Assistant + gateway settings), building health / comfort / air quality / people / alerts / averages sensors, one-click generated dashboard with built-in cards. |
| **0.18.0** | Command confirmation with retries (pending / confirmed / failed, network ACKs), signal quality per device (gateways in range, SF, packet loss, advice) with installer dashboard, DS3604 display content (text entities, service, room-sign blueprint), gateway health (a device per gateway: online, packets, devices heard, status reports). |
| **0.17.0** | Device settings as entities (alarm thresholds, child lock, LED, buzzer), stored-data backfill into long-term statistics, pulse counters as water / gas / energy meters for the Energy dashboard, building analytics (area comfort, occupancy heat map, utilisation) with dashboard. |
| **0.16.0** | Rollout tools: bulk onboarding with areas, fleet overview sensors + dashboard, online / battery-low sensors and events, 8 blueprints, settings confirmation. |
| **0.15.0** | Device commands: reboot, time sync, request update, reporting / collection interval, UC output and valve switches, UC521 valve opening; output_command and send_downlink services. |
| **0.14.0** | 25 more models: AM102 / 103 / 104 / 107, AM304L / 305L, EM300-CL / -MLD / -DI-HALL, EM310-UDL / -TILT, EM320-TH (v1 / v2) / -TILT, EM410 / 411-RDL, VS132 / 133 / 135 / 330 / 350 / 351 / 360, DS3604. People-counter statistics. |
| **0.13.0** | CTH01 multi-circuit energy meter added (CT range). |
| **0.12.0** | WT range added (WT101, WT102, WT201 v1 / v2, WT211, WT301, WT302, WT303, WT304, WT401) with thermostat control from Home Assistant. |
| **0.11.0** | WS range added (27 models): buttons as event entities, WS sensors, and wall switches / sockets / light controllers that can be switched from Home Assistant, with energy metering. |
| **0.10.0** | AT range added: AT101 tracker with map position (device tracker), trips, distance travelled and geofence statistics. |
| **0.9.0** | GS range added: GS101 gas, GS301 odour, GS524N smoke and GS601 vape detectors, with alarm statistics. |
| **0.8.0** | CT range added: CT101, CT103, CT105, CT303, CT305, CT310 (firmware v1 and v2), with load run-time statistics and estimated power. |
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
