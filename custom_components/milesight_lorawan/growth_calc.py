"""Growth-rate analytics for a downward-facing distance sensor (EM500-UDL / EM400-MUD) over a crop canopy or a
flock.

The sensor is mounted a known height above the ground and reports the distance down to the surface below it
(the crop canopy, or the backs of the birds). So::

    height = mount_height - distance

and the change in that height over time is the growth rate. Everything here is pure (no Home Assistant): the
runtime feeds in the mount height and a list of *daily* height samples ``[(day, height_mm), ...]`` where ``day`` is
an increasing integer (a local-date ordinal) and the height is that day's median, which smooths out a single noisy
reading (and, for a flock, the birds moving under the sensor). It returns the numbers the card shows.
"""
from __future__ import annotations


def height_mm(mount_mm, distance_mm):
    """Canopy / flock-top height above the ground, clamped at 0 (never negative)."""
    if mount_mm is None or distance_mm is None:
        return None
    return max(0.0, float(mount_mm) - float(distance_mm))


def _median(xs):
    vals = sorted(float(x) for x in xs if x is not None)
    n = len(vals)
    if n == 0:
        return None
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _slope_mm_per_day(samples):
    """Least-squares slope of height(mm) against day. Needs at least two distinct days; else None."""
    pts = [(float(d), float(h)) for d, h in samples if h is not None]
    if len({d for d, _ in pts}) < 2:
        return None
    n = len(pts)
    sx = sum(d for d, _ in pts)
    sy = sum(h for _, h in pts)
    sxx = sum(d * d for d, _ in pts)
    sxy = sum(d * h for d, h in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    return (n * sxy - sx * sy) / denom


def rate_cm_day_recent(samples, now_day, window_days=7):
    """Recent growth rate (cm/day) — the slope over the last ``window_days`` days of samples."""
    recent = [s for s in samples if s[0] >= now_day - window_days]
    m = _slope_mm_per_day(recent)
    return None if m is None else round(m / 10.0, 2)


def rate_cm_day_life(samples):
    """Lifetime average growth rate (cm/day) — total rise divided by the days between first and last sample."""
    pts = [s for s in samples if s[1] is not None]
    if len(pts) < 2:
        return None
    (d0, h0), (d1, h1) = pts[0], pts[-1]
    days = d1 - d0
    if days <= 0:
        return None
    return round((h1 - h0) / days / 10.0, 2)


def fold_day(log, day, height, *, cap=400):
    """Append / replace *day*'s median height in a daily log (a list of ``[day, height_mm]``), newest last.

    ``height`` is the day's median so far. If the last entry is the same day it is replaced (the running median),
    otherwise a new day is appended. The log is capped to the most recent ``cap`` days.
    """
    out = [row for row in log if row[0] != day]
    out.append([day, height])
    out.sort(key=lambda r: r[0])
    return out[-cap:]


def summary(mount_mm, samples, now_day, *, current_mm=None, start_day=None, target_mm=None, kind="crop"):
    """The full growth picture for the card.

    ``samples`` are the finalised daily medians; ``current_mm`` (optional) is today's live height, which overrides
    today's sample so the headline tracks the latest reading. ``start_day`` is the auto-detected first day (for age);
    ``target_mm`` (optional) drives the projection.
    """
    pts = [(int(d), float(h)) for d, h in samples if h is not None]
    if current_mm is not None:
        pts = [p for p in pts if p[0] != now_day] + [(now_day, float(current_mm))]
    pts.sort(key=lambda p: p[0])
    cur = pts[-1][1] if pts else (float(current_mm) if current_mm is not None else None)
    first = pts[0] if pts else None
    start = start_day if start_day is not None else (first[0] if first else now_day)
    days = max(0, now_day - start)
    total_mm = (cur - first[1]) if (first is not None and cur is not None) else None
    r_recent = rate_cm_day_recent(pts, now_day)
    r_life = rate_cm_day_life(pts)
    to_target = None
    if target_mm and cur is not None and r_recent and r_recent > 0 and cur < target_mm:
        to_target = round((target_mm - cur) / 10.0 / r_recent)
    return {
        "kind": kind,
        "height_cm": None if cur is None else round(cur / 10.0, 1),
        "mount_mm": None if mount_mm is None else round(mount_mm),
        "distance_mm": None if (mount_mm is None or cur is None) else round(mount_mm - cur),
        "rate_cm_day": r_recent,            # recent (window) rate — the headline
        "rate_cm_day_life": r_life,         # lifetime average
        "total_cm": None if total_mm is None else round(total_mm / 10.0, 1),
        "days": days,
        "target_cm": None if not target_mm else round(target_mm / 10.0, 1),
        "to_target_days": to_target,
        "points": [[int(d), round(h / 10.0, 1)] for d, h in pts],   # cm, oldest→newest (sparkline / debugging)
    }
