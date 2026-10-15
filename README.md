# Milesight LoRaWAN for Home Assistant

[![Release](https://img.shields.io/github/v/release/Juanko984/milesight-lorawan-ha?label=version)](https://github.com/Juanko984/milesight-lorawan-ha/releases)
[![HACS](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue.svg)
![Models](https://img.shields.io/badge/supported%20models-45-brightgreen.svg)

**Current version: 0.16.0** · [Version history](#version-history)

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

Button presses as an event entity (single / double click, short / long press), current template, battery.

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
* **Downlink data topic** (only needed to switch WS wall switches / sockets from Home Assistant): e.g.
  `milesight/downlink/$deveui`. In the integration's gateway settings the same topic is written as
  `milesight/downlink/{deveui}` (the default).

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
DevEUI, Model, Name, Area
24E124136B322135, EM300-MCS, Back door, Warehouse
24E124538C220481, AM307, Meeting room 1, 1st floor
24E124600B251990, VS121, Reception, Ground floor
```

Model names are matched loosely (`em300 mcs`, `WS501 v4`). Every device is created straight away – no confirm
dialogs – and placed in its **area** (created if it doesn't exist). Devices that already exist are skipped and
mistakes are listed line by line. The single-device forms (manual and discovered) also have an *Area* field.

### Fleet overview

The gateway device gets four sensors: **Devices**, **Devices online**, **Devices offline** and **Devices with low
battery**. Their attributes list the devices (name, model, area, battery, RSSI / SNR, last seen).
A ready-made dashboard is in [`dashboards/fleet_overview.yaml`](dashboards/fleet_overview.yaml) – a status glance,
a *Needs attention* table and a table of all devices.

Every device also has an **Online** sensor (off after the *Offline gap*, default 120 min, without an uplink)
and – for battery devices – a **Battery low** sensor (threshold per device under **Configure**, default 20 %).
Going offline / online also fires `milesight_lorawan_device_offline` / `milesight_lorawan_device_online` events.

### Blueprints

Import with one click (or copy the files from [`blueprints/`](blueprints/automation/milesight_lorawan)):

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

Each one has an editable action list (notification by default) – point it at your phone, Telegram, e-mail etc.

### Settings confirmation

After a setting is sent (e.g. *Reporting interval*), the device's **Last command** sensor shows *sent*, and
*confirmed* once the device echoes the new value (most Milesight devices do on their next uplink); the interval
entity's `confirmed_by_device` attribute shows the same. Firmware and hardware versions on the device page update
whenever the device reports them.

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

## Settings per device

Open the device's integration entry → **Configure** (⚙️). Picked the wrong model during onboarding? Change **Model** here; afterwards delete the old, now-unavailable entities from the device page.

| Setting | Devices | Default |
|---|---|---|
| Offline gap (min) – time isn't counted across longer gaps | all | 120 |
| Door left open after (min) | EM300-MCS | 10 |
| CO2 limit (ppm) | AM300 range, EM500-CO2 | 1000 |
| Empty distance (mm) – for fill level % | EM400 range | 0 (off) |
| Running above (A) – for run time and starts | CT range | 0.5 |
| Voltage for power estimate (V) | CT range | 0 (off) |
| Count as empty after (min at 0 people / vacant) | VS121, VS321, VS340, VS341, VS370, VS373, GS601 | 2 |
| Opening hour / closing hour / open days (for utilisation %) | VS-range, GS601 | 08–17, Mon–Fri |

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
