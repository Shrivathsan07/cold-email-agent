"""
Turn 8,000 raw listings into a short ranked list of things worth applying to today.

Two stages:
  classify()  - what track is this, what level, what company tier, is it even
                eligible for you
  score()     - 0-100 priority, driven mostly by company tier and freshness,
                because for new grad and internship roles at big companies,
                applying in the first few days is most of the game
"""

import re

from . import settings

# ---------------------------------------------------------------------------
# Track classification
# ---------------------------------------------------------------------------
# Order matters: deployed/solutions titles contain the word "engineer", so they
# are matched before the generic software patterns.
DTE_PATTERNS = [
    "forward deployed", "forward-deployed", "deployed engineer", "deployed software",
    "solutions engineer", "solution engineer", "solutions architect", "solution architect",
    "solutions consultant", "sales engineer", "implementation engineer",
    "implementation consultant", "technical account manager", "customer engineer",
    "field engineer", "professional services", "technical consultant",
    "delivery engineer", "technical solutions", "customer success engineer",
    "partner engineer", "developer advocate", "developer relations",
    "deployment strategist", "solutions specialist", "solutions analyst",
]

PM_PATTERNS = [
    "product manager", "product management", "associate product manager",
    "product owner", "apm ", "apm,", "apm-", "(apm)", "pmt ", "pmt,", "(pmt)",
    "product analyst", "product strategy", "product marketing manager",
    "rotational product", "product lead",
]

SWE_PATTERNS = [
    "software engineer", "software developer", "software development engineer",
    "software engineering", "sde ", "sde,", "sde-", "(sde)", "swe ", "swe,", "(swe)",
    "backend", "back end", "back-end", "frontend", "front end", "front-end",
    "full stack", "fullstack", "full-stack", "machine learning engineer",
    "ml engineer", "ai engineer", "applied scientist", "research engineer",
    "data engineer", "infrastructure engineer", "platform engineer",
    "systems engineer", "site reliability", "devops", "mobile engineer",
    "ios engineer", "android engineer", "security engineer", "developer,",
    "developer -", "web developer", "application developer", "compiler engineer",
    "distributed systems", "software intern", "coding", "programmer",
]

# Titles that look like a match on a keyword but are not the job you want.
NEGATIVE_PATTERNS = [
    "hardware", "asic", "rtl ", "vlsi", "fpga", "analog", "rf engineer",
    "mechanical engineer", "civil engineer", "chemical engineer", "industrial engineer",
    "electrical engineer", "structural", "aerospace engineer", "manufacturing engineer",
    "process engineer", "quality engineer", "test technician", "field technician",
    "engineering technician", "maintenance", "hvac", "welding", "drafter",
    "nurse", "clinical", "pharmac", "sales representative", "account executive",
    "recruiter", "marketing intern", "accounting", "audit", "tax ", "teller",
    "quantitative trader", "quantitative researcher", "trader,", "actuarial",
    "data analyst", "business analyst", "financial analyst", "marketing analyst",
    "campaign", "social media", "content creator", "graphic design", "supply chain analyst",
]

# Seniority the new grad / intern pipeline should never show you.
SENIOR_PATTERNS = [
    "senior ", "sr. ", "sr ", "staff ", "principal ", "lead ", "manager of",
    "director", "head of", "vp ", "vice president", "distinguished", "fellow",
    "experienced", "mid-level", "5+ years", "10+ years", "expert",
    # Level suffixes: "Engineer II" and up are not entry level at most companies.
    " ii ", " iii ", " iv ", " ii-", " iii-", " 2 ", " 3 ",
]

INTERN_PATTERNS = ["intern", "internship", "co-op", "coop", "co op", "summer analyst", "placement"]
NEWGRAD_PATTERNS = [
    "new grad", "new graduate", "university grad", "university graduate",
    "entry level", "entry-level", "early career", "campus", "graduate program",
    "rotational", "associate ", "grad ", "early in career", "eic ",
]


def _has(text, patterns):
    return any(p in text for p in patterns)


def classify_track(job):
    """Return 'dte', 'pm', 'swe' or '' (not one of your tracks)."""
    title = f" {job.get('title', '').lower()} "
    category = (job.get("category") or "").lower()

    if _has(title, NEGATIVE_PATTERNS):
        return ""
    if _has(title, DTE_PATTERNS):
        return "dte"
    if _has(title, PM_PATTERNS):
        return "pm"
    if _has(title, SWE_PATTERNS):
        return "swe"
    # Fall back to the source's own category when the title is vague
    # ("2027 Summer Intern", "Technology Analyst Program").
    if "product" in category:
        return "pm"
    if "software" in category or "ai/ml" in category or "data" in category:
        return "swe"
    return ""


def classify_level(job):
    """Return 'intern', 'newgrad' or ''."""
    title = f" {job.get('title', '').lower()} "
    if _has(title, INTERN_PATTERNS):
        return "intern"
    if _has(title, NEWGRAD_PATTERNS):
        return "newgrad"
    return job.get("level", "")


# ---------------------------------------------------------------------------
# Company tier
# ---------------------------------------------------------------------------
_ALIAS_INDEX = None
_TIER_LABELS = None


def company_tier(company_name):
    """Return (canonical_name, tier_key). tier_key is tier1/tier2/quant/other."""
    global _ALIAS_INDEX, _TIER_LABELS
    if _ALIAS_INDEX is None:
        _ALIAS_INDEX, _TIER_LABELS = settings.load_companies()
    name = (company_name or "").lower()
    # Word-boundary match so "Applecare Staffing" does not become Apple and
    # "Metabolon" does not become Meta.
    for alias, canonical, tier_key in _ALIAS_INDEX:
        if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", name):
            return canonical, tier_key
    return company_name, "other"


def tier_label(tier_key):
    global _ALIAS_INDEX, _TIER_LABELS
    if _TIER_LABELS is None:
        _ALIAS_INDEX, _TIER_LABELS = settings.load_companies()
    return _TIER_LABELS.get(tier_key, "Other")


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------
def eligibility_problem(job, profile=None, tracks=None, level=None):
    """Return a reason string if you should not see this job, else ''."""
    profile = profile if profile is not None else settings.PROFILE
    tracks = tracks if tracks is not None else settings.TRACKS
    level = level if level is not None else settings.LEVEL

    title = f" {job.get('title', '').lower()} "

    track = classify_track(job)
    if not track:
        return "off-track"
    if not tracks.get(track):
        return f"track {track} disabled"
    if _has(title, SENIOR_PATTERNS) or re.search(r"\b(ii|iii|iv|2|3)\s*$", title.strip(), re.I):
        return "too senior"

    job_level = classify_level(job)
    if level != "both" and job_level and job_level != level:
        return f"level {job_level}"

    degrees = (job.get("degrees") or "").lower()
    if degrees and "phd" in degrees and "bachelor" not in degrees and "master" not in degrees:
        return "PhD only"
    if "phd" in title and "phd" not in (profile.get("degree", "") or "").lower():
        return "PhD only"

    sponsorship = (job.get("sponsorship") or "").lower()
    if profile.get("needs_sponsorship") and "does not offer sponsorship" in sponsorship:
        return "no sponsorship"
    if profile.get("no_security_clearance"):
        if "citizenship is required" in sponsorship:
            return "citizenship required"
        if any(k in title for k in ("ts/sci", "top secret", "security clearance", " - ctj", "polygraph")):
            return "clearance required"

    locations = (job.get("locations") or "").lower()
    for bad in (settings.EXCLUDED_LOCATIONS or []):
        if bad.lower() in locations:
            return f"excluded location {bad}"

    age = job.get("age_days")
    if isinstance(age, str) and age.isdigit():
        age = int(age)
    if isinstance(age, int) and age > settings.MAX_AGE_DAYS:
        return f"stale ({age}d)"

    return ""


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
TIER_POINTS = {"tier1": 46, "tier2": 33, "quant": 20, "other": 12}


def score(job, profile=None):
    """Attach track/tier/score/reasons to a job dict and return it."""
    profile = profile if profile is not None else settings.PROFILE

    track = classify_track(job)
    canonical, tier_key = company_tier(job.get("company"))
    job["track"] = track
    job["company_canonical"] = canonical
    job["tier"] = tier_key
    job["level_detected"] = classify_level(job)

    points = TIER_POINTS.get(tier_key, 12)
    reasons = [tier_label(tier_key)]

    age = job.get("age_days")
    if isinstance(age, str):
        age = int(age) if age.isdigit() else None
    if isinstance(age, int):
        fresh = max(0.0, 26.0 - age * 1.7)
        points += fresh
        if age == 0:
            reasons.append("posted today")
        elif age <= 2:
            reasons.append(f"posted {age}d ago")
        elif age <= 7:
            reasons.append(f"{age}d old")
        else:
            reasons.append(f"{age}d old, apply now or skip")
    else:
        points += 6  # unknown date: neither reward nor punish too hard

    locations = (job.get("locations") or "").lower()
    for pref in (settings.PREFERRED_LOCATIONS or []):
        if pref.lower() in locations:
            points += 10
            reasons.append(f"in {pref}")
            break

    if job.get("faang_flag"):
        points += 3
    if job.get("salary"):
        points += 3
        reasons.append(job["salary"])
    if "offers sponsorship" in (job.get("sponsorship") or "").lower():
        points += 2

    # A posting that names the track plainly is usually a real req rather than
    # an evergreen pipeline page.
    title_low = job.get("title", "").lower()
    if any(k in title_low for k in ("2027", "2026", "summer", "fall", "winter")):
        points += 2

    job["score"] = round(min(100.0, points), 1)
    job["reasons"] = " · ".join(reasons)
    return job


def rank(jobs, profile=None, tracks=None, level=None, exclude_ids=()):
    """Filter to eligible jobs, score them, return sorted best-first."""
    out = []
    for job in jobs:
        if job.get("id") in exclude_ids:
            continue
        problem = eligibility_problem(job, profile=profile, tracks=tracks, level=level)
        if problem:
            continue
        out.append(score(dict(job), profile=profile))
    out.sort(key=lambda j: (-j["score"], j.get("company_canonical", "")))
    return out
