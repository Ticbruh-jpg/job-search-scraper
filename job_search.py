#!/usr/bin/env python3
"""Daily job search - računovodstvo/knjigovodstvo Zagreb"""

import urllib.request
import urllib.parse
import re
import html as htmlmod
import time
import json
from datetime import datetime

OUTPUT_FILE = "/home/Documents/jobs_today.txt"

KEYWORDS = [
    'računovod', 'knjigovod', 'računovođ', 'porezn', 'financij',
    'obračun plaća', 'fakturist', 'bilanca', 'glavna knjiga',
    'blagajn', 'kontroling', 'controller', 'treasurer', 'riznic',
    'revizij', 'audit', 'poreski', 'porezni savjetnik', 'fiskalizacij',
    'likvidatur', 'financijsk', 'treasury', 'budžet', 'proračun'
]

def clean_text(s):
    """Strip HTML tags, decode entities, collapse whitespace."""
    s = re.sub(r'<[^>]+>', ' ', s)
    s = htmlmod.unescape(s)
    s = re.sub(r'[\r\n\t]+', ' ', s)
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip()

def fetch(url, headers=None):
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0')
    req.add_header('Accept-Language', 'hr,en;q=0.9')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return ""

def parse_rss_jobs(xml):
    """Returns list of (firma, pozicija, opis, link)"""
    jobs = []
    items = re.findall(r'<item>(.*?)</item>', xml, re.DOTALL)
    for item in items:
        title_m = re.search(r'<title>(.*?)</title>', item)
        link_m = re.search(r'<link>(.*?)</link>', item)
        author_m = re.search(r'<(?:author|dc:creator|company)>(.*?)</(?:author|dc:creator|company)>', item)
        desc_m = re.search(r'<description>(.*?)</description>', item, re.DOTALL)
        if not title_m:
            continue
        title = htmlmod.unescape(title_m.group(1)).strip()
        link = link_m.group(1).strip() if link_m else ''
        firma = htmlmod.unescape(author_m.group(1)).strip() if author_m else ''
        desc_raw = desc_m.group(1) if desc_m else ''
        desc_raw = re.sub(r']]>', '', desc_raw)
        desc = clean_text(desc_raw)[:200]

        # If no firma from RSS, try to extract from title (e.g. "Računovođa - Acme d.o.o.")
        # Only use the part after separator if it looks like a company (contains d.o.o, j.d.o.o, d.d., or is capitalized)
        if not firma:
            sep_m = re.search(r'[-–|]\s*(.+)$', title)
            if sep_m:
                candidate = sep_m.group(1).strip()
                if re.search(r'd\.o\.o|j\.d\.o\.o|d\.d\.|j\.d\.d\.|[A-Z]{2,}', candidate):
                    firma = candidate
                    title = title[:sep_m.start()].strip()

        t_lower = title.lower()
        if any(k in t_lower for k in KEYWORDS):
            jobs.append((firma, title, desc, link))
    return jobs

def parse_rss_jobs_with_source(xml, source_label):
    """Like parse_rss_jobs but uses source_label when firma is unknown."""
    jobs = parse_rss_jobs(xml)
    return [(f if f else source_label, p, o, l) for f, p, o, l in jobs]

def search_posao_hr():
    xml = fetch('https://www.posao.hr/rss/')
    return parse_rss_jobs_with_source(xml, 'posao.hr')

def search_mojposao():
    """Search mojposao.hr using Playwright — returns (firma, pozicija, opis, link)"""
    import random
    from playwright.sync_api import sync_playwright

    jobs = []
    seen = set()
    BASE = 'https://mojposao.hr'

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            locale='hr-HR',
            timezone_id='Europe/Zagreb',
            viewport={'width': 1280, 'height': 800},
        )
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        for keyword in ['računovođa', 'financije']:
            try:
                page.goto(f'{BASE}/poslovi', timeout=20000, wait_until='domcontentloaded')
                page.wait_for_timeout(random.randint(1000, 2000))

                # Fill search input
                search_input = page.locator('input[name=positions]')
                search_input.click()
                search_input.fill('')
                search_input.type(keyword, delay=random.randint(80, 150))
                page.wait_for_timeout(1500)

                # Press Enter to search
                search_input.press('Enter')
                page.wait_for_timeout(random.randint(1500, 2500))

                # Extract job cards from results
                content = page.content()
                for h3_m in re.finditer(r'<h3[^>]*>(.*?)</h3>', content, re.DOTALL):
                    title = clean_text(h3_m.group(1))
                    if not (5 < len(title) < 150):
                        continue
                    if not any(k in title.lower() for k in KEYWORDS):
                        continue

                    # Find link in surrounding context
                    ctx_before = content[max(0, h3_m.start()-500):h3_m.start()]
                    ctx_after = content[h3_m.end():min(len(content), h3_m.end()+300)]
                    links_before = re.findall(r'href="(/posao/[^"]+)"', ctx_before)
                    links_after = re.findall(r'href="(/posao/[^"]+)"', ctx_after)
                    link = BASE + (links_before[-1] if links_before else (links_after[0] if links_after else ''))

                    # Company name
                    full_ctx = ctx_before[-300:] + ctx_after[:300]
                    firma_m = re.search(r'class="[^"]*(?:employer|company|name)[^"]*"[^>]*>\s*([^<]{3,60})', full_ctx)
                    firma = clean_text(firma_m.group(1)) if firma_m else 'mojposao.hr'

                    key = (firma.lower(), title.lower())
                    if key not in seen:
                        seen.add(key)
                        jobs.append((firma, title, title[:200], link))

            except Exception:
                pass

            time.sleep(random.uniform(2.0, 4.0))

        browser.close()

    return jobs

def search_duckduckgo():
    """Search DuckDuckGo — returns (firma, pozicija, opis, link)"""
    jobs = []
    queries = [
        'site:*.hr "računovodstvo" OR "knjigovodstvo" "posao" Zagreb "prijavi se" 2026',
        '"računovodstvo" OR "knjigovodstvo" Zagreb posao oglasi 2026',
    ]
    for query in queries[:1]:
        q = urllib.parse.quote(query)
        html = fetch(f'https://html.duckduckgo.com/html/?q={q}')
        matches = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
        for href, title in matches[:10]:
            title = re.sub(r'<[^>]+>', '', title).strip()
            title = htmlmod.unescape(title)
            if any(skip in href for skip in ['posao.hr', 'mojposao', 'njuskalo', 'google', 'bing']):
                continue
            if title and len(title) > 5:
                # Try to extract firma from URL domain
                domain_m = re.search(r'https?://(?:www\.)?([^/]+)', href)
                firma = domain_m.group(1) if domain_m else '?'
                jobs.append((firma, title, title[:200], href))
        time.sleep(1)
    return jobs

def search_njuskalo():
    xml = fetch('https://www.njuskalo.hr/posao/feed')
    return parse_rss_jobs_with_source(xml, 'njuskalo.hr')

def search_hzz():
    """Search HZZ (Zavod za zapošljavanje) via Playwright — returns (firma, pozicija, opis, link)"""
    import random
    from playwright.sync_api import sync_playwright

    jobs = []
    seen = set()
    BASE = 'https://burzarada.hzz.hr'

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36',
            locale='hr-HR', timezone_id='Europe/Zagreb',
        )
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = ctx.new_page()

        try:
            page.goto(f'{BASE}/RadnaMjesta_pretraga.aspx', timeout=25000, wait_until='networkidle')
            page.wait_for_timeout(random.randint(1500, 2500))

            # Fill keyword field
            kw_input = page.locator('input[id*="txtNazivRadnogMjesta"], input[name*="naziv"], input[placeholder*="naziv"], input[type=text]').first
            kw_input.fill('računovođa')
            page.wait_for_timeout(500)

            # Submit
            btn = page.locator('input[type=submit], button[type=submit]').first
            btn.click()
            page.wait_for_timeout(random.randint(2000, 3000))

            content = page.content()
            # Extract job rows from results table
            rows = re.findall(r'<tr[^>]*class="[^"]*(?:job|result|oglas|RadnoMjesto)[^"]*"[^>]*>(.*?)</tr>', content, re.DOTALL | re.IGNORECASE)
            if not rows:
                # Try all table rows
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', content, re.DOTALL)

            for row in rows:
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                if len(cells) < 2:
                    continue
                title = clean_text(cells[0])
                firma = clean_text(cells[1]) if len(cells) > 1 else 'HZZ'
                link_m = re.search(r'href="([^"]+RadnoMjesto[^"]+)"', row)
                link = BASE + link_m.group(1) if link_m else BASE
                if any(k in title.lower() for k in KEYWORDS) and 5 < len(title) < 150:
                    key = (firma.lower(), title.lower())
                    if key not in seen:
                        seen.add(key)
                        jobs.append((firma, title, title[:200], link))

        except Exception:
            pass

        browser.close()

    return jobs

def extract_jobs_from_page(page_content, url):
    """
    Extract real job listings from rendered page content.
    Looks for repeating job card patterns with position title + apply button/link.
    Returns list of (pozicija, opis) tuples.
    """
    # Remove script/style
    clean_html = re.sub(r'<script[^>]*>.*?</script>', '', page_content, flags=re.DOTALL | re.IGNORECASE)
    clean_html = re.sub(r'<style[^>]*>.*?</style>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)

    found = []
    seen = set()

    # Look for job cards: elements near "prijavi se", "apply", "apply now", "oglas"
    apply_signals = ['prijavi se', 'apply now', 'apply', 'pošalji prijavu', 'natječaj', 'oglas za posao']

    # Find headings (h1-h4) that contain keywords AND are near an apply signal within 500 chars
    heading_pattern = re.compile(r'<h[1-4][^>]*>(.*?)</h[1-4]>', re.DOTALL | re.IGNORECASE)
    for m in heading_pattern.finditer(clean_html):
        title = clean_text(m.group(1))
        if not (5 < len(title) < 150):
            continue
        if not any(k in title.lower() for k in KEYWORDS):
            continue
        # Check surroundings for apply signal
        start = max(0, m.start() - 200)
        end = min(len(clean_html), m.end() + 500)
        context = clean_html[start:end].lower()
        if any(sig in context for sig in apply_signals):
            if title not in seen:
                seen.add(title)
                found.append((title, title[:200]))

    # Fallback: if no apply-signal matches, look for <li> or <a> with keyword
    # but only if they look like a job title (not navigation)
    if not found:
        # Job title heuristics: contains noun-like keywords, not too short/long
        job_title_pattern = re.compile(
            r'<(?:li|a)[^>]*class="[^"]*(?:job|position|title|oglas|career|karijera)[^"]*"[^>]*>(.*?)</(?:li|a)>',
            re.DOTALL | re.IGNORECASE
        )
        for m in job_title_pattern.finditer(clean_html):
            title = clean_text(m.group(1))
            if 5 < len(title) < 150 and any(k in title.lower() for k in KEYWORDS) and title not in seen:
                seen.add(title)
                found.append((title, title[:200]))

    return found


def check_company_careers():
    """
    Check Zagreb company career pages using Playwright for JS rendering.
    Anti-bot measures: random delays, realistic user agent, no automation flags.
    Returns (firma, pozicija, opis, link).
    """
    import json, os, random
    from playwright.sync_api import sync_playwright

    jobs = []
    json_path = os.path.join(os.path.dirname(__file__), 'zagreb_companies.json')
    try:
        with open(json_path) as f:
            data = json.load(f)
        companies = data.get('companies', [])
    except Exception:
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
            ]
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800},
            locale='hr-HR',
            timezone_id='Europe/Zagreb',
            java_script_enabled=True,
        )
        # Hide automation signals
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['hr-HR', 'hr', 'en-US']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        """)

        page = context.new_page()

        for company in companies:
            name = company.get('name', '')
            url = company.get('careers') or company.get('website', '')
            if not url:
                continue

            try:
                page.goto(url, timeout=20000, wait_until='domcontentloaded')
                # Random wait to simulate human browsing (2-5 seconds)
                time.sleep(random.uniform(2.0, 5.0))
                # Wait a bit more for JS to render
                page.wait_for_timeout(random.randint(800, 1500))

                content = page.content()
                content_lower = content.lower()

                if any(k in content_lower for k in KEYWORDS):
                    titles = extract_jobs_from_page(content, url)
                    if titles:
                        for pozicija, opis in titles:
                            jobs.append((name, pozicija, opis, url))
                    # If no structured job found but keyword exists, skip — don't add noise

            except Exception:
                pass

            # Extra random delay between companies (3-8 seconds)
            time.sleep(random.uniform(3.0, 8.0))

        browser.close()

    return jobs

def fmt(firma, pozicija, opis, link):
    opis = opis[:200] if len(opis) <= 200 else opis[:197] + "..."
    return f"[{firma}] ; {pozicija} ; {opis} ; {link}"


def run_with_timeout(fn, timeout_sec=60):
    """Run a search function with a timeout. Returns [] on timeout/error."""
    import multiprocessing
    def target(q):
        try:
            q.put(fn())
        except Exception as e:
            q.put([])
    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=target, args=(q,))
    p.start()
    p.join(timeout_sec)
    if p.is_alive():
        p.terminate()
        p.join()
        print(f"[TIMEOUT] {fn.__name__} prekinut nakon {timeout_sec}s", flush=True)
        return []
    return q.get() if not q.empty() else []


def sheets_get_all_seen(maton_key, conn_id, sheet_id):
    """Fetch all Firma+Pozicija from all existing sheets."""
    seen = set()
    try:
        req = urllib.request.Request(
            f'https://gateway.maton.ai/google-sheets/v4/spreadsheets/{sheet_id}?fields=sheets.properties'
        )
        req.add_header('Authorization', f'Bearer {maton_key}')
        req.add_header('Maton-Connection', conn_id)
        res = json.load(urllib.request.urlopen(req, timeout=10))
        for s in res.get('sheets', []):
            title = s['properties']['title']
            try:
                enc = urllib.parse.quote(title)
                req2 = urllib.request.Request(
                    f'https://gateway.maton.ai/google-sheets/v4/spreadsheets/{sheet_id}/values/{enc}!A:B'
                )
                req2.add_header('Authorization', f'Bearer {maton_key}')
                req2.add_header('Maton-Connection', conn_id)
                rows = json.load(urllib.request.urlopen(req2, timeout=10)).get('values', [])
                for row in rows[1:]:  # skip header
                    if len(row) >= 2:
                        seen.add((row[0].lower().strip(), row[1].lower().strip()))
            except Exception:
                pass
    except Exception as e:
        print(f"[SHEETS] Greška pri dohvaćanju: {e}", flush=True)
    return seen


def sheets_write(maton_key, conn_id, sheet_id, sheet_name, rows):
    """Create sheet if needed and write rows."""
    import json as _json
    # Create sheet
    try:
        data = _json.dumps({"requests": [{"addSheet": {"properties": {"title": sheet_name}}}]}).encode()
        req = urllib.request.Request(
            f'https://gateway.maton.ai/google-sheets/v4/spreadsheets/{sheet_id}:batchUpdate',
            data=data, method='POST'
        )
        req.add_header('Authorization', f'Bearer {maton_key}')
        req.add_header('Maton-Connection', conn_id)
        req.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Sheet already exists

    # Write rows
    enc = urllib.parse.quote(sheet_name)
    data = _json.dumps({"values": rows}).encode()
    req = urllib.request.Request(
        f'https://gateway.maton.ai/google-sheets/v4/spreadsheets/{sheet_id}/values/{enc}!A1?valueInputOption=RAW',
        data=data, method='PUT'
    )
    req.add_header('Authorization', f'Bearer {maton_key}')
    req.add_header('Maton-Connection', conn_id)
    req.add_header('Content-Type', 'application/json')
    res = json.load(urllib.request.urlopen(req, timeout=10))
    return res.get('updatedRows', 0)


def main():
    import json, os
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    today = datetime.now().strftime("%d.%m.%Y")

    # RSS sources — brzi, bez timeoutа
    all_jobs = []
    for fn in [search_posao_hr, search_njuskalo, search_duckduckgo]:
        try:
            all_jobs.extend(fn())
        except Exception as e:
            print(f"[ERROR] {fn.__name__}: {e}", flush=True)

    # Playwright sources — s timeoutom
    for fn, timeout in [(search_mojposao, 90), (search_hzz, 60), (check_company_careers, 120)]:
        all_jobs.extend(run_with_timeout(fn, timeout))

    # Sheets deduplication
    MATON_KEY = os.environ.get("MATON_API_KEY", "")
    CONN_ID = ""
    SHEET_ID = ""

    seen = set()
    if MATON_KEY:
        seen = sheets_get_all_seen(MATON_KEY, CONN_ID, SHEET_ID)
        print(f"[SHEETS] Već viđeno: {len(seen)} kombinacija", flush=True)

    new_jobs = []
    for firma, pozicija, opis, link in all_jobs:
        key = (firma.lower().strip(), pozicija.lower().strip())
        if key not in seen:
            new_jobs.append((firma, pozicija, opis, link))

    # Write to sheets
    if MATON_KEY and new_jobs:
        rows = [["Firma", "Pozicija", "Opis", "Link", "Datum"]]
        for firma, pozicija, opis, link in new_jobs:
            rows.append([firma, pozicija, opis[:200], link, today])
        try:
            written = sheets_write(MATON_KEY, CONN_ID, SHEET_ID, today, rows)
            print(f"[SHEETS] Upisano {written} redaka u list '{today}'", flush=True)
        except Exception as e:
            print(f"[SHEETS] Greška pri upisu: {e}", flush=True)

    # Save to file
    lines = [
        f"=== OGLASI: RAČUNOVODSTVO/KNJIGOVODSTVO — ZAGREB ===",
        f"Generirano: {now}",
        f"Ukupno pronađeno: {len(all_jobs)} | Novih: {len(new_jobs)}",
        "",
    ]
    for job in new_jobs:
        lines.append(fmt(*job))
    if not new_jobs:
        lines.append("Nema novih oglasa danas.")

    output = "\n".join(lines)
    with open(OUTPUT_FILE, "w") as f:
        f.write(output)

    print(output, flush=True)
    return OUTPUT_FILE

if __name__ == "__main__":
    main()
