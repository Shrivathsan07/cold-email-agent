"""
Configuration for the recruiting system.

Resolution order for every value:
  1. environment variable  (so GitHub Actions can inject secrets)
  2. recruit_config.py in the repo root (gitignored, your local overrides)
  3. the defaults in this file

Nothing here is secret. Secrets live in recruit_config.py or env vars only.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PKG_DATA = Path(__file__).resolve().parent / "data"

# ---------------------------------------------------------------- user config
try:  # pragma: no cover - optional local file
    import recruit_config as _user
except Exception:  # noqa: BLE001
    _user = None


def _get(name, default):
    env = os.environ.get(name)
    if env not in (None, ""):
        if isinstance(default, bool):
            return env.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(env)
            except ValueError:
                return default
        if isinstance(default, (list, tuple)):
            return [p.strip() for p in env.split(",") if p.strip()]
        return env
    if _user is not None and hasattr(_user, name):
        value = getattr(_user, name)
        # Merge dicts over the defaults so a partial override (which is what
        # the GitHub Action writes from a secret) cannot silently drop keys.
        if isinstance(default, dict) and isinstance(value, dict):
            merged = dict(default)
            merged.update(value)
            return merged
        return value
    return default


# ------------------------------------------------------------------- profile
PROFILE = _get("PROFILE", {
    "name": "",
    "school": "",
    "grad_year": "",
    "linkedin": "",
    "github": "",
    "portfolio": "",
    "email": "",
    "phone": "",
    # One paragraph. Used to draft outreach messages.
    "pitch": "",
    # Needs visa sponsorship? Set True to filter out no-sponsorship roles.
    "needs_sponsorship": False,
    # Set True if you are not a US citizen (filters out clearance-required roles).
    "no_security_clearance": True,
})

# --------------------------------------------------------------------- goals
# The three tracks you are recruiting for. Turn one off by setting it False.
TRACKS = _get("TRACKS", {
    "swe": True,   # software engineering
    "pm": True,    # product management / APM / PMT
    "dte": True,   # deployed / forward-deployed / solutions engineering
})

# What stage you are recruiting for: "intern", "newgrad", or "both".
LEVEL = _get("LEVEL", "both")

PREFERRED_LOCATIONS = _get("PREFERRED_LOCATIONS", [
    "New York", "NYC", "NY", "San Francisco", "SF", "Bay Area", "Seattle",
    "Mountain View", "Palo Alto", "Sunnyvale", "Menlo Park", "Remote",
])

# Locations you will not take. Matched as lowercase substrings.
EXCLUDED_LOCATIONS = _get("EXCLUDED_LOCATIONS", [])

# Daily/weekly targets used by the report to tell you if you are on pace.
TARGETS = _get("TARGETS", {
    "applications_per_day": 5,
    "outreach_per_week": 10,
    "leetcode_new_per_day": 2,
    "leetcode_max_reviews_per_day": 3,
})

# How many roles the daily email puts in front of you. Keep it small enough
# that you actually finish the list.
REPORT_LIMITS = _get("REPORT_LIMITS", {
    "apply_today": 8,
    "also_worth_it": 6,
    "outreach_suggestions": 3,
})

# Roles older than this (days since posted) are dropped from the apply list.
MAX_AGE_DAYS = _get("MAX_AGE_DAYS", 21)

# Nudge you to follow up on an application after this many days of silence.
FOLLOWUP_AFTER_DAYS = _get("FOLLOWUP_AFTER_DAYS", 10)

# ---------------------------------------------------------------- email out
EMAIL = _get("EMAIL", {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "address": os.environ.get("RECRUIT_EMAIL_ADDRESS", ""),
    "password": os.environ.get("RECRUIT_EMAIL_PASSWORD", ""),  # Gmail app password
    "to": os.environ.get("RECRUIT_EMAIL_TO", ""),              # defaults to address
    "display_name": "Recruiting Command Center",
})

ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# --------------------------------------------------------------- data files
JOBS_CSV = DATA_DIR / "jobs.csv"              # full cache, gitignored
JOB_STATE_CSV = DATA_DIR / "job_state.csv"    # small durable half, committed
APPLICATIONS_CSV = DATA_DIR / "applications.csv"
CONTACTS_CSV = DATA_DIR / "contacts.csv"
LEETCODE_CSV = DATA_DIR / "leetcode_log.csv"
STATE_JSON = DATA_DIR / "state.json"


def load_companies():
    """Company tier table -> {canonical_name: (tier_key, tier_label)} plus alias index."""
    raw = json.loads((PKG_DATA / "companies.json").read_text())
    alias_index = []  # (alias, canonical, tier_key)
    tiers = {}
    for tier_key, block in raw.items():
        if tier_key.startswith("_"):
            continue
        tiers[tier_key] = block["label"]
        for canonical, aliases in block["companies"].items():
            for alias in aliases:
                alias_index.append((alias.lower(), canonical, tier_key))
    # longest alias first so "amazon web services" beats "amazon"
    alias_index.sort(key=lambda x: -len(x[0]))
    return alias_index, tiers


def load_leetcode_bank():
    return json.loads((PKG_DATA / "leetcode_bank.json").read_text())


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
