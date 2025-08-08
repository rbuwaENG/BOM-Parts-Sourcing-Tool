# Streamlit BOM Parts Sourcing Website

A Streamlit-based web app to upload a Bill of Materials (BOM), search multiple suppliers for availability and pricing, and suggest alternatives with similarity scoring. Supports caching to a local database and adding new suppliers with auto-detection or manual selector mapping.

## Features
- BOM upload (CSV/Excel) with validation and preview
- Exact and fuzzy matching across database-cached supplier data
- Supplier scrapers (Tronic.lk, LCSC/JLCPCB, Mouser) with graceful fallbacks
- Automatic HTML structure detection + manual override for new suppliers
- Weighted similarity scoring with RapidFuzz + TF-IDF
- Datasheet links (Octopart API optional) and purchase links
- Streamlit UI with filtering, sorting, color-coded similarity, and downloads
- SQLite caching with periodic update hooks

## Tech Stack
- Frontend: Streamlit
- Backend: Python
- Scraping: Requests, BeautifulSoup (Playwright optional)
- DB: SQLite via SQLAlchemy
- Matching: RapidFuzz, scikit-learn (TF-IDF)
- File parsing: Pandas, OpenPyXL
- Scheduling: APScheduler or cron

## Project Structure
```
.
├── streamlit_app.py
├── requirements.txt
├── README.md
├── .streamlit/
│   └── config.toml
├── app/
│   ├── __init__.py
│   ├── db.py
│   ├── models.py
│   ├── matching.py
│   ├── datasheets.py
│   ├── scheduler.py
│   ├── utils.py
│   └── scrapers/
│       ├── __init__.py
│       ├── base.py
│       ├── auto.py
│       ├── lscs.py
│       ├── mouser.py
│       └── troniclk.py
└── data/
    ├── bom_template.csv
    └── sample_parts.csv
```

## Setup
1. Python 3.10+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Optional: Install Playwright browsers (only if you want dynamic scraping):
   ```bash
   python -m playwright install
   ```
4. Run the app:
   ```bash
   streamlit run streamlit_app.py
   ```

## Environment Variables
- `OCTOPART_API_KEY` (optional): Enables better datasheet fetching.

## Usage
1. Start the app and upload your BOM (CSV/Excel). Use the provided template.
2. Review the preview and process. The app will look up parts from cache and scrape suppliers as needed.
3. Filter results by supplier, similarity, and in-stock. Download CSV/Excel.
4. Add new suppliers via the UI: provide a search URL or homepage, let the app auto-detect, or map selectors manually.

## Data and Caching
- SQLite database stored at `data/cache.db`.
- Supplier rules and parts are persisted. First run seeds sample parts for a better demo.
- You can schedule periodic refresh using cron or `APScheduler`. See `app/scheduler.py`.

## Notes on Scraping
- Some suppliers employ anti-bot measures. The app uses headers and backs off to cached data if scraping fails.
- LCSC/Mouser can be challenging; manual mapping or Playwright may be required.

## License
MIT