# Google POI Crawler

Web app to search Google Places by keyword and location, choose which attributes to fetch, then export results to CSV and preview them on an interactive map.

## How it works

1. **Geocode** — Your location string is geocoded to a center point and viewport bounds (or a single point for addresses).
2. **Optional boundary** — For cities/regions with a meaningful area, the app can fetch an **irregular boundary polygon** from OpenStreetMap (e.g. Taipei City). Searches are limited to cells that intersect this shape, and final POIs are filtered to those inside the boundary — so you get results *inside* the shape, not just a bounding box.
3. **Adaptive grid search** — The crawler starts with **one coarse cell** covering the full area. It calls the Places Text Search API per cell. When a cell returns the API maximum (~60 results), that cell is **subdivided into 2×2** and the sub-cells are queued. Subdivision continues only where needed, up to a max depth. This keeps API usage low while still discovering all results in dense areas.
4. **Merge & dedupe** — Results from all cells are merged and deduplicated by place ID.
5. **Export** — You choose which Place fields to fetch (name, address, rating, phone, website, etc.). Results can be previewed on an interactive map and downloaded as CSV.

**What makes it unique** — Unlike a fixed fine grid over the whole area, the **on-demand subdivision** (refine only when a cell hits the cap) reduces API calls. The **OSM boundary integration** lets you crawl POIs inside irregular geographic shapes (city limits, districts) instead of a rectangle, which is rare in typical Place-search workflows.

## Setup

1. **Virtual environment** (recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **API key**: Enable **Places API (New)** and **Geocoding API** in [Google Cloud Console](https://console.cloud.google.com/), create an API key, and either:
   - Set env: `export GOOGLE_PLACES_API_KEY=your_key`
   - Or create `config.json` in the project root: `{"api_key": "your_key"}`  
   (Do not commit `config.json` or `.env`.)

## Run

```bash
python app_web.py
```

Then open **http://127.0.0.1:5001** in your browser. Use the form to enter keywords and location, set options, choose attributes, and click **Start crawl**. Progress and errors appear on the page; when done, use **Open map** and **Download CSV**.

## Session

Keywords, location, attribute checkboxes, max pages, max results, language, and region are saved to `session.json` when you start a crawl and are restored when you open the app again.
