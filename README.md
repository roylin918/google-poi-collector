# Google POI Crawler

Web app to search Google Places by keyword and location, choose which attributes to fetch, then export results to CSV and preview them on an interactive map.

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
