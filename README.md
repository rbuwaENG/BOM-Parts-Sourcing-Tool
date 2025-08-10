#  Pickitronix 

A Streamlit-based web app to upload a Bill of Materials (BOM), search multiple suppliers for availability and pricing, and suggest alternatives with similarity scoring. Supports caching to a local database and adding new suppliers with auto-detection or manual selector mapping. Now includes integrated supplier management and a background scraping runner capable of handling 5,000+ items per run.

## Features
- BOM upload (CSV/Excel) with validation and preview
- Exact and fuzzy matching across database-cached supplier data
- Supplier scrapers (Tronic.lk, LCSC/JLCPCB placeholder, Mouser placeholder)
- Automatic HTML structure detection + manual override for new suppliers
- Weighted similarity scoring with RapidFuzz + TF-IDF
- Datasheet links (Octopart API optional) and purchase links
- Streamlit UI with filtering, sorting, color-coded similarity, and downloads
- SQLite caching with periodic update hooks
- Background scraping in batches with progress reporting

## Tech Stack
- Frontend: Streamlit
- Backend: Python
- Scraping: Requests, BeautifulSoup (Playwright optional)
- DB: SQLite via SQLAlchemy
- Matching: RapidFuzz, scikit-learn (TF-IDF)
- File parsing: Pandas, OpenPyXL
- Scheduling/Progress: Lightweight JSON progress store; background thread runner

## Project Structure
```
.
├── streamlit_app.py                # Main app; includes Supplier settings & Scraping
├── requirements.txt
├── README.md
├── .streamlit/
│   └── config.toml
├── app/
│   ├── __init__.py
│   ├── bootstrap.py (imported as bootstrap)
│   ├── db.py
│   ├── models.py
│   ├── matching.py
│   ├── datasheets.py
│   ├── scheduler.py                # progress and last-update tracking
│   ├── runner.py                   # background scraping runner
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
   pip install -r requirements.txt --break-system-packages
   ```
3. Optional: Install Playwright browsers (only if you want dynamic scraping):
   ```bash
   python -m playwright install
   ```
4. Run the app:
   ```bash
   streamlit run streamlit_app.py
   ```

## Usage
1. Open the app. Supplier Management and Scraping controls are on the main page:
   - Select a supplier, toggle active/enabled, and update sitemap JSON if needed.
   - Click “Run All Scrapers (Background)” to populate the DB (handles 5,000+ items per run, batch inserts).
   - Progress bar shows per-supplier scraped/stored counts and percentage.
2. Upload your BOM (CSV/Excel). The app normalizes common column aliases (e.g., MPN → Part_Number, Qty → Quantity).
3. Review preview, then “Upload & Process” to match against the database.
4. Filter by supplier and similarity in the sidebar, download CSV/Excel.

## Notes on Scraping
- Some suppliers have dynamic content; integrate Playwright if server-side HTML is insufficient.
- Broken product links are skipped gracefully.

## Environment Variables
- `OCTOPART_API_KEY` (optional): Enables better datasheet fetching (stub included).

## License
MIT. See `LICENSE`.

## Contributing
Please see `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `SECURITY.md`.

## Issue and PR Templates
This repository includes templates under `.github/` to help file issues and pull requests.
