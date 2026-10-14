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
DEFAULT_TOPIC = "milesight/uplink/#"
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

DEFAULT_MAX_GAP_MIN = 120
DEFAULT_LEFT_OPEN_MIN = 10
DEFAULT_EMPTY_GRACE_MIN = 2
DEFAULT_OPEN_HOUR = 8
DEFAULT_CLOSE_HOUR = 17
DEFAULT_CO2_LIMIT = 1000
DEFAULT_OPEN_DAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Dispatcher signals
SIGNAL_UPLINK = f"{DOMAIN}_uplink_{{}}"   # .format(deveui)
SIGNAL_UPDATE = f"{DOMAIN}_update_{{}}"   # .format(deveui)

STORAGE_VERSION = 1
TICK_SECONDS = 60
