"""Regional parameters (RP002). b1: EU868."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    datarates: tuple[str, ...]                  # DR index → Semtech datr
    rx2_freq: float
    rx2_dr: int
    max_payload: tuple[int, ...]                # DR index → max MACPayload (N)
    cflist: tuple[float, ...]                   # extra channels sent in the join-accept
    power: int                                  # dBm for downlinks
    rx2_power: int
    join_delay1: int = 5
    join_delay2: int = 6

    def dr_of(self, datr: str) -> int | None:
        try:
            return self.datarates.index(datr)
        except ValueError:
            return None

    def sf_of(self, datr: str) -> int | None:
        try:
            return int(datr.upper().split("BW")[0].removeprefix("SF"))
        except (ValueError, AttributeError):
            return None

    def rx1(self, freq: float, datr: str, rx1_dr_offset: int = 0) -> tuple[float, str]:
        dr = self.dr_of(datr)
        if dr is None:
            return freq, datr
        return freq, self.datarates[max(0, min(len(self.datarates) - 1, dr - rx1_dr_offset))]

    def cflist_bytes(self) -> bytes:
        out = b"".join(int(round(f * 10000)).to_bytes(3, "little") for f in self.cflist[:5])
        out += bytes(15 - len(out))
        return out + b"\x00"                    # CFListType 0: frequencies


EU868 = Region(
    name="EU868",
    datarates=("SF12BW125", "SF11BW125", "SF10BW125", "SF9BW125", "SF8BW125", "SF7BW125", "SF7BW250"),
    rx2_freq=869.525, rx2_dr=0,
    max_payload=(59, 59, 59, 123, 230, 230, 230),
    cflist=(867.1, 867.3, 867.5, 867.7, 867.9),
    power=14, rx2_power=27,
)
REGIONS = {"EU868": EU868}


def airtime_ms(sf: int, size: int, bw_khz: int = 125, cr: int = 1, preamble: int = 8, crc: bool = False) -> float:
    """Time on air of a LoRa frame (Semtech AN1200.13) – for the per-gateway duty-cycle budget."""
    tsym = (2 ** sf) / (bw_khz * 1000) * 1000
    de = 1 if sf >= 11 and bw_khz == 125 else 0
    n = 8 + max(math.ceil((8 * size - 4 * sf + 28 + (16 if crc else 0)) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (preamble + 4.25) * tsym + n * tsym
