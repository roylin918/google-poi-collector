"""
Export crawled places to CSV and generate a folium map.
"""
import csv
import html
from pathlib import Path

import folium
from branca.element import Element

# Human-readable labels for place attributes (API field names)
FIELD_LABELS = {
    "id": "ID",
    "displayName": "Name",
    "formattedAddress": "Address",
    "location": "Location",
    "types": "Types",
    "businessStatus": "Business status",
    "rating": "Rating",
    "userRatingCount": "User rating count",
    "priceLevel": "Price level",
    "priceRange": "Price range",
    "nationalPhoneNumber": "Phone (national)",
    "internationalPhoneNumber": "Phone (international)",
    "websiteUri": "Website",
    "googleMapsUri": "Google Maps",
    "primaryType": "Primary type",
    "currentOpeningHours": "Current opening hours",
    "regularOpeningHours": "Regular opening hours",
    "plusCode": "Plus code",
    "viewport": "Viewport",
}


def _get_display_name(place):
    """Extract display name text from place."""
    dn = place.get("displayName")
    if isinstance(dn, dict) and "text" in dn:
        return dn["text"] or ""
    return str(dn or "")


def _get_location(place):
    """Extract (lat, lng) from place. Returns (None, None) if missing."""
    loc = place.get("location")
    if isinstance(loc, dict):
        return (loc.get("latitude"), loc.get("longitude"))
    return (None, None)


def _flatten_place(place):
    """Flatten one place dict for CSV row. Returns dict of column -> value."""
    row = {}
    row["place_id"] = place.get("id") or place.get("name", "").replace("places/", "")
    row["name"] = _get_display_name(place)
    lat, lng = _get_location(place)
    row["lat"] = lat if lat is not None else ""
    row["lng"] = lng if lng is not None else ""
    row["address"] = place.get("formattedAddress") or ""

    # Optional fields
    for key in (
        "businessStatus",
        "rating",
        "userRatingCount",
        "nationalPhoneNumber",
        "internationalPhoneNumber",
        "websiteUri",
        "googleMapsUri",
        "primaryType",
        "priceLevel",
        "types",
    ):
        val = place.get(key)
        if val is None:
            row[key] = ""
        elif isinstance(val, (list, tuple)):
            row[key] = ",".join(str(x) for x in val)
        elif isinstance(val, dict):
            if "text" in val:
                row[key] = val["text"]
            else:
                row[key] = str(val)
        else:
            row[key] = str(val)

    # Opening hours: simplify to string
    for key in ("currentOpeningHours", "regularOpeningHours"):
        val = place.get(key)
        if val is None:
            row[key] = ""
        elif isinstance(val, dict) and "weekdayDescriptions" in val:
            row[key] = " | ".join(val["weekdayDescriptions"])
        else:
            row[key] = str(val) if val else ""

    return row


def _format_place_value(place, key):
    """Format a single attribute value for display. Returns string."""
    if key == "id":
        return (place.get("id") or place.get("name", "").replace("places/", "")) or ""
    if key == "displayName":
        return _get_display_name(place)
    if key == "formattedAddress":
        return place.get("formattedAddress") or ""
    if key == "location":
        lat, lng = _get_location(place)
        if lat is not None and lng is not None:
            return f"{lat}, {lng}"
        return ""
    if key in ("currentOpeningHours", "regularOpeningHours"):
        val = place.get(key)
        if val is None:
            return ""
        if isinstance(val, dict) and "weekdayDescriptions" in val:
            return " | ".join(val["weekdayDescriptions"])
        return str(val) if val else ""
    val = place.get(key)
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return ", ".join(str(x) for x in val)
    if isinstance(val, dict) and "text" in val:
        return val["text"] or ""
    return str(val)


def _get_place_attributes_html(place, field_list):
    """Build HTML snippet showing selected attributes for one place (for tooltip/popup)."""
    if not field_list:
        name = _get_display_name(place)
        addr = place.get("formattedAddress") or ""
        return f"<b>{html.escape(name)}</b><br>{html.escape(addr)}"
    parts = []
    for key in field_list:
        label = FIELD_LABELS.get(key, key)
        value = _format_place_value(place, key)
        if value:
            parts.append(f"<b>{html.escape(label)}:</b> {html.escape(value)}")
    if not parts:
        name = _get_display_name(place)
        parts.append(f"<b>{html.escape(name)}</b>")
    return "<br>".join(parts)


def to_csv(places, path):
    """
    Write places to a CSV file. path can be str or Path.
    Columns include place_id, name, lat, lng, address plus any requested attributes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not places:
        return
    rows = [_flatten_place(p) for p in places]
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def to_folium_map(places, center_lat, center_lng, path, field_list=None, grid_cells=None, boundary_geojson=None):
    """
    Generate an HTML map with folium and save to path.
    field_list: optional list of attribute keys to show in tooltip/popup (same as user-selected attributes).
    grid_cells: optional list of (sw_lat, sw_lng, ne_lat, ne_lng) to draw as grid overlay.
    boundary_geojson: optional GeoJSON geometry (Polygon/MultiPolygon) for the search boundary; shown as a toggleable layer.
    POIs and Grid are in separate FeatureGroups so users can toggle them on/off via the layer control.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    m = folium.Map(location=[center_lat, center_lng], zoom_start=12)
    if not field_list:
        field_list = ["displayName", "formattedAddress"]

    # Layer: Boundary (irregular geo shape) – toggleable
    if boundary_geojson:
        fg_boundary = folium.FeatureGroup(name="Boundary", show=False)
        # Folium expects Feature or FeatureCollection; wrap geometry
        geojson_feature = {"type": "Feature", "geometry": boundary_geojson}
        folium.GeoJson(
            geojson_feature,
            style_function=lambda _: {"color": "#16a34a", "weight": 2, "fillOpacity": 0.1},
        ).add_to(fg_boundary)
        fg_boundary.add_to(m)

    # Layer: Grid cells – toggleable
    fg_grid = folium.FeatureGroup(name="Grid", show=True)
    if grid_cells:
        for sw_lat, sw_lng, ne_lat, ne_lng in grid_cells:
            folium.Rectangle(
                bounds=[[sw_lat, sw_lng], [ne_lat, ne_lng]],
                color="#2563eb",
                weight=1,
                fill=True,
                fill_color="#2563eb",
                fill_opacity=0.08,
                popup=None,
            ).add_to(fg_grid)
    fg_grid.add_to(m)

    # Layer: POIs – toggleable
    fg_pois = folium.FeatureGroup(name="POIs", show=True)
    for p in places:
        lat, lng = _get_location(p)
        if lat is None or lng is None:
            continue
        content = _get_place_attributes_html(p, field_list)
        folium.Marker(
            [lat, lng],
            popup=folium.Popup(content, max_width=400),
            tooltip=folium.Tooltip(content, sticky=True),
        ).add_to(fg_pois)
    fg_pois.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Total POI count overlay
    count = sum(1 for p in places if _get_location(p) != (None, None))
    count_html = (
        f'<div style="position: fixed; top: 10px; left: 50px; z-index: 9999; '
        'background: white; padding: 8px 14px; border-radius: 6px; '
        'box-shadow: 0 1px 5px rgba(0,0,0,0.2); font-weight: bold; font-size: 14px;">'
        f"Total: {count} POI{'' if count == 1 else 's'}"
        "</div>"
    )
    m.get_root().html.add_child(Element(count_html))
    m.save(str(path))
