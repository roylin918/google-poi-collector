"""
Google Places API (New) and Geocoding API client.
- geocode_with_bounds(location_string, ...) -> (lat, lng, sw_lat, sw_lng, ne_lat, ne_lng) or None
- text_search(...) -> (places, next_page_token)
- get_last_geocode_error() -> str or None (reason when geocode failed)
"""
import requests

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

_last_geocode_error = None


def get_last_geocode_error():
    """Return the last Geocoding API error message, or None."""
    return _last_geocode_error


def geocode_with_bounds(location_string, api_key, language_code=None):
    """
    Geocode a location string and return center plus optional viewport bounds.
    Returns (lat, lng, sw_lat, sw_lng, ne_lat, ne_lng) or (lat, lng, None, None, None, None) when no viewport.
    On failure returns None; use get_last_geocode_error() for the reason.
    Bounds are from the first result's geometry.viewport (covers the full area for cities/regions).
    """
    global _last_geocode_error
    _last_geocode_error = None
    if not location_string or not api_key:
        return None
    params = {"address": location_string, "key": api_key}
    if language_code:
        params["language"] = language_code
    try:
        r = requests.get(GEOCODE_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")
        if status != "OK" or not data.get("results"):
            msg = data.get("error_message") or status or "No results"
            _last_geocode_error = f"Geocoding API: {status} — {msg}"
            print(f"[Geocode] {_last_geocode_error}", flush=True)
            return None
        geo = data["results"][0]["geometry"]
        loc = geo["location"]
        lat, lng = loc["lat"], loc["lng"]
        bounds = None
        if "viewport" in geo:
            vp = geo["viewport"]
            ne = vp.get("northeast") or vp.get("high")
            sw = vp.get("southwest") or vp.get("low")
            if ne and sw:
                ne_lat = ne.get("lat") if "lat" in (ne or {}) else ne.get("latitude")
                ne_lng = ne.get("lng") if "lng" in (ne or {}) else ne.get("longitude")
                sw_lat = sw.get("lat") if "lat" in (sw or {}) else sw.get("latitude")
                sw_lng = sw.get("lng") if "lng" in (sw or {}) else sw.get("longitude")
                if None not in (ne_lat, ne_lng, sw_lat, sw_lng):
                    bounds = (sw_lat, sw_lng, ne_lat, ne_lng)
        if bounds:
            print(f"[Geocode] OK -> ({lat}, {lng}) bounds (sw={bounds[0]:.4f},{bounds[1]:.4f} ne={bounds[2]:.4f},{bounds[3]:.4f})", flush=True)
        else:
            print(f"[Geocode] OK -> ({lat}, {lng})", flush=True)
        return (lat, lng, *(bounds if bounds else (None, None, None, None)))
    except requests.RequestException as e:
        _last_geocode_error = str(e)
        print(f"[Geocode] {_last_geocode_error}", flush=True)
        return None
    except (KeyError, TypeError) as e:
        _last_geocode_error = f"Unexpected response: {e}"
        print(f"[Geocode] {_last_geocode_error}", flush=True)
        return None


def text_search(
    text_query,
    lat,
    lng,
    radius_m,
    field_mask,
    api_key,
    page_token=None,
    language_code=None,
    region_code=None,
    location_bounds=None,
):
    """
    Places API (New) Text Search.
    location_bounds: optional (sw_lat, sw_lng, ne_lat, ne_lng). When set, uses locationRestriction
    rectangle to search the full area (e.g. whole city); otherwise uses locationBias circle.
    Returns (places_list, next_page_token). next_page_token is None when no more pages.
    Raises requests.RequestException or returns ([], None) on API error; check response status.
    """
    # Text Search response field mask: use "places." prefix for each field; include nextPageToken for pagination
    mask_list = field_mask if isinstance(field_mask, (list, tuple)) else [f.strip() for f in field_mask.split(",")]
    mask_list = [m if m.startswith("places.") else f"places.{m}" for m in mask_list if m]
    if not mask_list:
        mask_list = ["places.id", "places.displayName", "places.formattedAddress", "places.location"]
    if "nextPageToken" not in mask_list:
        mask_list.append("nextPageToken")
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join(mask_list),
    }
    body = {"textQuery": text_query, "pageSize": 20}
    if location_bounds and len(location_bounds) >= 4 and all(x is not None for x in location_bounds):
        sw_lat, sw_lng, ne_lat, ne_lng = location_bounds[0], location_bounds[1], location_bounds[2], location_bounds[3]
        # Ensure low lat <= high lat (Places API requirement)
        body["locationRestriction"] = {
            "rectangle": {
                "low": {"latitude": min(sw_lat, ne_lat), "longitude": min(sw_lng, ne_lng)},
                "high": {"latitude": max(sw_lat, ne_lat), "longitude": max(sw_lng, ne_lng)},
            }
        }
    else:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius_m),
            }
        }
    if page_token:
        body["pageToken"] = page_token
    if language_code:
        body["languageCode"] = language_code
    if region_code:
        body["regionCode"] = region_code

    r = requests.post(TEXT_SEARCH_URL, json=body, headers=headers, timeout=30)
    if r.status_code == 429:
        msg = "Rate limit (429). Try again later."
        print(f"[Places API] {msg}", flush=True)
        raise requests.RequestException(msg)
    if r.status_code >= 400:
        try:
            err_body = r.json()
            err_info = err_body.get("error", {})
            api_msg = err_info.get("message") or err_info.get("status") or r.text[:200]
        except Exception:
            api_msg = r.text[:200] if r.text else ""
        msg = f"Places API {r.status_code}: {api_msg}"
        print(f"[Places API] {msg}", flush=True)
        raise requests.RequestException(msg)
    r.raise_for_status()
    data = r.json()
    places = data.get("places") or []
    next_token = data.get("nextPageToken")
    n = len(places)
    print(f"[Places API] Response: {n} places", flush=True)
    return (places, next_token)
