"""
Copy this to recruit_config.py and fill it in. recruit_config.py is gitignored.

Every value here can also come from an environment variable of the same name,
which is how the GitHub Actions workflow supplies secrets without them ever
being committed.
"""

# ============================================================
# WHO YOU ARE
# ============================================================
PROFILE = {
    "name": "",
    "school": "Duke",                 # used to find alumni at target companies
    "grad_year": "2027",
    "linkedin": "",
    "github": "",
    "portfolio": "",
    "email": "",
    "phone": "",

    # One or two sentences, in your own voice. This is what gets woven into
    # outreach drafts, so make it concrete. Name the thing you built.
    "pitch": "I build AI tools for people in documentation-heavy jobs. "
             "I shipped AphasiaGPT and I move fast.",

    # Set True if you will need visa sponsorship. Roles that explicitly do not
    # sponsor get filtered out.
    "needs_sponsorship": False,

    # Set True if you do not hold a US security clearance. Filters out roles
    # that require citizenship or TS/SCI.
    "no_security_clearance": True,
}

# If you already filled in the cold email agent's config.py, you can borrow
# your background from it instead of retyping:
#
#   from config import PERSONAL_CONTEXT
#   PROFILE["pitch"] = PERSONAL_CONTEXT.strip()

# ============================================================
# WHAT YOU ARE GOING AFTER
# ============================================================
TRACKS = {
    "swe": True,    # software engineering
    "pm": True,     # product management, APM, PMT
    "dte": True,    # deployed / forward deployed / solutions engineering
}

# "intern", "newgrad", or "both"
LEVEL = "both"

PREFERRED_LOCATIONS = [
    "New York", "NYC", "NY", "San Francisco", "SF", "Bay Area", "Seattle",
    "Mountain View", "Palo Alto", "Sunnyvale", "Menlo Park", "Remote",
]

# Substrings. Anything matching gets dropped entirely.
EXCLUDED_LOCATIONS = []

# Roles older than this many days stop showing up. For new grad and intern
# hiring, a posting more than three weeks old is usually already deep in
# review, so the default is deliberately aggressive.
MAX_AGE_DAYS = 21

# Nudge you to follow up on a silent application after this many days.
FOLLOWUP_AFTER_DAYS = 10

TARGETS = {
    "applications_per_day": 5,
    "outreach_per_week": 10,
    "leetcode_new_per_day": 2,
    "leetcode_max_reviews_per_day": 3,
}

# How much the daily email puts in front of you. Keep these small. A list you
# finish beats a list you skim.
REPORT_LIMITS = {
    "apply_today": 8,
    "also_worth_it": 6,
    "outreach_suggestions": 3,
}

# ============================================================
# DAILY EMAIL (optional)
# ============================================================
# Gmail app password: myaccount.google.com/apppasswords
EMAIL = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "address": "",
    "password": "",
    "to": "",                 # defaults to address
    "display_name": "Recruiting Command Center",
}

# ============================================================
# CLAUDE (optional)
# ============================================================
# Only used to sharpen outreach drafts. Everything else works without it.
ANTHROPIC_API_KEY = ""
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
