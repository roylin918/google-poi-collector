"""
Config and session persistence.
- API key: from GOOGLE_PLACES_API_KEY env or config.json.
- Session: keywords, location, attribute checkboxes, max_pages, max_results, language, region.
"""
import json
import os
from pathlib import Path

# Project root (directory containing this file)
PROJECT_ROOT = Path(__file__).resolve().parent
SESSION_PATH = PROJECT_ROOT / "session.json"
CONFIG_PATH = PROJECT_ROOT / "config.json"

# Default session values
DEFAULT_SESSION = {
    "keywords": "",
    "location": "",
    "max_pages": 10,
    "max_results": None,  # None = no cap
    "language_code": "en",
    "region_code": "",
    "primary_types": [],  # optional: e.g. ["restaurant", "cafe"] to limit POI types (Table A place types)
    "attributes": [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "types",
        "businessStatus",
        "rating",
        "userRatingCount",
        "nationalPhoneNumber",
        "websiteUri",
        "googleMapsUri",
    ],
}


def get_api_key():
    """Read API key from GOOGLE_PLACES_API_KEY env or config.json. Returns None if missing."""
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if key and key.strip():
        return key.strip()
    # Try project-root config first, then current working directory (in case app is run from elsewhere)
    for config_path in (CONFIG_PATH, Path(os.getcwd()) / "config.json"):
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    raw = f.read().strip()
                if not raw:
                    if config_path == CONFIG_PATH:
                        print(f"[Config] {config_path} is empty.", flush=True)
                    continue
                data = json.loads(raw)
                key = (data.get("api_key") or data.get("API_KEY") or "").strip()
                if key:
                    return key
            except (json.JSONDecodeError, IOError) as e:
                if config_path == CONFIG_PATH:
                    print(f"[Config] Could not read {config_path}: {e}", flush=True)
    return None


def load_session():
    """Load session from session.json. Returns dict with defaults for missing keys."""
    out = DEFAULT_SESSION.copy()
    if not SESSION_PATH.exists():
        return out
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in out:
            if k in data:
                out[k] = data[k]
        if "attributes" in data and isinstance(data["attributes"], list):
            out["attributes"] = data["attributes"]
    except (json.JSONDecodeError, IOError):
        pass
    return out


def save_session(keywords, location, max_pages, max_results, language_code, region_code, primary_types, attributes):
    """Persist session to session.json."""
    data = {
        "keywords": keywords,
        "location": location,
        "max_pages": max_pages,
        "max_results": max_results,
        "language_code": language_code or "en",
        "region_code": region_code or "",
        "primary_types": list(primary_types) if primary_types else [],
        "attributes": list(attributes),
    }
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
