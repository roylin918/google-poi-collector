"""
Crawl POIs via Google Places Text Search: geocode -> paginate -> merge/dedup.
When location has viewport bounds, starts with a single coarse cell (full area) and
subdivides into 2×2 only when a cell returns the API max (~60 results), to minimize
API calls. For irregular boundaries (e.g. Taipei City), uses OSM boundary polygon to
search only inside the shape. Returns list of place dicts and (center_lat, center_lng)
for map/CSV export.
"""
import time
from collections import deque

from shapely.geometry import box, shape, Point
from shapely.prepared import prep

from boundary import fetch_boundary_geojson
from places_client import geocode_with_bounds, text_search, get_last_geocode_error

RADIUS_M = 20000  # 20 km default for locationBias
PAGE_DELAY_S = 0.3  # delay between pages to reduce rate limit risk
CELL_DELAY_S = 0.5  # delay between grid cells when using grid search
# Dynamic refinement: when a cell returns >= this many results, subdivide into 2×2 and re-search
REFINEMENT_RESULT_THRESHOLD = 60
MAX_REFINEMENT_DEPTH = 5  # max subdivision levels (1 -> 2×2 -> 4×4 -> 8×8 -> 16×16 -> 32×32)
MIN_CELL_DEGREES = 0.003  # don't subdivide if cell lat or lng span is smaller


def run_crawl(
    keywords,
    location,
    field_list,
    api_key,
    progress_callback,
    max_pages=10,
    max_results=None,
    language_code=None,
    region_code=None,
):
    """
    Run the full crawl flow. progress_callback(status, message, count, errors_list).
    Always starts with the roughest grid (one cell) and subdivides only when a cell
    hits the result limit (~60), to reduce API calls. For irregular boundaries
    (e.g. city), uses OSM boundary polygon when available.
    Returns (places_list, center_lat, center_lng, cells_searched, boundary_geojson).
    On failure returns (None, None, None, [], None).
    """
    errors = []
    print("[Crawl] Request received.", flush=True)

    def report(status, message, count=0, log_errors=False):
        if log_errors:
            for e in errors:
                progress_callback("log", e, 0, [])
        progress_callback(status, message, count, [])

    # Validate
    if not (keywords and keywords.strip()):
        print("[Crawl] Skipped: keywords required.", flush=True)
        report("error", "Keywords are required.", 0)
        return (None, None, None, [], None)
    if not (location and location.strip()):
        print("[Crawl] Skipped: location required.", flush=True)
        report("error", "Location is required.", 0)
        return (None, None, None, [], None)
    if not api_key:
        print("[Crawl] Skipped: API key missing.", flush=True)
        report("error", "API key is missing. Set GOOGLE_PLACES_API_KEY or config.json.", 0)
        return (None, None, None, [], None)
    field_mask = [f for f in (field_list or []) if f]
    if not field_mask:
        field_mask = ["id", "displayName", "formattedAddress", "location"]

    print(f"[Crawl] Starting: keywords={keywords.strip()!r}, location={location.strip()!r}", flush=True)
    report("status", "Geocoding…", 0)
    geocoded = geocode_with_bounds(location.strip(), api_key, language_code=language_code)
    if not geocoded:
        err_msg = get_last_geocode_error() or ("Geocode failed for: " + location.strip())
        errors.append(err_msg)
        report("error", "Geocode failed. " + err_msg, 0, log_errors=True)
        return (None, None, None, [], None)

    center_lat, center_lng = geocoded[0], geocoded[1]
    sw_lat, sw_lng, ne_lat, ne_lng = geocoded[2], geocoded[3], geocoded[4], geocoded[5]
    # Use viewport bounds when available and span is meaningful (whole city/region, not a point)
    use_bounds = (
        sw_lat is not None
        and (ne_lat - sw_lat) >= 0.01
        and (ne_lng - sw_lng) >= 0.01
    )
    location_bounds = (sw_lat, sw_lng, ne_lat, ne_lng) if use_bounds else None
    text_query = f"{keywords.strip()} in {location.strip()}"

    # Optional: fetch irregular boundary from OSM (e.g. Taipei City polygon)
    boundary_geojson = None
    boundary_shape = None
    if use_bounds and location.strip():
        report("status", "Fetching boundary…", 0)
        boundary_geojson = fetch_boundary_geojson(location.strip())
        if boundary_geojson:
            try:
                boundary_geom = shape(boundary_geojson)
                boundary_shape = prep(boundary_geom)
                # Use boundary bbox so we don't search outside the shape (bounds = minx, miny, maxx, maxy = lng, lat, lng, lat)
                minx, miny, maxx, maxy = boundary_geom.bounds
                sw_lat, sw_lng, ne_lat, ne_lng = miny, minx, maxy, maxx
                location_bounds = (sw_lat, sw_lng, ne_lat, ne_lng)
                report("status", "Using geo boundary (irregular shape).", 0)
            except Exception as e:
                print(f"[Crawl] Boundary shape error: {e}, using viewport.", flush=True)
                boundary_geojson = None
                boundary_shape = None

    # Queue of (cell_bounds, depth). Start with one coarse cell; subdivide only when cell hits result cap.
    def subdivide_cell(c_sw_lat, c_sw_lng, c_ne_lat, c_ne_lng):
        mid_lat = (c_sw_lat + c_ne_lat) / 2
        mid_lng = (c_sw_lng + c_ne_lng) / 2
        return [
            (c_sw_lat, c_sw_lng, mid_lat, mid_lng),
            (c_sw_lat, mid_lng, mid_lat, c_ne_lng),
            (mid_lat, c_sw_lng, c_ne_lat, mid_lng),
            (mid_lat, mid_lng, c_ne_lat, c_ne_lng),
        ]

    def cell_big_enough(c_sw_lat, c_sw_lng, c_ne_lat, c_ne_lng):
        return (c_ne_lat - c_sw_lat) >= MIN_CELL_DEGREES and (c_ne_lng - c_sw_lng) >= MIN_CELL_DEGREES

    def cell_inside_boundary(c_sw_lat, c_sw_lng, c_ne_lat, c_ne_lng):
        """True if cell (rectangle) intersects the boundary polygon, or cell center is inside (fallback for small cells)."""
        if boundary_shape is None:
            return True
        # Shapely box(xmin, ymin, xmax, ymax) = (lng, lat, lng, lat)
        cell_box = box(c_sw_lng, c_sw_lat, c_ne_lng, c_ne_lat)
        if boundary_shape.intersects(cell_box):
            return True
        # Fallback: small cells can be rejected by simplified boundaries; include if center is inside
        center_lng = (c_sw_lng + c_ne_lng) / 2
        center_lat = (c_sw_lat + c_ne_lat) / 2
        return boundary_shape.contains(Point(center_lng, center_lat))

    # Always start with the roughest grid: one cell (full bounds). Subdivide only when needed.
    cell_queue = deque()
    if use_bounds and location_bounds is not None:
        if cell_inside_boundary(*location_bounds):
            cell_queue.append((location_bounds, 0))
        report("status", "Starting with 1 coarse cell (will refine if needed).", 0)
    else:
        cell_queue.append((location_bounds, 0))

    all_places = []
    seen_ids = set()
    total_cells_done = 0
    cells_refined = 0
    cells_searched = []  # list of (sw_lat, sw_lng, ne_lat, ne_lng) for map overlay

    while cell_queue and (not max_results or len(all_places) < max_results):
        cell_bounds, depth = cell_queue.popleft()
        if cell_bounds is not None:
            cells_searched.append(cell_bounds)
        total_cells_done += 1
        report("status", f"Cell #{total_cells_done} (depth {depth})… {len(all_places)} places.", len(all_places))

        cell_places = []
        cell_api_returned = 0  # total results returned by API for this cell (before dedup) – used to decide subdivision
        page_token = None
        page = 0
        cell_done = False
        request_error = False

        while not cell_done and not request_error:
            page += 1
            if page > max_pages:
                break
            try:
                places_batch, next_token = text_search(
                    text_query,
                    center_lat,
                    center_lng,
                    RADIUS_M,
                    field_mask,
                    api_key,
                    page_token=page_token,
                    language_code=language_code or None,
                    region_code=region_code or None,
                    location_bounds=cell_bounds,
                )
            except Exception as e:
                errors.append(str(e))
                report("status", f"Request error: {e}", len(all_places), log_errors=True)
                request_error = True
                break

            cell_api_returned += len(places_batch)
            for p in places_batch:
                pid = p.get("id") or (p.get("name") or "").replace("places/", "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_places.append(p)
                    cell_places.append(p)
                if max_results and len(all_places) >= max_results:
                    cell_done = True
                    break

            report("status", f"Page {page}… {len(all_places)} places.", len(all_places))
            if max_results and len(all_places) >= max_results:
                cell_done = True
                break
            if not next_token:
                cell_done = True
                break
            page_token = next_token
            time.sleep(PAGE_DELAY_S)

        # Subdivide if this cell hit the API cap (60 results per query) – use API count, not new-only, so sub-cells subdivide too
        hit_max = cell_api_returned >= REFINEMENT_RESULT_THRESHOLD
        if (
            hit_max
            and cell_bounds is not None
            and depth < MAX_REFINEMENT_DEPTH
            and cell_big_enough(*cell_bounds)
        ):
            c_sw_lat, c_sw_lng, c_ne_lat, c_ne_lng = cell_bounds
            sub_count = 0
            for sub in subdivide_cell(c_sw_lat, c_sw_lng, c_ne_lat, c_ne_lng):
                if cell_inside_boundary(*sub):
                    cell_queue.append((sub, depth + 1))
                    sub_count += 1
            if sub_count:
                cells_refined += 1
                report("status", f"Refining cell (API returned {cell_api_returned}) → {sub_count} sub-cells queued.", len(all_places))

        time.sleep(CELL_DELAY_S)

    if cells_refined:
        report("status", f"Done. {len(all_places)} places from {total_cells_done} cells ({cells_refined} refined).", len(all_places))

    # Deduplicate by id (already avoided in loop; one more pass to be safe)
    by_id = {}
    for p in all_places:
        pid = p.get("id") or (p.get("name") or "").replace("places/", "")
        if pid and pid not in by_id:
            by_id[pid] = p
    places = list(by_id.values())

    # If we used a geo-boundary, keep only POIs whose (lat, lng) is inside the boundary
    if boundary_geojson and places:
        try:
            boundary_geom = shape(boundary_geojson)
            boundary_prep = prep(boundary_geom)
            inside = []
            for p in places:
                loc = p.get("location")
                if isinstance(loc, dict):
                    lat, lng = loc.get("latitude"), loc.get("longitude")
                    if lat is not None and lng is not None and boundary_prep.contains(Point(lng, lat)):
                        inside.append(p)
                else:
                    inside.append(p)  # no location: keep (will be excluded from map anyway)
            if len(inside) < len(places):
                report("status", f"Filtered to {len(inside)} POIs inside boundary (removed {len(places) - len(inside)} outside).", len(inside))
            places = inside
        except Exception as e:
            print(f"[Crawl] Boundary filter error: {e}, keeping all places.", flush=True)

    if not places and not errors:
        errors.append(
            "Places API returned 0 results. In Google Cloud enable 'Places API (New)' "
            "(not the legacy Places API) and ensure the API key has access."
        )
        report("status", "No places.", 0, log_errors=True)
    return (places, center_lat, center_lng, cells_searched, boundary_geojson)
