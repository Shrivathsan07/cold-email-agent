"""
Pull job listings from the public GitHub job-board repos.

Every source is defined with a list of candidate URLs. These repos get renamed
once a year (Summer2026-Internships -> Summer2027-Internships, and so on), so
the fetcher walks the candidates until one returns usable content. That means
the system keeps working across recruiting cycles without a code change.

No API keys. No scraping of anything that asks you not to. Just raw.githubusercontent.
"""

import hashlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

USER_AGENT = "recruiting-command-center/1.0 (+github job board aggregator)"
TIMEOUT = 60

# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------
# kind:
#   simplify_json  - the .github/scripts/listings.json schema used by
#                    SimplifyJobs, vanshb03 and forks
#   speedyapply_md - speedyapply markdown tables (has salary + FAANG sections)
#   jobright_md    - jobright-ai markdown tables (best PM coverage)
SOURCES = [
    {
        "key": "simplify_newgrad",
        "label": "SimplifyJobs / New-Grad-Positions",
        "kind": "simplify_json",
        "level": "newgrad",
        "urls": [
            "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        ],
    },
    {
        "key": "simplify_intern",
        "label": "SimplifyJobs / Summer Internships",
        "kind": "simplify_json",
        "level": "intern",
        "urls": [
            "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
        ],
    },
    {
        "key": "cvrve_newgrad",
        "label": "vanshb03 / New-Grad",
        "kind": "simplify_json",
        "level": "newgrad",
        "urls": [
            "https://raw.githubusercontent.com/vanshb03/New-Grad-2027/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/vanshb03/New-Grad-2026/dev/.github/scripts/listings.json",
        ],
    },
    {
        "key": "cvrve_intern",
        "label": "vanshb03 / Summer Internships",
        "kind": "simplify_json",
        "level": "intern",
        "urls": [
            "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json",
            "https://raw.githubusercontent.com/vanshb03/Summer2026-Internships/dev/.github/scripts/listings.json",
        ],
    },
    {
        "key": "speedy_intern",
        "label": "speedyapply / SWE Internships (USA)",
        "kind": "speedyapply_md",
        "level": "intern",
        "urls": [
            "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/README.md",
            "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/README.md",
        ],
    },
    {
        "key": "speedy_newgrad",
        "label": "speedyapply / SWE New Grad (USA)",
        "kind": "speedyapply_md",
        "level": "newgrad",
        "urls": [
            "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md",
            "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/NEW_GRAD_USA.md",
        ],
    },
    {
        "key": "speedy_ai_intern",
        "label": "speedyapply / AI-ML Internships (USA)",
        "kind": "speedyapply_md",
        "level": "intern",
        "urls": [
            "https://raw.githubusercontent.com/speedyapply/2027-AI-College-Jobs/main/README.md",
            "https://raw.githubusercontent.com/speedyapply/2026-AI-College-Jobs/main/README.md",
        ],
    },
    {
        "key": "jobright_pm_intern",
        "label": "jobright-ai / Product Management Internships",
        "kind": "jobright_md",
        "level": "intern",
        "urls": [
            "https://raw.githubusercontent.com/jobright-ai/2027-Product-Management-Internship/master/README.md",
            "https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-Internship/master/README.md",
        ],
    },
    {
        "key": "jobright_pm_newgrad",
        "label": "jobright-ai / Product Management New Grad",
        "kind": "jobright_md",
        "level": "newgrad",
        "urls": [
            "https://raw.githubusercontent.com/jobright-ai/2026-Product-Management-New-Grad/master/README.md",
            "https://raw.githubusercontent.com/jobright-ai/2025-Product-Management-New-Grad/master/README.md",
        ],
    },
]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch(url, attempts=3):
    """GET a URL with retries. Returns text, or None."""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None  # wrong candidate URL, try the next one
            if i == attempts - 1:
                return None
        except Exception:  # noqa: BLE001 - network flake
            if i == attempts - 1:
                return None
        time.sleep(2 ** i)
    return None


# ---------------------------------------------------------------------------
# Canonical record
# ---------------------------------------------------------------------------
def job_id(company, title, url):
    basis = f"{_slug(company)}|{_slug(title)}|{(url or '').split('?')[0].lower()}"
    return hashlib.sha1(basis.encode()).hexdigest()[:12]


def _slug(text):
    # "San Francisco, CA +3" and "San Francisco, CA" are the same place
    text = re.sub(r"\s*\+\d+\s*$", "", (text or ""))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def make_job(**kw):
    company = (kw.get("company") or "").strip()
    title = (kw.get("title") or "").strip()
    url = (kw.get("url") or "").strip()
    return {
        "id": job_id(company, title, url),
        "company": company,
        "title": title,
        "url": url,
        "locations": (kw.get("locations") or "").strip(),
        "source": kw.get("source", ""),
        "source_label": kw.get("source_label", ""),
        "level": kw.get("level", ""),
        "category": (kw.get("category") or "").strip(),
        "posted": kw.get("posted", ""),
        "age_days": kw.get("age_days", ""),
        "salary": (kw.get("salary") or "").strip(),
        "sponsorship": (kw.get("sponsorship") or "").strip(),
        "degrees": (kw.get("degrees") or "").strip(),
        "faang_flag": kw.get("faang_flag", ""),
        "active": kw.get("active", True),
    }


def _iso(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except Exception:  # noqa: BLE001
        return ""


def _age_from_iso(iso_date):
    if not iso_date:
        return ""
    try:
        d = datetime.fromisoformat(iso_date).date()
        return (datetime.now(timezone.utc).date() - d).days
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_simplify_json(text, source):
    import json

    try:
        rows = json.loads(text)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not r.get("active", True) or not r.get("is_visible", True):
            continue
        posted = _iso(r.get("date_posted") or r.get("date_updated"))
        locs = r.get("locations") or []
        if isinstance(locs, str):
            locs = [locs]
        out.append(make_job(
            company=r.get("company_name"),
            title=r.get("title"),
            url=r.get("url"),
            locations="; ".join(str(x) for x in locs),
            source=source["key"],
            source_label=source["label"],
            level=source["level"],
            category=r.get("category") or "",
            posted=posted,
            age_days=_age_from_iso(posted),
            sponsorship=r.get("sponsorship") or "",
            degrees="; ".join(r.get("degrees") or []),
            active=True,
        ))
    return out


_A_HREF = re.compile(r'<a[^>]*href="([^"]+)"', re.I)
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_TAGS = re.compile(r"<[^>]+>")


def _cell_text(cell):
    """Plain text of a markdown table cell, handling HTML and markdown links."""
    text = _MD_LINK.sub(r"\1", cell)
    text = _TAGS.sub("", text)
    text = text.replace("**", "").replace("&amp;", "&").replace("&nbsp;", " ")
    return text.strip()


def _cell_href(cell):
    """First link target in a cell, from either an HTML anchor or a markdown link."""
    m = _A_HREF.search(cell)
    if m:
        return m.group(1).strip()
    m = _MD_LINK.search(cell)
    return m.group(2).strip() if m else ""


def _md_rows(text):
    """Yield (section, [cells]) for every data row of every markdown table."""
    section = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            section = s.lstrip("# ").strip()
            continue
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        low = _cell_text(cells[0]).lower()
        if low in ("company", "company name"):
            continue  # header row
        yield section, cells


def parse_speedyapply_md(text, source):
    """| Company | Position | Location | Salary | Posting | Age |"""
    out = []
    for section, cells in _md_rows(text):
        if len(cells) < 6:
            continue
        company = _cell_text(cells[0])
        title = _cell_text(cells[1])
        if not company or not title:
            continue
        url = _cell_href(cells[4]) or _cell_href(cells[1])
        age_raw = _cell_text(cells[5])
        m = re.match(r"(\d+)\s*([dmy])", age_raw.lower())
        age = ""
        posted = ""
        if m:
            n = int(m.group(1))
            age = n * {"d": 1, "m": 30, "y": 365}[m.group(2)]
            posted = (datetime.now(timezone.utc).date() - timedelta(days=age)).isoformat()
        out.append(make_job(
            company=company,
            title=title,
            url=url,
            locations=_cell_text(cells[2]),
            source=source["key"],
            source_label=source["label"],
            level=source["level"],
            category="AI/ML" if "-AI-" in (source.get("urls") or [""])[0] else "Software",
            posted=posted,
            age_days=age,
            salary=_cell_text(cells[3]),
            faang_flag="faang" if "faang" in section.lower() else "",
            active=True,
        ))
    return out


_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _jobright_date(raw):
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})", raw.strip())
    if not m:
        return "", ""
    today = datetime.now(timezone.utc).date()
    month = _MONTHS.get(m.group(1))
    if not month:
        return "", ""
    year = today.year
    try:
        d = datetime(year, month, int(m.group(2))).date()
    except ValueError:
        return "", ""
    if d > today + timedelta(days=2):  # listed date is in the past year
        d = d.replace(year=year - 1)
    return d.isoformat(), (today - d).days


def parse_jobright_md(text, source):
    """| Company | Job Title | Location | Work Model | Date Posted |

    A leading arrow in the company cell means 'same company as the row above'.
    """
    out = []
    last_company = ""
    for _section, cells in _md_rows(text):
        if len(cells) < 5:
            continue
        raw_company = _cell_text(cells[0])
        if raw_company in ("↳", "->", ""):
            company = last_company
        else:
            company = raw_company
            last_company = company
        title = _cell_text(cells[1])
        if not company or not title:
            continue
        posted, age = _jobright_date(_cell_text(cells[4]))
        location = _cell_text(cells[2])
        work_model = _cell_text(cells[3])
        if work_model and work_model.lower() not in location.lower():
            location = f"{location} ({work_model})" if location else work_model
        out.append(make_job(
            company=company,
            title=title,
            url=_cell_href(cells[1]),
            locations=location,
            source=source["key"],
            source_label=source["label"],
            level=source["level"],
            category="Product",
            posted=posted,
            age_days=age,
            active=True,
        ))
    return out


PARSERS = {
    "simplify_json": parse_simplify_json,
    "speedyapply_md": parse_speedyapply_md,
    "jobright_md": parse_jobright_md,
}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def pull_source(source, verbose=True):
    parser = PARSERS[source["kind"]]
    for url in source["urls"]:
        text = fetch(url)
        if not text:
            continue
        jobs = parser(text, source)
        if jobs:
            if verbose:
                print(f"  {source['label']}: {len(jobs)} active  <- {url.split('/main/')[0].split('/dev/')[0]}")
            return jobs
        if verbose:
            print(f"  {source['label']}: 0 rows parsed from {url}")
    if verbose:
        print(f"  {source['label']}: UNAVAILABLE (all candidate URLs failed)")
    return []


def pull_all(level="both", verbose=True):
    """Fetch every source, drop ones that do not match the wanted level, dedupe."""
    seen = {}
    order = []
    for source in SOURCES:
        if level != "both" and source["level"] != level:
            continue
        for job in pull_source(source, verbose=verbose):
            keys = [job["id"], _dup_key(job)]
            url_key = _url_key(job)
            if url_key:
                keys.append(url_key)
            hit = next((seen[k] for k in keys if k in seen), None)
            if hit is not None:
                _merge(hit, job)
                for k in keys:
                    seen.setdefault(k, hit)
                continue
            for k in keys:
                seen[k] = job
            order.append(job)
    return order


def _dup_key(job):
    """Same company + same title is one decision for you, even if two boards
    list it under different cities. Locations get merged instead."""
    return f"dup:{_slug(job['company'])}|{_slug(job['title'])}"


def _url_key(job):
    """Two boards listing the same req under slightly different titles still
    point at the same application link."""
    url = (job.get("url") or "").split("?")[0].rstrip("/").lower()
    if not url or "jobright.ai" in url:
        return ""  # jobright mints its own per-listing ids, not the employer's
    # ".../<req-id>" and ".../<req-id>/application" are the same posting
    url = re.sub(r"/(application|apply)$", "", url)
    return f"url:{url}"


def _merge(existing, extra):
    """Keep the richer of two records for the same posting."""
    for field in ("salary", "sponsorship", "category", "faang_flag", "degrees"):
        if not existing.get(field) and extra.get(field):
            existing[field] = extra[field]
    _merge_locations(existing, extra.get("locations", ""))
    if extra.get("posted") and (not existing.get("posted") or extra["posted"] > existing["posted"]):
        existing["posted"] = extra["posted"]
        existing["age_days"] = extra["age_days"]
    if extra["source_label"] not in existing["source_label"]:
        existing["source_label"] += f" + {extra['source_label']}"


def _merge_locations(existing, extra_locations):
    if not extra_locations:
        return
    merged, have = [], set()
    for part in (existing["locations"] + ";" + extra_locations).split(";"):
        part = part.strip()
        key = _slug(part)
        if not part or key in have:
            continue
        have.add(key)
        merged.append(part)
    existing["locations"] = "; ".join(merged[:6])
