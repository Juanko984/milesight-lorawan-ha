"""Constants for the Milesight LoRaWAN integration."""

DOMAIN = "milesight_lorawan"
MANUFACTURER = "Milesight"

# Config entry types
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_HUB = "hub"
ENTRY_TYPE_DEVICE = "device"

# Hub settings
CONF_TOPIC = "topic"
CONF_PAYLOAD_ENCODING = "payload_encoding"
CONF_DOWNLINK_TOPIC = "downlink_topic"
CONF_DOWNLINK_FORMAT = "downlink_format"
DEFAULT_DOWNLINK_TOPIC = "milesight/downlink/{deveui}"
DOWNLINK_MILESIGHT = "milesight"
DOWNLINK_CHIRPSTACK = "chirpstack"
DOWNLINK_FPORT = 85
DEFAULT_TOPIC = "milesight/uplink/#"
CONF_EXTRA_TOPICS = "extra_topics"              # ACK / join / gateway status topics (comma separated)
CONF_GATEWAY_OFFLINE_MIN = "gateway_offline_min"
DEFAULT_GATEWAY_OFFLINE_MIN = 15
ENCODING_BASE64 = "base64"
ENCODING_HEX = "hex"

# Device settings
CONF_DEVEUI = "deveui"
CONF_MODEL = "model"

# Device options
CONF_MAX_GAP_MIN = "max_gap_min"
CONF_LEFT_OPEN_MIN = "left_open_min"
CONF_EMPTY_GRACE_MIN = "empty_grace_min"
CONF_OPEN_HOUR = "open_hour"
CONF_CLOSE_HOUR = "close_hour"
CONF_OPEN_DAYS = "open_days"
CONF_CO2_LIMIT = "co2_limit"
CONF_INSTALL_HEIGHT_MM = "install_height_mm"
CONF_AREA = "area"
CONF_METER_TYPE = "meter_type"
CONF_METER_UNIT = "meter_unit"
CONF_METER_PPU = "meter_pulses_per_unit"
CONF_METER_OFFSET = "meter_offset"
CONF_METER_SOURCE = "meter_source"
CONF_AUTO_BACKFILL = "auto_backfill"
METER_TYPES = ["none", "water", "gas", "energy"]
METER_UNITS = {"water": ["L", "m³", "gal", "ft³"], "gas": ["m³", "ft³"], "energy": ["kWh", "Wh"]}
CONF_CONFIRMED_DOWNLINKS = "confirmed_downlinks"
CONF_RETRIES = "downlink_retries"
DEFAULT_RETRIES = 2
RETRY_AFTER_UPLINKS = 2                         # Class A: resend after this many uplinks without an answer
CONF_DISPLAY_MAX_BYTES = "display_max_bytes"
DEFAULT_DISPLAY_MAX_BYTES = 51                  # fits every EU868 / AS923 data rate
CONF_BATTERY_LOW = "battery_low_pct"
DEFAULT_BATTERY_LOW = 20
CONF_RUN_THRESHOLD_A = "run_threshold_a"
CONF_MAINS_VOLTAGE = "mains_voltage"

DEFAULT_MAX_GAP_MIN = 120
DEFAULT_LEFT_OPEN_MIN = 10
DEFAULT_EMPTY_GRACE_MIN = 2
DEFAULT_OPEN_HOUR = 8
DEFAULT_CLOSE_HOUR = 17
DEFAULT_CO2_LIMIT = 1000
DEFAULT_RUN_THRESHOLD_A = 0.5
DEFAULT_OPEN_DAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Dispatcher signals
SIGNAL_UPLINK = f"{DOMAIN}_uplink_{{}}"   # .format(deveui)
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"   # .format(deveui)
SIGNAL_FLEET = f"{DOMAIN}_fleet"            # any device changed online / battery state
SIGNAL_EVENT = f"{DOMAIN}_event_{{}}"     # .format(deveui), args: key, event_type
SIGNAL_NOTIFY = f"{DOMAIN}_notify_{{}}"   # .format(deveui), args: notification dict (ack / join / error)
SIGNAL_GATEWAY = f"{DOMAIN}_gateway_{{}}"  # .format(hub entry_id): gateway list / stats changed
SIGNAL_GATEWAY_NEW = f"{DOMAIN}_gateway_new_{{}}"  # .format(hub entry_id), args: gateway id

STORAGE_VERSION = 1
TICK_SECONDS = 60
