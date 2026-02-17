"""
Fetch irregular geo boundary (polygon) for a location from OpenStreetMap Nominatim.
Used when the location is an administrative area (e.g. Taipei City) so we can
search only inside the boundary instead of the rectangular viewport.
"""
import time
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_DELAY_S = 1.1  # respect usage policy (max 1 req/sec)

_last_boundary_error = None


def get_last_boundary_error():
    """Return the last boundary fetch error message, or None."""
    return _last_boundary_error


def fetch_boundary_geojson(location_string, timeout=15):
    """
    Fetch boundary polygon for a location from Nominatim (OSM).
    Returns a GeoJSON geometry dict (e.g. {"type": "Polygon", "coordinates": [...]})
    or None if not available. Coordinates are [lng, lat] per GeoJSON spec.
    """
    global _last_boundary_error
    _last_boundary_error = None
    if not location_string or not location_string.strip():
        return None
    params = {
        "q": location_string.strip(),
        "format": "json",
        "polygon_geojson": 1,
        "limit": 10,
    }
    headers = {"User-Agent": "GooglePOICrawler/1.0 (boundary fetch)"}
    try:
        time.sleep(NOMINATIM_DELAY_S)
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if not data or not isinstance(data, list):
            return None
        # Prefer administrative/place boundaries (city, region); then any Polygon/MultiPolygon
        admin_types = ("administrative", "city", "town", "village", "municipality", "place", "state", "county")
        candidates = []
        for item in data:
            geojson = item.get("geojson")
            if not geojson or not isinstance(geojson, dict):
                continue
            gtype = geojson.get("type")
            coords = geojson.get("coordinates")
            if not coords or gtype not in ("Polygon", "MultiPolygon"):
                continue
            item_type = (item.get("type") or "").lower()
            is_admin = item_type in admin_types or (item.get("class") or "") == "boundary"
            candidates.append((0 if is_admin else 1, geojson))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        geojson = candidates[0][1]
        print(f"[Boundary] Got {geojson.get('type')} for {location_string.strip()!r}", flush=True)
        return geojson
    except requests.RequestException as e:
        _last_boundary_error = str(e)
        print(f"[Boundary] Request error: {e}", flush=True)
        return None
    except (KeyError, TypeError) as e:
        _last_boundary_error = f"Unexpected response: {e}"
        print(f"[Boundary] {_last_boundary_error}", flush=True)
        return None
