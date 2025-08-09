# Contributing

Thanks for your interest in contributing! Please follow the steps below to get started.

## Development Setup
1. Python 3.10+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt --break-system-packages
   ```
3. Optional: install Playwright browsers if you enable dynamic scraping:
   ```bash
   python -m playwright install
   ```
4. Run the app:
   ```bash
   streamlit run streamlit_app.py
   ```

## Branching and PRs
- Create a feature branch from `main`.
- Keep edits focused and small; add tests or sample data when appropriate.
- Ensure the app starts and basic flows work (upload BOM, run scrapers, downloads).
- Use clear PR titles and include a summary of changes.

## Code Style
- Python: PEP8-ish, black-compatible formatting preferred.
- Keep functions small and readable; avoid deep nesting.
- Prefer pure functions where possible, and handle exceptions gracefully.

## Scrapers
- Use respectful headers and reasonable timeouts.
- Avoid heavy traffic; consider batching and caching.
- Add site-specific rules under `app/scrapers/` and wire them in `app/runner.py`.

## Security and Privacy
- Do not commit secrets; use environment variables.
- Avoid scraping where prohibited by robots.txt or TOS.

## Licensing
- By contributing, you agree your contributions are licensed under the MIT License.