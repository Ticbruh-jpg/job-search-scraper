# Job Search Scraper

Automated job search scraper for Croatian job portals.

## Sources
- posao.hr (RSS)
- moj-posao.net (Playwright)
- HZZ (Playwright)
- Karijerne.com (Playwright)

## Features
- Deduplication across all previous results
- Google Sheets integration
- Daily cron job support
- Telegram notifications

## Requirements
```bash
pip install playwright requests gspread google-auth
playwright install chromium
```

## Usage
```bash
python3 job_search.py
```
