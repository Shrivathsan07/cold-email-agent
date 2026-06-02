#!/usr/bin/env python3
"""
Company Discovery v5 - YC-tailored, real data only.

Primary source: YC Algolia API (real companies from ycombinator.com/companies)
Secondary: Manual CSV import (--from-file)
Legacy: AI discovery (--use-ai, prints deprecation warning)

Run:
  python discover.py                              # Default: YC directory (interactive)
  python discover.py --from-yc                    # YC directory (auto-append)
  python discover.py --from-yc --vertical legal   # YC directory, specific vertical
  python discover.py --from-yc --recent-only      # Only recent YC batches (W25+)
  python discover.py --from-file leads.csv        # Import from manual CSV
  python discover.py --use-ai --auto              # Legacy AI discovery (prints warning)
  python discover.py --backfill                    # Deprecated, prints warning and exits
"""
import csv, json, re, smtplib, sys, time, urllib.request, urllib.error
from pathlib import Path
import anthropic
import dns.resolver

# Public DNS resolver (avoids ISP NXDOMAIN hijacking)
_public_resolver = dns.resolver.Resolver()
_public_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
from config import (
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL, DISCOVERY_MODEL, ANTHROPIC_TEMPERATURE,
    DISCOVERY_TEMPERATURE, PERSONAL_CONTEXT, VERTICALS, VERTICAL_TO_CATEGORY,
    MIN_SENDS, PREFERRED_LOCATIONS, MAX_EMPLOYEES,
    YC_RECENT_BATCHES, YC_FOCUS_MODE,
)

JUNK_EMAIL_PATTERNS = [
    "example.com", "sentry.io", "wixpress", "schema.org",
    "googleapis", "cloudflare", "webpack", "w3.org",
    "hubspot.com", "mailchimp.com", "sendgrid", "intercom",
    "zendesk.com", "crisp.chat", "drift.com", "typeform.com",
    "calendly.com", "stripe.com", "segment.com", "mixpanel.com",
    ".png", ".jpg", ".svg", ".gif", ".css", ".js", ".woff",
    "placeholder", "email@", "name@", "user@", "test@",
    "noreply@", "no-reply@", "mailer-daemon",
]


def _scrape_emails_from_url(url):
    """Fetch a URL and extract email addresses from the page."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
        found = set(re.findall(pattern, html))
        mailto = re.findall(r'mailto:(' + pattern + ')', html)
        found.update(mailto)
        return [e.lower().strip().rstrip('.') for e in found
                if not any(skip in e.lower() for skip in JUNK_EMAIL_PATTERNS)]
    except Exception:
        return []


def _scrape_company_emails(domain):
    """Scrape a company website for on-domain email addresses."""
    if not domain:
        return []
    base = f"https://{domain}"
    paths = ["", "/about", "/about-us", "/team", "/contact", "/contact-us",
             "/company", "/people", "/leadership", "/founders"]
    all_emails = set()
    for path in paths:
        all_emails.update(_scrape_emails_from_url(f"{base}{path}"))
        if len(all_emails) >= 5:
            break
    core = domain.replace("www.", "")
    return [e for e in all_emails if core in e.split("@")[1]]


def _smtp_verify(email_addr):
    """SMTP RCPT TO check — returns 'valid', 'invalid', 'catch_all', or 'unknown'."""
    if not email_addr or '@' not in email_addr:
        return 'invalid'
    domain = email_addr.split('@')[1]
    try:
        answers = _public_resolver.resolve(domain, 'MX')
        mx_host = str(sorted(answers, key=lambda r: r.preference)[0].exchange).rstrip('.')
        if not mx_host:
            return 'invalid'
    except Exception:
        return 'unknown'
    try:
        s = smtplib.SMTP(timeout=10)
        s.connect(mx_host, 25)
        s.ehlo('gmail.com')
        s.mail('verify@gmail.com')
        code, _ = s.rcpt(email_addr)
        s.quit()
        if code == 250:
            # Check catch-all
            try:
                s2 = smtplib.SMTP(timeout=10)
                s2.connect(mx_host, 25)
                s2.ehlo('gmail.com')
                s2.mail('verify@gmail.com')
                code2, _ = s2.rcpt(f"zzzfakeverify9999@{domain}")
                s2.quit()
                if code2 == 250:
                    return 'catch_all'
            except Exception:
                pass
            return 'valid'
        elif code >= 500:
            return 'invalid'
        return 'unknown'
    except Exception:
        return 'unknown'


def _guess_emails(founders_str, domain):
    """Generate possible email patterns from founder names."""
    emails = []
    names = re.split(r'[&,]', founders_str.split('(')[0])
    for name in names:
        parts = name.strip().split()
        if len(parts) >= 2:
            first = parts[0].lower().strip()
            last = parts[-1].lower().strip()
            if first in ['dr', 'dr.', 'md']:
                continue
            emails.append(f"{first}@{domain}")
            emails.append(f"{first}.{last}@{domain}")
    return list(dict.fromkeys(emails))


def find_best_email(company):
    """Find and verify the best email for a discovered company.
    Returns (email, contact_method) or (None, None)."""
    domain = company.get("domain", "").strip()
    founders = company.get("founders", "")
    email_guess = company.get("email_guess", "")

    if not domain:
        return email_guess, "email_guess"

    # 1. Scrape the website for real emails
    scraped = _scrape_company_emails(domain)
    if scraped:
        # Score them: founder name match > generic
        founder_firsts = []
        for name in re.split(r'[&,]', founders.split('(')[0]):
            parts = name.strip().split()
            if len(parts) >= 2 and parts[0].lower() not in ['dr', 'dr.', 'md']:
                founder_firsts.append(parts[0].lower())

        # Check founder matches first
        for email in scraped:
            local = email.split("@")[0].lower()
            for first in founder_firsts:
                if first in local:
                    result = _smtp_verify(email)
                    if result != 'invalid':
                        print(f"      Found scraped founder email: {email} (smtp: {result})")
                        return email, "scraped_verified"

        # Then check any non-generic scraped email
        generic = {"support", "help", "sales", "admin", "careers", "jobs", "press",
                   "legal", "privacy", "noreply", "no-reply", "newsletter", "marketing"}
        for email in scraped:
            local = email.split("@")[0].lower()
            if local not in generic:
                result = _smtp_verify(email)
                if result != 'invalid':
                    print(f"      Found scraped email: {email} (smtp: {result})")
                    return email, "scraped"

    # 2. SMTP-verify guessed patterns
    guesses = _guess_emails(founders, domain)
    for guess in guesses[:4]:
        result = _smtp_verify(guess)
        if result == 'valid':
            print(f"      Verified guess: {guess}")
            return guess, "guess_smtp_verified"
        elif result == 'catch_all':
            print(f"      Catch-all domain, using: {guess}")
            return guess, "guess_catch_all"

    # 3. No verified email found — use best guess and mark as needs_review
    # Most YC companies use Google Workspace which blocks SMTP RCPT TO,
    # so 'unknown' is expected. firstname@domain is still the best bet.
    if email_guess:
        print(f"      Could not verify any email. Marking for review: {email_guess}")
        return email_guess, "needs_review"

    # Fall back to first guessed pattern (firstname@domain) — still add to pipeline
    if guesses:
        best_guess = guesses[0]
        print(f"      SMTP unverifiable. Using best guess: {best_guess}")
        return best_guess, "needs_review"

    return None, None


CSV_PATH = Path("companies.csv")
ARCHIVE_PATH = Path("archive.csv")
CSV_HEADERS = [
    "company", "founders", "email", "contact_method", "what_they_do",
    "hook_notes", "status", "yc_batch", "funding", "location",
    "team_size", "sent_date", "sent_subject", "message_id", "followup_status",
    "vertical", "domain",
]

client = None


def verify_domain(domain):
    """Returns True if domain has a real website."""
    if not domain:
        return False
    domain = domain.lower().strip().rstrip("/")
    # Strip protocol if accidentally included
    domain = re.sub(r'^https?://', '', domain)
    for scheme in ["https://", "http://"]:
        try:
            url = f"{scheme}{domain}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status < 500
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 405, 429):
                return True  # domain exists, just blocks bots
        except Exception:
            continue
    return False


def verify_mx(domain):
    """Check if a domain has real MX records (can actually receive email)."""
    if not domain:
        return False
    domain = domain.lower().strip().rstrip("/")
    domain = re.sub(r'^https?://', '', domain)
    domain = domain.split("/")[0]
    try:
        answers = _public_resolver.resolve(domain, 'MX')
        real_mx = [r for r in answers if str(r.exchange).strip('.') != '']
        return len(real_mx) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return False
    except Exception:
        return True  # DNS timeout — give benefit of the doubt


def get_client():
    global client
    if client is None:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return client


def get_existing():
    """Return set of existing company names and domains (lowercased).
    Checks both companies.csv and archive.csv to prevent re-discovery."""
    existing = set()
    for csv_file in [CSV_PATH, ARCHIVE_PATH]:
        if csv_file.exists():
            with open(csv_file) as f:
                for row in csv.DictReader(f):
                    existing.add(row["company"].lower().strip())
                    # Also track domains to catch name variants (e.g. "Primer" vs "Primer AI")
                    domain = row.get("domain", "").lower().strip()
                    if domain:
                        existing.add(f"domain:{domain}")
    return existing


def count_by_category():
    """Count companies per vertical category, split by status."""
    counts = {"healthcare": 0, "legal": 0, "finance": 0, "other": 0}
    sent_counts = {"healthcare": 0, "legal": 0, "finance": 0, "other": 0}
    pending_counts = {"healthcare": 0, "legal": 0, "finance": 0, "other": 0}

    if not CSV_PATH.exists():
        return counts, sent_counts, pending_counts

    with open(CSV_PATH) as f:
        for row in csv.DictReader(f):
            v = row.get("vertical", "healthcare").strip()
            cat = VERTICAL_TO_CATEGORY.get(v, "other")
            counts[cat] += 1
            status = row.get("status", "pending")
            if status in ("sent", "dry_run"):
                sent_counts[cat] += 1
            elif status == "pending":
                pending_counts[cat] += 1

    return counts, sent_counts, pending_counts


# ============================================================
# YC ALGOLIA DISCOVERY (real data, no hallucination)
# ============================================================

# Vertical keyword mapping for Algolia search
YC_VERTICAL_QUERIES = {
    "healthcare": ["healthcare", "health tech", "clinical", "medical", "digital health", "telehealth"],
    "legal": ["legal", "law", "contract", "compliance", "regulatory"],
    "finance": ["fintech", "financial", "banking", "insurance", "fraud", "risk"],
    "supply_chain": ["supply chain", "logistics", "procurement", "manufacturing"],
    "cybersecurity": ["security", "cybersecurity", "threat", "vulnerability"],
    "defense": ["defense", "govtech", "government", "military"],
}


def _get_yc_algolia_credentials():
    """Fetch Algolia app ID and API key from YC's companies page.
    These are public credentials embedded in window.AlgoliaOpts."""
    # Fallback credentials (update when YC rotates keys)
    fallback_app_id = "45BWZJ1SGC"
    fallback_api_key = "NzllNTY5MzJiZGM2OTY2ZTQwMDEzOTNhYWZiZGRjODlhYzVkNjBmOGRjNzJiMWM4ZTU0ZDlhYTZjOTJiMjlhMWFuYWx5dGljc1RhZ3M9eWNkYyZyZXN0cmljdEluZGljZXM9WUNDb21wYW55X3Byb2R1Y3Rpb24lMkNZQ0NvbXBhbnlfQnlfTGF1bmNoX0RhdGVfcHJvZHVjdGlvbiZ0YWdGaWx0ZXJzPSU1QiUyMnljZGNfcHVibGljJTIyJTVE"
    try:
        url = "https://www.ycombinator.com/companies"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Parse window.AlgoliaOpts JSON from the page
        algolia_match = re.search(r'window\.AlgoliaOpts\s*=\s*(\{[^}]+\})', html)
        if algolia_match:
            import json as _json
            opts = _json.loads(algolia_match.group(1))
            app_id = opts.get("app", fallback_app_id)
            api_key = opts.get("key", fallback_api_key)
            return app_id, api_key

        return fallback_app_id, fallback_api_key
    except Exception as e:
        print(f"  Warning: could not fetch YC page ({e}), using known credentials")
        return fallback_app_id, fallback_api_key


def _query_yc_algolia(query, app_id, api_key, page=0, hits_per_page=20):
    """Query YC's Algolia index for companies matching the query.
    Returns list of company dicts from the Algolia response."""
    try:
        url = f"https://{app_id}-dsn.algolia.net/1/indexes/YCCompany_production/query"

        payload = json.dumps({
            "query": query,
            "page": page,
            "hitsPerPage": hits_per_page,
            "facetFilters": [["status:Active"]],
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST", headers={
            "X-Algolia-Application-Id": app_id,
            "X-Algolia-API-Key": api_key,
            "Content-Type": "application/json",
        })

        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        return data.get("hits", [])
    except Exception as e:
        print(f"  Algolia query error for '{query}': {e}")
        return []


def _scrape_yc_company_page(yc_slug):
    """Scrape a YC company page for founder names and contact info.
    Returns dict with founders list, emails found, and long description."""
    try:
        url = f"https://www.ycombinator.com/companies/{yc_slug}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        founders = []
        emails = []
        long_description = ""

        # Method 1: Inertia.js data-page attribute (current YC format)
        import html as htmlmod
        inertia_match = re.search(r'data-page="([^"]*)"', html)
        if inertia_match:
            try:
                decoded = htmlmod.unescape(inertia_match.group(1))
                data = json.loads(decoded)
                company_data = data.get("props", {}).get("company", {})

                # Extract founders
                for f in company_data.get("founders", []):
                    name = f.get("full_name", "").strip()
                    title = f.get("title", "").strip()
                    if name and name not in [x.get("name") for x in founders]:
                        founders.append({"name": name, "title": title})

                # Extract long description for better hook notes
                long_description = company_data.get("long_description", "") or ""
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

        # Method 2: Fallback — search through all nested JSON in page
        if not founders:
            # Try both script tags and any JSON-like blocks
            json_matches = re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
            for json_str in json_matches:
                try:
                    data = json.loads(json_str)
                    _extract_founders_from_json(data, founders)
                except (json.JSONDecodeError, TypeError):
                    continue

        # Method 3: Fallback — regex for founder HTML elements
        if not founders:
            founder_pattern = r'<div[^>]*class="[^"]*founder[^"]*"[^>]*>.*?<h3[^>]*>(.*?)</h3>.*?<p[^>]*>(.*?)</p>'
            html_founders = re.findall(founder_pattern, html, re.DOTALL | re.I)
            for name, title in html_founders:
                name = re.sub(r'<[^>]+>', '', name).strip()
                title = re.sub(r'<[^>]+>', '', title).strip()
                if name and name not in [f.get("name") for f in founders]:
                    founders.append({"name": name, "title": title})

        # Method 4: Last resort — look for common name patterns near "founder" text
        if not founders:
            # Look for patterns like "Name LastName, CEO" or "Name LastName - Founder"
            name_patterns = re.findall(
                r'(?:CEO|CTO|COO|Founder|Co-Founder|Co-founder)[^<]{0,5}([A-Z][a-z]+ [A-Z][a-z]+)',
                html
            )
            name_patterns += re.findall(
                r'([A-Z][a-z]+ [A-Z][a-z]+)[^<]{0,5}(?:CEO|CTO|COO|Founder|Co-Founder)',
                html
            )
            seen = set()
            for name in name_patterns:
                name = name.strip()
                if name not in seen and len(name) > 4:
                    founders.append({"name": name, "title": "Founder"})
                    seen.add(name)

        # Extract emails from the page
        email_pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
        page_emails = re.findall(email_pattern, html)
        for e in page_emails:
            e = e.lower().strip()
            if not any(skip in e for skip in JUNK_EMAIL_PATTERNS):
                emails.append(e)

        return {
            "founders": founders,
            "emails": list(set(emails)),
            "long_description": long_description,
        }
    except Exception as e:
        print(f"    Could not scrape YC page for {yc_slug}: {e}")
        return {"founders": [], "emails": [], "long_description": ""}


def _extract_founders_from_json(data, founders, depth=0):
    """Recursively search JSON for founder-related data."""
    if depth > 10:
        return
    if isinstance(data, dict):
        # Check if this dict looks like a founder entry
        if "full_name" in data or ("first_name" in data and "last_name" in data):
            name = data.get("full_name", "")
            if not name:
                name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
            title = data.get("title", "") or data.get("role", "")
            if name and name not in [f.get("name") for f in founders]:
                founders.append({"name": name, "title": title})
        for v in data.values():
            _extract_founders_from_json(v, founders, depth + 1)
    elif isinstance(data, list):
        for item in data:
            _extract_founders_from_json(item, founders, depth + 1)


def _score_yc_company(hit, vertical):
    """Score a YC Algolia hit for relevance. Higher = better fit.
    Heavily weights recent batches and small team size — these are
    the startups most likely to respond to a cold email from a freshman."""
    score = 0

    # Batch recency — BIGGEST factor. Recent = still building = needs help
    batch = hit.get("batch", "")
    batch_scores = {
        "W26": 120, "Winter 2026": 120, "Spring 2026": 120, "IK12": 120,
        "F25": 110, "Fall 2025": 110,
        "S25": 100, "Summer 2025": 100,
        "W25": 90, "Winter 2025": 90,
        "F24": 75, "Fall 2024": 75,
        "S24": 65, "Summer 2024": 65,
        "W24": 55, "Winter 2024": 55,
        "F23": 40, "Fall 2023": 40,
        "S23": 35, "Summer 2023": 35,
        "W23": 30, "Winter 2023": 30,
    }
    score += batch_scores.get(batch, 15)

    # Team size — smaller = founder still reads cold emails
    team_size = hit.get("team_size", 0) or 0
    if isinstance(team_size, str):
        try:
            team_size = int(team_size)
        except ValueError:
            team_size = 10
    if team_size <= 3:
        score += 50  # Solo founder or tiny team — highest signal
    elif team_size <= 8:
        score += 40
    elif team_size <= 15:
        score += 25
    elif team_size <= 30:
        score += 10
    elif team_size <= 50:
        score += 3

    # Location preference
    location = (hit.get("location", "") or "").lower()
    for pref in PREFERRED_LOCATIONS:
        if pref.lower() in location:
            score += 20
            break

    # Bonus: if company has "AI" or "machine learning" in description
    one_liner = (hit.get("one_liner", "") or "").lower()
    if "ai" in one_liner or "machine learning" in one_liner or "llm" in one_liner:
        score += 10

    return score


def _classify_vertical(hit):
    """Classify a YC company into a vertical based on its tags/description."""
    tags = [t.lower() for t in (hit.get("tags", []) or [])]
    one_liner = (hit.get("one_liner", "") or "").lower()
    description = (hit.get("long_description", "") or "").lower()
    combined = " ".join(tags) + " " + one_liner + " " + description

    # Check each vertical's keywords
    vertical_scores = {}
    for vertical, keywords in YC_VERTICAL_QUERIES.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > 0:
            vertical_scores[vertical] = score

    if vertical_scores:
        return max(vertical_scores, key=vertical_scores.get)
    return None


def discover_from_yc(vertical=None, max_results=60, recent_only=False):
    """Discover real companies from YC's public Algolia search API.
    If recent_only=True, only returns companies from YC_RECENT_BATCHES.
    Returns list of company dicts ready for append_to_csv."""
    existing = get_existing()

    print(f"\n{'='*60}")
    print(f"YC DIRECTORY DISCOVERY")
    if vertical:
        print(f"Vertical: {vertical}")
    if recent_only:
        print(f"Filtering: recent batches only ({', '.join(YC_RECENT_BATCHES)})")
    print(f"{'='*60}")

    # Get Algolia credentials
    print("  Fetching Algolia credentials...")
    app_id, api_key = _get_yc_algolia_credentials()

    # Build queries based on vertical
    if vertical:
        queries = YC_VERTICAL_QUERIES.get(vertical, [vertical])
    else:
        # Search across all verticals
        queries = []
        for v_queries in YC_VERTICAL_QUERIES.values():
            queries.extend(v_queries)

    # Deduplicate queries
    queries = list(dict.fromkeys(queries))

    all_hits = {}  # domain -> hit (dedup)
    for query in queries:
        print(f"  Searching: '{query}'...", end=" ", flush=True)
        hits = _query_yc_algolia(query, app_id, api_key, hits_per_page=30)
        new_count = 0
        for hit in hits:
            slug = hit.get("slug", "")
            if slug and slug not in all_hits:
                all_hits[slug] = hit
                new_count += 1
        print(f"{len(hits)} results ({new_count} new)")
        time.sleep(0.3)  # Be polite to Algolia

    print(f"\n  Total unique companies from Algolia: {len(all_hits)}")

    # Filter: team size, already known, active status
    candidates = []
    for slug, hit in all_hits.items():
        name = hit.get("name", "").strip()
        if not name:
            continue

        # Skip if already known
        if name.lower() in existing:
            continue
        website = (hit.get("website", "") or "").strip()
        domain = ""
        if website:
            domain = re.sub(r'^https?://', '', website).split("/")[0].replace("www.", "")
        if domain and f"domain:{domain.lower()}" in existing:
            continue

        # Skip if too large
        team_size = hit.get("team_size", 0) or 0
        if isinstance(team_size, str):
            try:
                team_size = int(team_size)
            except ValueError:
                team_size = 10
        if team_size > MAX_EMPLOYEES:
            continue

        # Skip if recent_only and not in a recent batch
        batch = hit.get("batch", "")
        if recent_only and batch not in YC_RECENT_BATCHES:
            continue

        # Classify vertical
        if vertical:
            hit_vertical = vertical
        else:
            hit_vertical = _classify_vertical(hit)
            if not hit_vertical:
                continue  # Can't classify, skip

        hit["_vertical"] = hit_vertical
        hit["_domain"] = domain
        hit["_score"] = _score_yc_company(hit, hit_vertical)
        candidates.append(hit)

    # Sort by score descending
    candidates.sort(key=lambda h: h["_score"], reverse=True)

    # Ensure proportional vertical distribution (round-robin by vertical)
    if not vertical:
        by_vertical = {}
        for c in candidates:
            v = c.get("_vertical", "healthcare")
            by_vertical.setdefault(v, []).append(c)
        # Round-robin pick from each vertical
        balanced = []
        verticals_list = list(by_vertical.keys())
        idx = {v: 0 for v in verticals_list}
        while len(balanced) < max_results:
            added_any = False
            for v in verticals_list:
                if idx[v] < len(by_vertical[v]) and len(balanced) < max_results:
                    balanced.append(by_vertical[v][idx[v]])
                    idx[v] += 1
                    added_any = True
            if not added_any:
                break
        candidates = balanced
    else:
        candidates = candidates[:max_results]

    print(f"  Candidates after filtering: {len(candidates)}")
    # Show vertical breakdown
    vert_counts = {}
    for c in candidates:
        v = c.get("_vertical", "?")
        vert_counts[v] = vert_counts.get(v, 0) + 1
    for v, ct in sorted(vert_counts.items()):
        print(f"    {v}: {ct}")

    # Verify domains and MX records
    verified = []
    for hit in candidates:
        name = hit.get("name", "")
        domain = hit.get("_domain", "")

        if not domain:
            print(f"    {name}: no domain, skipping")
            continue

        print(f"    Verifying {name} ({domain})...", end=" ", flush=True)

        # Domain check
        if not verify_domain(domain):
            print("domain FAILED")
            continue

        # MX check
        if not verify_mx(domain):
            print("no MX records")
            continue

        print("OK")
        verified.append(hit)

    print(f"\n  Verified companies: {len(verified)}")

    # Scrape YC pages for founder details
    companies = []
    for hit in verified:
        name = hit.get("name", "")
        slug = hit.get("slug", "")
        domain = hit.get("_domain", "")
        vertical_tag = hit.get("_vertical", "healthcare")
        batch = hit.get("batch", "unknown")
        one_liner = hit.get("one_liner", "")
        location = hit.get("location", "") or "unknown"
        team_size_val = hit.get("team_size", 0) or 0

        # Map team_size number to label
        if isinstance(team_size_val, int):
            if team_size_val <= 10:
                ts_label = "small"
            elif team_size_val <= 30:
                ts_label = "mid"
            else:
                ts_label = "larger"
        else:
            ts_label = "small"

        # Get founder info from YC page
        print(f"    Scraping founders for {name}...", end=" ", flush=True)
        yc_data = _scrape_yc_company_page(slug)
        time.sleep(0.5)  # Be polite

        founders_list = yc_data.get("founders", [])
        if founders_list:
            founders_str = " & ".join(
                f"{f['name']} ({f['title']})" if f.get('title') else f['name']
                for f in founders_list
            )
            print(f"{len(founders_list)} founders found")
        else:
            # Try to extract from Algolia hit data as fallback
            algolia_founders = hit.get("founders", []) or []
            if isinstance(algolia_founders, list) and algolia_founders:
                founders_parts = []
                for af in algolia_founders:
                    if isinstance(af, dict):
                        fn = af.get("full_name", "") or af.get("name", "")
                        if fn:
                            founders_parts.append(fn)
                    elif isinstance(af, str):
                        founders_parts.append(af)
                if founders_parts:
                    founders_str = " & ".join(founders_parts)
                    print(f"{len(founders_parts)} founders from Algolia")
                else:
                    founders_str = "Founders (unknown)"
                    print("no founders found")
            else:
                founders_str = "Founders (unknown)"
                print("no founders found")

        # Use long description from YC page if available, else one_liner
        long_desc = yc_data.get("long_description", "")
        what_they_do = one_liner or f"YC {batch} company"
        if long_desc and len(long_desc) > len(what_they_do):
            # Use first 2 sentences of long description for richer context
            sentences = re.split(r'(?<=[.!?])\s+', long_desc.strip())
            what_they_do = " ".join(sentences[:2]).strip()
            if len(what_they_do) > 300:
                what_they_do = what_they_do[:297] + "..."

        company = {
            "company": name,
            "founders": founders_str,
            "email_guess": "",  # Will be resolved by find_best_email
            "domain": domain,
            "what_they_do": what_they_do,
            "hook_notes": "",  # Will be filled by generate_hook_notes
            "yc_batch": batch,
            "funding": "YC",
            "location": location,
            "team_size": ts_label,
            "vertical": vertical_tag,
        }

        # Check for emails found on YC page
        yc_emails = [e for e in yc_data.get("emails", []) if domain in e]
        if yc_emails:
            company["email_guess"] = yc_emails[0]

        companies.append(company)
        existing.add(name.lower())
        if domain:
            existing.add(f"domain:{domain.lower()}")

    return companies


# ============================================================
# CSV FILE IMPORT
# ============================================================
def discover_from_file(filepath):
    """Import companies from a manually curated CSV file.
    Expected columns: company, founders, domain, what_they_do, vertical
    Optional: yc_batch, funding, location, team_size, hook_notes
    Runs domain + MX verification before adding."""
    filepath = Path(filepath)
    if not filepath.exists():
        print(f"Error: file not found: {filepath}")
        return []

    existing = get_existing()

    print(f"\n{'='*60}")
    print(f"CSV FILE IMPORT: {filepath}")
    print(f"{'='*60}")

    with open(filepath) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"  Loaded {len(rows)} rows from {filepath}")

    # Validate required columns
    required = {"company", "domain"}
    if rows:
        available = set(rows[0].keys())
        missing = required - available
        if missing:
            print(f"  Error: missing required columns: {missing}")
            print(f"  Required: company, domain")
            print(f"  Optional: founders, what_they_do, vertical, yc_batch, funding, location, team_size, hook_notes")
            return []

    companies = []
    skipped = 0
    for row in rows:
        name = row.get("company", "").strip()
        domain = row.get("domain", "").strip()

        if not name or not domain:
            print(f"    Skipping row with missing company/domain: {row}")
            skipped += 1
            continue

        # Skip duplicates
        if name.lower() in existing or f"domain:{domain.lower()}" in existing:
            print(f"    {name}: already in pipeline, skipping")
            skipped += 1
            continue

        print(f"    Verifying {name} ({domain})...", end=" ", flush=True)

        # Domain check
        if not verify_domain(domain):
            print("domain FAILED")
            skipped += 1
            continue

        # MX check
        if not verify_mx(domain):
            print("no MX records")
            skipped += 1
            continue

        print("OK")

        companies.append({
            "company": name,
            "founders": row.get("founders", ""),
            "email_guess": row.get("email", ""),
            "domain": domain,
            "what_they_do": row.get("what_they_do", ""),
            "hook_notes": row.get("hook_notes", ""),
            "yc_batch": row.get("yc_batch", "unknown"),
            "funding": row.get("funding", "unknown"),
            "location": row.get("location", "unknown"),
            "team_size": row.get("team_size", "small"),
            "vertical": row.get("vertical", "healthcare"),
        })
        existing.add(name.lower())
        existing.add(f"domain:{domain.lower()}")

    print(f"\n  Verified: {len(companies)} | Skipped: {skipped}")
    return companies


# ============================================================
# HOOK NOTES GENERATION (Claude writes personalization, not company data)
# ============================================================
def generate_hook_notes(companies):
    """Ask Claude to write SHORT personalization hooks for each company.
    Claude ONLY generates hook_notes text — never company names, founders, or domains.
    Uses temperature 0.0 for consistency.

    IMPORTANT: Hook notes must be SHORT (1-2 sentences, under 50 words).
    These are internal notes for the email generator, not the email itself."""
    if not companies:
        return companies

    c = get_client()
    print(f"\n  Generating hook notes for {len(companies)} companies...")

    for co in companies:
        if co.get("hook_notes", "").strip():
            continue  # Already has hook notes

        vertical = co.get("vertical", "healthcare")
        yc_batch = co.get("yc_batch", "unknown")
        is_yc = yc_batch and yc_batch.lower() not in ("unknown", "non-yc", "n/a", "")

        yc_context = ""
        if is_yc:
            yc_context = f"This is a YC {yc_batch} company. Note any YC-relevant angles."

        prompt = f"""Write a SHORT internal note (1-2 sentences, MAX 50 words) about why Shrivi should email this company.
Focus on ONE specific overlap between Shrivi's work and theirs. Be concrete, not generic.

BAD (too long, too generic): "Shrivi's direct experience building AI-powered clinical tools at AphasiaGPT—including intelligent documentation systems and stakeholder feedback loops with healthcare professionals—aligns perfectly with..."
GOOD (short, specific): "Same core problem as SLP Portal: turning messy professional notes into structured data. YC W26, tiny team, NYC."
GOOD: "Duke alum founder. RPM overlaps with AphasiaGPT remote monitoring work."
GOOD: "Legal doc AI = same challenge as clinical doc AI. Different domain, same engineering."

SHRIVI'S KEY EXPERIENCE (pick the most relevant):
- AphasiaGPT: AI clinical documentation, SLP Portal, NLP prototyping
- iRx Reminder: B2B healthcare rebrand, shipped website+logo in a week
- PsychwithShri: mental health platform, 1.3M+ viewers, growth
- EE (Electrical Engineering) at Duke, 4.0 GPA, NJ (near NYC)
- Arduino/embedded: neonatal monitoring system for Uganda
{yc_context}

COMPANY:
- Name: {co.get('company', '')}
- What they do: {co.get('what_they_do', '')}
- Vertical: {vertical}
- YC Batch: {yc_batch}
- Team size: {co.get('team_size', 'unknown')}
- Location: {co.get('location', 'unknown')}

Return ONLY the short note. Under 50 words. No preamble."""

        try:
            r = c.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=100,
                temperature=DISCOVERY_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
            hook = r.content[0].text.strip()
            # Enforce length limit — truncate if Claude went long
            words = hook.split()
            if len(words) > 60:
                hook = " ".join(words[:50]) + "..."
            co["hook_notes"] = hook
            print(f"    {co['company']}: {hook[:80]}...")
        except Exception as e:
            print(f"    {co['company']}: hook generation failed ({e})")
            co["hook_notes"] = ""

    return companies


# ============================================================
# APPEND TO CSV (shared by all discovery methods)
# ============================================================
def append_to_csv(companies):
    """Find best emails, then append discovered companies to companies.csv.
    Scrapes websites and SMTP-verifies before adding."""
    if not companies:
        return

    # Ensure CSV exists with correct headers
    if not CSV_PATH.exists():
        with open(CSV_PATH, "w", newline="") as f:
            csv.writer(f).writerow(CSV_HEADERS)

    # Find and verify emails for each company
    print(f"\n  Finding & verifying emails for {len(companies)} companies...")
    added = 0
    skipped_no_email = 0
    with open(CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        for c in companies:
            print(f"    [{c.get('company', '?')}]", end=" ", flush=True)
            email, method = find_best_email(c)
            if not email:
                print("- no email found, skipping")
                skipped_no_email += 1
                continue
            w.writerow([
                c.get("company", ""),
                c.get("founders", ""),
                email,
                method,
                c.get("what_they_do", ""),
                c.get("hook_notes", ""),
                "pending",
                c.get("yc_batch", "unknown"),
                c.get("funding", "unknown"),
                c.get("location", "unknown"),
                c.get("team_size", "small"),
                "",  # sent_date
                "",  # sent_subject
                "",  # message_id
                "",  # followup_status
                c.get("vertical", "healthcare"),
                c.get("domain", ""),
            ])
            added += 1
    print(f"  Added {added} companies to companies.csv ({skipped_no_email} skipped - no email found)")


# ============================================================
# LEGACY AI DISCOVERY (kept for --use-ai flag, prints warning)
# ============================================================
def discover(vertical, count=15):
    """[LEGACY] Discover startups for a given vertical using Claude.
    WARNING: 58% hallucination rate observed. Use discover_from_yc() instead."""
    print("\n  WARNING: AI discovery has a ~58% hallucination rate.")
    print("  Consider using --from-yc for real YC companies instead.\n")

    existing = get_existing()
    vconfig = VERTICALS.get(vertical, VERTICALS["healthcare"])

    # Reference companies per vertical — used as anchoring examples AND added to skip list
    REFERENCE_COMPANIES = {
        "healthcare": [
            "Clarion Health", "Beacon Health", "CareSwift", "Asha Health", "Locata",
            "Opalite", "Kaigo Health", "Cadence RPM", "Tempus", "Tempus AI",
            "Olive AI", "Ro", "Veradigm", "Eko Health", "Infer",
        ],
        "legal": [
            "Draftwise", "EvenUp", "Harvey AI", "Casetext", "Ironclad", "Rally",
            "Luminance", "Spellbook", "Lexion", "Vanta", "Evisort",
            "Relativity", "Relativity Assist", "Kira Systems", "Zeta Global",
        ],
        "finance": [
            "Greenboard", "Socratix", "Kobalt", "Unit21", "Sardine", "Flagright",
            "Hummingbird", "ComplyAdvantage", "Onfido", "Comply",
        ],
        "supply_chain": ["Flexport", "Optimal Dynamics", "Altana AI", "Resilinc"],
        "cybersecurity": ["Protect AI", "Stairwell", "Drata", "Vanta", "Sublime Security"],
        "defense": ["Anduril", "Shield AI", "Vannevar Labs", "Primer AI", "Rebellion Defense"],
    }

    refs = REFERENCE_COMPANIES.get(vertical, [])
    for ref in refs:
        existing.add(ref.lower().strip())

    if vertical == "healthcare":
        vertical_label = "healthcare AI"
        examples = "clinical workflows, documentation, patient communication, medical AI, digital health, telehealth, RPM"
    elif vertical == "legal":
        vertical_label = "legal AI / legal tech"
        examples = "contract review, litigation research, compliance automation, e-discovery, legal document drafting, regulatory tracking"
    elif vertical == "finance":
        vertical_label = "fintech AI / financial compliance AI"
        examples = "fraud detection, risk management, AML/KYC automation, regulatory compliance, financial operations, insurance automation"
    elif vertical == "supply_chain":
        vertical_label = "supply chain / logistics AI"
        examples = "supply chain optimization, procurement automation, inventory management, manufacturing AI, logistics routing"
    elif vertical == "cybersecurity":
        vertical_label = "cybersecurity AI"
        examples = "threat detection, security operations, vulnerability scanning, incident response, security compliance"
    elif vertical == "defense":
        vertical_label = "defense tech / govtech AI"
        examples = "military logistics, intelligence analysis, defense operations, government automation, national security tech"
    else:
        vertical_label = "AI"
        examples = "various AI applications"

    half_count = max(3, count // 2)

    skip_names = sorted(existing)
    if len(skip_names) > 80:
        skip_str = ', '.join(skip_names[:80]) + f" (and {len(skip_names) - 80} more)"
    else:
        skip_str = ', '.join(skip_names) if skip_names else 'none'

    prompt = f"""Find {count} early-stage {vertical_label} startups for a cold email internship campaign.

CRITICAL - ACCURACY RULES:
- ONLY return companies you are CERTAIN exist. Every company must have a REAL, working website.
- DO NOT invent companies or guess at domains. I will verify every domain you return.
- DO NOT return companies with more than ~50 employees. Sweet spot is 2-20 employees.
- DO NOT return well-known or established companies. No Series C+, no companies valued over $50M.
- DO NOT return companies that have been acquired or shut down.
- If you are not confident a company exists, SKIP IT. Quality over quantity.
- Returning {half_count} real companies is better than {count} where half are fake.
- DO NOT pad the list with invented companies. Return fewer if needed.

WHERE TO LOOK (prioritize these sources):
- YC recent batches: S24, F24, W25, S25, F25, W26 (verifiable at ycombinator.com/companies)
- Very small seed-stage startups founded in 2023-2025
- Companies with fewer than 20 employees on LinkedIn
- Avoid ANY company you've seen in major tech press headlines (those are too big)

ALREADY ON LIST (skip ALL of these): {skip_str}

IDEAL TARGET:
- Seed to Series A ONLY (ideally <{MAX_EMPLOYEES} employees, sweet spot: 2-15)
- Building AI/tech for {vertical_label} (examples: {examples})
- YC-backed strongly preferred (their data is verifiable)
- US-based, especially {', '.join(PREFERRED_LOCATIONS[:6])}
- Small enough that a cold email to the founder gets read
- NOT: {', '.join(vconfig['skip_types'])}

INTERN BACKGROUND (for hook_notes):
{PERSONAL_CONTEXT}

For EACH company provide ALL of these fields:
1. company - exact company name
2. founders - "FirstName LastName (Role) & FirstName LastName (Role)"
3. email_guess - best guess (firstname@domain.com)
4. domain - company website domain (e.g. "company.com"). MUST be a real, working domain.
5. what_they_do - 1-2 sentences, specific
6. hook_notes - why this is a good fit for Shrivi specifically. Be concrete.
7. yc_batch - if YC, which batch (e.g. "S24"). Otherwise "non-YC"
8. location - city, state
9. team_size - "small" (<10), "mid" (10-30), or "larger" (30+)

Return ONLY a valid JSON array. No markdown, no explanation, no backticks."""

    try:
        c = get_client()
        r = c.messages.create(
            model=DISCOVERY_MODEL,
            max_tokens=4000,
            temperature=ANTHROPIC_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = r.content[0].text.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        companies = json.loads(raw)

        new = []
        skipped_existing = []
        for co in companies:
            name = co.get("company", "").lower().strip()
            domain = co.get("domain", "").lower().strip()
            domain_key = f"domain:{domain}" if domain else ""
            if not name:
                continue
            if name in existing or (domain_key and domain_key in existing):
                reason = "name" if name in existing else f"domain:{domain}"
                skipped_existing.append(f"{co.get('company', '?')} ({reason})")
            else:
                co["vertical"] = vertical
                new.append(co)
                existing.add(name)
                if domain_key:
                    existing.add(domain_key)
        if skipped_existing:
            print(f"  Skipped {len(skipped_existing)} already-known companies: {', '.join(skipped_existing[:10])}")
        if not companies:
            print(f"  Claude returned empty list for {vertical}")

        sized = []
        too_large = []
        for co in new:
            size = co.get("team_size", "small").lower().strip()
            if size == "larger":
                too_large.append(co)
            else:
                sized.append(co)
        if too_large:
            print(f"  Removed {len(too_large)} companies marked 'larger':")
            for co in too_large:
                print(f"    - {co.get('company', '?')} (team_size: larger)")
        new = sized

        verified = []
        hallucinated = []
        for co in new:
            domain = co.get("domain", "").strip()
            if not domain:
                email_guess = co.get("email_guess", "")
                if "@" in email_guess:
                    domain = email_guess.split("@")[1]
                    co["domain"] = domain

            print(f"    Verifying {co.get('company', '?')} ({domain})...", end=" ", flush=True)
            if verify_domain(domain):
                print("OK")
                verified.append(co)
            else:
                print("FAILED - domain doesn't resolve, removing")
                hallucinated.append(co)

        if hallucinated:
            print(f"\n  Removed {len(hallucinated)} hallucinated companies:")
            for co in hallucinated:
                print(f"    - {co.get('company', '?')} ({co.get('domain', '?')})")
            print(f"  Kept {len(verified)}/{len(new)} companies after domain verification\n")

        mx_passed = []
        mx_failed = []
        for co in verified:
            domain = co.get("domain", "").strip()
            if verify_mx(domain):
                mx_passed.append(co)
            else:
                print(f"    {co.get('company', '?')} ({domain}): no MX records, removing")
                mx_failed.append(co)

        if mx_failed:
            print(f"  Removed {len(mx_failed)} companies with no mail server (can't receive email)")
            print(f"  Kept {len(mx_passed)}/{len(verified)} after MX verification\n")

        return mx_passed

    except json.JSONDecodeError as e:
        print(f"  JSON parse error for {vertical}: {e}")
        print(f"  Raw response: {raw[:300]}...")
        return []
    except Exception as e:
        print(f"  Discovery error for {vertical}: {e}")
        return []


def backfill():
    """[DEPRECATED] Auto-discover companies to fill gaps.
    This is disabled because it creates a doom loop: bounces trigger more AI discovery
    which hallucinates more companies which bounce again."""
    print("\n" + "="*60)
    print("WARNING: --backfill is deprecated and disabled.")
    print("The auto-backfill doom loop has been eliminated.")
    print("")
    print("Use these instead:")
    print("  python discover.py --from-yc                  # Real YC companies")
    print("  python discover.py --from-yc --vertical legal # Specific vertical")
    print("  python discover.py --from-file leads.csv      # Manual CSV import")
    print("="*60)
    return []


def discover_all(counts_per_vertical=None):
    """[LEGACY] Discover across all verticals that need companies."""
    print("\n  WARNING: AI discovery has a ~58% hallucination rate.")
    print("  Consider using --from-yc for real YC companies instead.\n")

    if counts_per_vertical is None:
        counts_per_vertical = {
            "healthcare": 15,
            "legal": 12,
            "finance": 12,
            "supply_chain": 5,
            "cybersecurity": 5,
            "defense": 3,
        }

    all_new = []
    for vertical, count in counts_per_vertical.items():
        print(f"\nDiscovering {count} {vertical} startups...")
        results = discover(vertical, count)
        if results:
            print(f"  Found {len(results)} new companies")
            all_new.extend(results)
        else:
            print(f"  No results for {vertical}")

    return all_new


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    if ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY":
        print("Set your API key in config.py first")
        sys.exit(1)

    # Parse CLI arguments
    from_yc = "--from-yc" in sys.argv
    from_file = "--from-file" in sys.argv
    use_ai = "--use-ai" in sys.argv
    auto = "--auto" in sys.argv
    do_backfill = "--backfill" in sys.argv
    recent_only = "--recent-only" in sys.argv

    # Single vertical mode
    target_vertical = None
    if "--vertical" in sys.argv:
        idx = sys.argv.index("--vertical")
        if idx + 1 < len(sys.argv):
            target_vertical = sys.argv[idx + 1]
            if target_vertical not in VERTICALS:
                print(f"Unknown vertical: {target_vertical}")
                print(f"Available: {', '.join(VERTICALS.keys())}")
                sys.exit(1)

    # --backfill is deprecated
    if do_backfill:
        backfill()
        sys.exit(0)

    # --from-file: import from CSV
    if from_file:
        idx = sys.argv.index("--from-file")
        if idx + 1 >= len(sys.argv):
            print("Usage: python discover.py --from-file <path-to-csv>")
            sys.exit(1)
        filepath = sys.argv[idx + 1]
        results = discover_from_file(filepath)
        if results:
            results = generate_hook_notes(results)
            append_to_csv(results)
        else:
            print("No new companies to add.")
        sys.exit(0)

    # --use-ai: legacy AI discovery (with warning)
    if use_ai:
        print("\n  WARNING: AI discovery has a ~58% hallucination rate.")
        print("  Consider using --from-yc for real YC companies instead.\n")
        if target_vertical:
            results = discover(target_vertical, 15)
        else:
            results = discover_all()

        if not results:
            print("No new companies found.")
            sys.exit(0)

        print(f"\n{'='*60}")
        print(f"Found {len(results)} new companies total:")
        print(f"{'='*60}")

        by_vertical = {}
        for c in results:
            v = c.get("vertical", "unknown")
            by_vertical.setdefault(v, []).append(c)

        for v, companies in by_vertical.items():
            print(f"\n  [{v.upper()}] ({len(companies)} companies)")
            for c in companies:
                print(f"    {c['company']} - {c['what_they_do'][:60]}...")
                print(f"      Founders: {c['founders']}")
                print(f"      Email: {c.get('email_guess', '?')} | Location: {c.get('location', '?')}")

        if auto:
            append_to_csv(results)
        else:
            r = input("\nAppend all to companies.csv? (y/n): ").strip().lower()
            if r == "y":
                append_to_csv(results)
        sys.exit(0)

    # Default: --from-yc (or no flags)
    # If no flags at all, treat as --from-yc interactive
    results = discover_from_yc(vertical=target_vertical, recent_only=recent_only)

    if not results:
        print("No new companies found.")
        sys.exit(0)

    # Generate hook notes
    results = generate_hook_notes(results)

    print(f"\n{'='*60}")
    print(f"Found {len(results)} new companies:")
    print(f"{'='*60}")

    by_vertical = {}
    for c in results:
        v = c.get("vertical", "unknown")
        by_vertical.setdefault(v, []).append(c)

    for v, companies in by_vertical.items():
        print(f"\n  [{v.upper()}] ({len(companies)} companies)")
        for c in companies:
            print(f"    {c['company']} - {c.get('what_they_do', '')[:60]}...")
            print(f"      Founders: {c.get('founders', '?')}")
            print(f"      Domain: {c.get('domain', '?')} | Location: {c.get('location', '?')}")
            print(f"      Hook: {c.get('hook_notes', '')[:80]}...")

    if from_yc or auto:
        append_to_csv(results)
    else:
        r = input("\nAppend all to companies.csv? (y/n): ").strip().lower()
        if r == "y":
            append_to_csv(results)
