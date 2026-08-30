"""Distance and geofence evaluation for time-clock punches.

Standard library only. PostGIS would be more precise over continental distances,
but a required Postgres extension is a real burden for a self-hosted install and
the haversine error at geofence range (a few hundred metres) is orders of
magnitude below the noise in a phone's own position fix.
"""

import math
from typing import Iterable, Optional, Tuple

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean earth radius


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points, in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def evaluate_geofence(
    sites: Iterable,
    latitude: Optional[float],
    longitude: Optional[float],
    accuracy_m: Optional[float],
    mode: str,
    pinned_site_id: Optional[int] = None,
    default_radius_m: int = 200,
) -> Tuple[str, Optional[int], Optional[float]]:
    """Decide whether a punch counts as being where it should be.

    Returns (geofence_status, work_site_id, distance_m).

    Only `require_site` is ever evaluated. `any_location` covers work-from-home and
    official business, where being far from an office is the whole point, so a
    distance verdict there would be meaningless noise on a timesheet.

    The device's own accuracy figure is credited to the employee: a fix reported as
    +/-500m against a 200m radius is a coin toss, and being wrongly marked outside
    is something a human then has to unpick. Raw `distance_m` and `accuracy_m` are
    stored regardless, so a reviewer can form their own view.

    Nothing here blocks a punch. `outside` is a flag for review, never a refusal.
    """
    if mode != "require_site":
        return ("not_applicable", None, None)
    if latitude is None or longitude is None:
        # Expected on site, but we have no fix — distinct from being outside.
        return ("unverified", None, None)

    candidates = [s for s in sites if s.is_active]
    if pinned_site_id is not None:
        candidates = [s for s in candidates if s.id == pinned_site_id]
    if not candidates:
        # Nowhere to measure against. Do not invent a verdict.
        return ("unverified", None, None)

    best_site = None
    best_distance = None
    best_inside = False
    for site in candidates:
        distance = haversine_m(latitude, longitude, site.latitude, site.longitude)
        radius = site.radius_m or default_radius_m
        inside = (distance - (accuracy_m or 0.0)) <= radius
        # Prefer any site the employee is inside; otherwise report the nearest, so
        # "312m from Head Office" is the message rather than a bare failure.
        if best_distance is None or (inside and not best_inside) or (
            inside == best_inside and distance < best_distance
        ):
            best_site, best_distance, best_inside = site, distance, inside

    return (
        "inside" if best_inside else "outside",
        best_site.id if best_site else None,
        round(best_distance, 1) if best_distance is not None else None,
    )
