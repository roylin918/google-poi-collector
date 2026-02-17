"""
Google POI Crawler – Web UI.
Run: python app_web.py  then open in browser:
  http://127.0.0.1:5001   (or set PORT=... for a different port)
"""
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template

from config import (
    PROJECT_ROOT,
    get_api_key,
    load_session,
    save_session,
    DEFAULT_SESSION,
)
from crawler import run_crawl
from export import to_csv, to_folium_map

OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MAP_FILENAME = "poi_map.html"

app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"))

# Shared crawl state (thread-safe)
_crawl_lock = threading.Lock()
_crawl_state = {
    "running": False,
    "start_time": None,
    "status": "Idle",
    "message": "",
    "count": 0,
    "errors": [],
    "csv_path": None,
    "map_path": None,
}


def _run_crawl_worker(args):
    keywords = args["keywords"]
    location = args["location"]
    field_list = args["field_list"]
    max_pages = args["max_pages"]
    max_results = args["max_results"]
    language_code = args.get("language_code") or None
    region_code = args.get("region_code") or None
    primary_types = args.get("primary_types") or []
    api_key = get_api_key()

    def progress_cb(status, message, count, _errors):
        with _crawl_lock:
            if status == "log":
                _crawl_state["errors"].append(message)
            else:
                _crawl_state["status"] = status
                _crawl_state["message"] = message
                _crawl_state["count"] = count
            if _crawl_state["start_time"]:
                _crawl_state["elapsed"] = int(time.time() - _crawl_state["start_time"])

    with _crawl_lock:
        _crawl_state["running"] = True
        _crawl_state["start_time"] = time.time()
        _crawl_state["status"] = "Starting…"
        _crawl_state["message"] = ""
        _crawl_state["count"] = 0
        _crawl_state["errors"] = []
        _crawl_state["csv_path"] = None
        _crawl_state["map_path"] = None
        _crawl_state["elapsed"] = 0

    try:
        result = run_crawl(
            keywords,
            location,
            field_list,
            api_key,
            progress_cb,
            max_pages=max_pages,
            max_results=max_results,
            language_code=language_code,
            region_code=region_code,
            primary_types=primary_types,
        )
        places = result[0]
        center_lat, center_lng = result[1], result[2]
        grid_cells = result[3] if len(result) > 3 else []
        boundary_geojson = result[4] if len(result) > 4 else None
        print(f"[Crawl] Worker finished: {len(places) if places else 0} places.", flush=True)
        with _crawl_lock:
            _crawl_state["running"] = False
            if places and len(places) > 0:
                stamp = datetime.now().strftime("%Y%m%d_%H%M")
                csv_path = OUTPUT_DIR / f"poi_results_{stamp}.csv"
                to_csv(places, csv_path)
                to_folium_map(
                    places, center_lat, center_lng, OUTPUT_DIR / MAP_FILENAME,
                    field_list=field_list, grid_cells=grid_cells, boundary_geojson=boundary_geojson,
                )
                _crawl_state["csv_path"] = csv_path.name
                _crawl_state["map_path"] = MAP_FILENAME
                _crawl_state["status"] = "Done"
                _crawl_state["message"] = f"Exported {len(places)} places."
            else:
                _crawl_state["status"] = "Done (no results)"
                errs = _crawl_state.get("errors") or []
                if errs:
                    _crawl_state["message"] = "No places to export. " + (errs[0] if errs else "")
                else:
                    _crawl_state["message"] = "No places to export. (Geocode or Places API may have failed; check API key and enabled APIs.)"
            if _crawl_state["start_time"]:
                _crawl_state["elapsed"] = int(time.time() - _crawl_state["start_time"])
    except Exception as e:
        print(f"[Crawl] Worker error: {e}", flush=True)
        with _crawl_lock:
            _crawl_state["running"] = False
            _crawl_state["status"] = "Error"
            _crawl_state["message"] = str(e)
            _crawl_state["errors"].append(str(e))
            if _crawl_state["start_time"]:
                _crawl_state["elapsed"] = int(time.time() - _crawl_state["start_time"])


ATTRIBUTE_GROUPS = [
    ("Basics", ["id", "displayName", "formattedAddress", "location", "types"]),
    ("Contact", ["nationalPhoneNumber", "internationalPhoneNumber", "websiteUri"]),
    ("Business", ["businessStatus", "rating", "userRatingCount", "priceLevel", "priceRange"]),
    ("Hours", ["currentOpeningHours", "regularOpeningHours"]),
    ("Extra", ["googleMapsUri", "plusCode", "viewport", "primaryType"]),
]


@app.route("/")
def index():
    return render_template("index.html", attribute_groups=ATTRIBUTE_GROUPS)


@app.route("/favicon.ico")
def favicon():
    """Avoid 404 when the browser requests favicon.ico."""
    return "", 204


@app.route("/api/session", methods=["GET"])
def api_get_session():
    return jsonify(load_session())


@app.route("/api/session", methods=["POST"])
def api_save_session():
    data = request.get_json() or {}
    save_session(
        data.get("keywords", ""),
        data.get("location", ""),
        data.get("max_pages", 10),
        data.get("max_results"),
        data.get("language_code", "en"),
        data.get("region_code", ""),
        data.get("primary_types", []),
        data.get("attributes", []),
    )
    return jsonify({"ok": True})


@app.route("/api/crawl", methods=["POST"])
def api_crawl():
    with _crawl_lock:
        if _crawl_state["running"]:
            return jsonify({"ok": False, "error": "Crawl already in progress"}), 400
    data = request.get_json() or {}
    keywords = (data.get("keywords") or "").strip()
    location = (data.get("location") or "").strip()
    if not keywords or not location:
        return jsonify({"ok": False, "error": "Keywords and location are required"}), 400
    field_list = data.get("attributes") or []
    if not field_list:
        field_list = ["id", "displayName", "formattedAddress", "location"]
    max_pages = min(20, max(1, int(data.get("max_pages", 10))))
    max_results = data.get("max_results")
    if max_results is not None and max_results != "":
        try:
            max_results = int(max_results)
        except (ValueError, TypeError):
            max_results = None
    language_code = (data.get("language_code") or "").strip() or None
    region_code = (data.get("region_code") or "").strip() or None
    primary_types = data.get("primary_types")
    if not isinstance(primary_types, list):
        primary_types = [x.strip() for x in (primary_types or "").split(",") if x and x.strip()] if primary_types else []
    else:
        primary_types = [str(x).strip() for x in primary_types if str(x).strip()]
    args = {
        "keywords": keywords,
        "location": location,
        "field_list": field_list,
        "max_pages": max_pages,
        "max_results": max_results,
        "language_code": language_code,
        "region_code": region_code,
        "primary_types": primary_types,
    }
    print("[Crawl] Starting background worker.", flush=True)
    threading.Thread(target=_run_crawl_worker, args=(args,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    with _crawl_lock:
        elapsed = _crawl_state.get("elapsed", 0)
        if _crawl_state["running"] and _crawl_state.get("start_time"):
            elapsed = int(time.time() - _crawl_state["start_time"])
        return jsonify({
            "running": _crawl_state["running"],
            "status": _crawl_state["status"],
            "message": _crawl_state["message"],
            "count": _crawl_state["count"],
            "errors": _crawl_state.get("errors", []),
            "elapsed": elapsed,
            "csv_path": _crawl_state.get("csv_path"),
            "map_path": _crawl_state.get("map_path"),
        })


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=(filename.endswith(".csv")))


if __name__ == "__main__":
    api_key = get_api_key()
    if api_key:
        print("[Config] API key loaded (from config.json or env).", flush=True)
    else:
        print("[Config] API key NOT FOUND. Put it in config.json: {\"api_key\": \"YOUR_KEY\"} or set GOOGLE_PLACES_API_KEY.", flush=True)
    port = int(os.environ.get("PORT", 5001))
    print(f"Open http://127.0.0.1:{port} in your browser.", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
