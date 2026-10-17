# Milesight LoRaWAN for Home Assistant

Adds Milesight LoRaWAN sensors to Home Assistant **without YAML or Node-RED**.
Connect the gateway once; every new sensor that sends data shows up under
**Settings → Devices & services → Discovered**. Click **Add**, confirm the model, give it a name – done.

## Supported devices (v0.1)

| Model | What you get |
|---|---|
| **VS121** people counter | People count, occupied (debounced), occupied since / duration, last & longest session, occupied today / yesterday, sessions, peak people + time, person-minutes, average people, utilisation % within opening hours |
| **EM300-MCS** door/window | Temperature, humidity, battery, feels-like, daily min/max, door open/closed, *door left open* alarm, open duration (live), open time & number of openings today / yesterday / this week / last week / this month / last month, longest & average opening |
| **EM300-TH** | Temperature, humidity, battery, feels-like, daily min/max |
| **EM300-SLD / EM300-ZLD** leak | As EM300-TH plus leak detected and leak statistics (same periods as door) |
| **EM300-DI** *(beta)* | As EM300-TH plus digital input statistics and pulse counter |

All devices also get RSSI, SNR and *Last seen* (diagnostic).
Durations update **every minute** (not only when the sensor reports), and day / week / month
totals roll over at local midnight using Home Assistant's time zone. Statistics are stored by
Home Assistant and survive restarts.

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

## Settings per device

Open the device's integration entry → **Configure**:

| Setting | Devices | Default |
|---|---|---|
| Offline gap (min) – time isn't counted across longer gaps | all | 120 |
| Door left open after (min) | EM300-MCS | 10 |
| Count as empty after (min at 0 people) | VS121 | 2 |
| Opening hour / closing hour / open days (for utilisation %) | VS121 | 08–17, Mon–Fri |

## Troubleshooting

* **Download diagnostics** on the device page shows the last decoded values and stored statistics – attach it to support requests.
* Debug logging:
  ```yaml
  logger:
    logs:
      custom_components.milesight_lorawan: debug
  ```
* A device stuck sending *JnReq/JnAcc* in the gateway log never gets as far as sending data; fix the join on the gateway first (RX2/channel plan, gateway downlink).

## Development

```bash
python -m pytest tests/test_pure.py          # decoders + analytics
python tests/test_runtime_stubbed.py         # hub -> device -> entity wiring
```
GitHub Actions also runs Home Assistant's `hassfest` and the HACS validator on every push.
