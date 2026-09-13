"""
Finding people worth talking to, and tracking whether you actually talked to them.

An honest note about what this does and does not do. It does NOT scrape
LinkedIn. LinkedIn's terms forbid it, and scraped contact data is exactly the
kind of thing that gets an account restricted during the one season you cannot
afford to lose your account. What it does instead is generate the precise
searches that surface the right people in seconds, rank the kinds of people by
how likely they are to actually help you, and keep a record so you stop
losing track of who you messaged.

The ranking is deliberate. At a big company, the yield order is roughly:
  1. alumni from your school on or near the team  (warm, high reply rate)
  2. recent grads / current interns               (remember being you, reply most)
  3. the university / campus recruiter            (can actually move your resume)
  4. the hiring manager                           (lowest reply rate, highest payoff)
"""

import urllib.parse
from datetime import date

from . import score, settings, store

# Email conventions that are widely published for these companies. Treat every
# one as a guess: verify before you send anything important, and prefer
# LinkedIn for first contact regardless.
EMAIL_PATTERNS = {
    "Google": ["{first}{last}@google.com", "{first}@google.com"],
    "Meta": ["{first}{last}@meta.com"],
    "Amazon": ["{first}{lastinitial}@amazon.com", "{first}@amazon.com"],
    "Microsoft": ["{first}.{last}@microsoft.com", "{firstinitial}{last}@microsoft.com"],
    "Apple": ["{first}_{last}@apple.com", "{firstinitial}{last}@apple.com"],
    "Netflix": ["{first}@netflix.com", "{first}{lastinitial}@netflix.com"],
    "Nvidia": ["{firstinitial}{last}@nvidia.com"],
    "Stripe": ["{first}@stripe.com"],
    "Databricks": ["{first}.{last}@databricks.com"],
    "Palantir": ["{firstinitial}{last}@palantir.com"],
    "Uber": ["{first}@uber.com"],
    "Airbnb": ["{first}.{last}@airbnb.com"],
    "Salesforce": ["{firstinitial}{last}@salesforce.com"],
    "Adobe": ["{last}@adobe.com", "{first}{last}@adobe.com"],
    "Coinbase": ["{first}.{last}@coinbase.com"],
    "Snowflake": ["{first}.{last}@snowflake.com"],
    "OpenAI": ["{first}@openai.com"],
    "Anthropic": ["{first}@anthropic.com"],
}

# Companies where deployed / forward-deployed / solutions engineering is a real
# career track with real headcount. These roles rarely show up on the new grad
# job boards, so the system checks them by hand instead of pretending it can
# find them in a feed.
DTE_WATCHLIST = [
    ("Palantir", "https://www.palantir.com/careers/"),
    ("Anthropic", "https://www.anthropic.com/careers"),
    ("OpenAI", "https://openai.com/careers/search/"),
    ("Scale AI", "https://scale.com/careers"),
    ("Databricks", "https://www.databricks.com/company/careers/open-positions"),
    ("Snowflake", "https://careers.snowflake.com/us/en/search-results"),
    ("Samsara", "https://www.samsara.com/company/careers/roles"),
    ("Applied Intuition", "https://www.appliedintuition.com/careers"),
    ("Sierra", "https://sierra.ai/careers"),
    ("Glean", "https://www.glean.com/careers-list"),
    ("Ramp", "https://ramp.com/careers"),
    ("Rippling", "https://www.rippling.com/careers/open-roles"),
]


def _q(text):
    return urllib.parse.quote_plus(text)


def _company_slug(company):
    return company.lower().replace(" ", "-").replace(".", "").replace(",", "")


def linkedin_search(keywords):
    return f"https://www.linkedin.com/search/results/people/?keywords={_q(keywords)}"


def google_xray(company, extra):
    query = f'site:linkedin.com/in "{company}" {extra}'
    return f"https://www.google.com/search?q={_q(query)}"


def role_keywords(track):
    return {
        "swe": "software engineer",
        "pm": "product manager",
        "dte": "forward deployed engineer OR solutions engineer",
    }.get(track, "software engineer")


def research_card(company, track="swe", team_hint="", school=None):
    """Everything you need to find 3-4 real people at one company, ranked."""
    school = school if school is not None else (settings.PROFILE.get("school") or "")
    role = role_keywords(track)
    hint = f" {team_hint}" if team_hint else ""
    canonical, tier = score.company_tier(company)

    targets = []

    if school:
        targets.append({
            "priority": 1,
            "kind": "alum",
            "who": f"{school} alumni at {canonical}",
            "why": "Warmest possible intro. Shared school is the single best predictor of a reply.",
            "links": [
                ("LinkedIn search", linkedin_search(f"{canonical} {school}")),
                ("LinkedIn alumni tool", f"https://www.linkedin.com/search/results/people/?keywords={_q(school + ' ' + canonical)}&origin=FACETED_SEARCH"),
                ("Google x-ray", google_xray(canonical, f'"{school}" {role}')),
            ],
        })

    targets.append({
        "priority": 2,
        "kind": "engineer" if track != "pm" else "pm",
        "who": f"Recent grads and current interns at {canonical}",
        "why": "One to two years in, they remember applying, and they usually have referral links to burn.",
        "links": [
            ("LinkedIn search", linkedin_search(f"{canonical} {role} intern")),
            ("Google x-ray", google_xray(canonical, f'"{role}" "2024" OR "2025" OR "new grad"')),
            ("GitHub (engineers)", f"https://github.com/search?q={_q(canonical)}&type=users"),
        ],
    })

    targets.append({
        "priority": 3,
        "kind": "recruiter",
        "who": f"University / campus recruiter at {canonical}",
        "why": "The one person whose actual job is to move your resume. Be short and specific with them.",
        "links": [
            ("LinkedIn search", linkedin_search(f"{canonical} university recruiter")),
            ("LinkedIn search (campus)", linkedin_search(f"{canonical} campus recruiting early careers")),
            ("Google x-ray", google_xray(canonical, '"university recruiter" OR "campus recruiter" OR "early career"')),
        ],
    })

    targets.append({
        "priority": 4,
        "kind": "hiring_manager",
        "who": f"Hiring manager / team lead{hint} at {canonical}",
        "why": "Lowest reply rate, highest payoff. Only worth it if you have something specific to say about their team's work.",
        "links": [
            ("LinkedIn search", linkedin_search(f"{canonical} engineering manager{hint}")),
            ("Google x-ray", google_xray(canonical, f'"engineering manager" OR "head of"{hint}')),
            ("Company blog / eng site", f"https://www.google.com/search?q={_q(canonical + ' engineering blog ' + (team_hint or role))}"),
        ],
    })

    return {
        "company": canonical,
        "tier": tier,
        "tier_label": score.tier_label(tier),
        "track": track,
        "team_hint": team_hint,
        "targets": targets,
        "email_patterns": EMAIL_PATTERNS.get(canonical, []),
        "careers_url": f"https://www.google.com/search?q={_q(canonical + ' careers university new grad')}",
    }


def guess_emails(company, full_name):
    """Best-known email conventions for a big-tech company. Verify before sending."""
    canonical, _ = score.company_tier(company)
    patterns = EMAIL_PATTERNS.get(canonical)
    if not patterns:
        return []
    parts = [p for p in full_name.lower().replace(".", " ").split() if p]
    if len(parts) < 2:
        return []
    first, last = parts[0], parts[-1]
    return [p.format(first=first, last=last,
                     firstinitial=first[0], lastinitial=last[0]) for p in patterns]


# ---------------------------------------------------------------------------
# What to work on this week
# ---------------------------------------------------------------------------
def suggest_targets(limit=3):
    """Companies where outreach would move the needle right now.

    Priority goes to companies you already applied to, because a message that
    starts 'I applied to X last week' is a real reason to be in someone's
    inbox, and a referral can still be attached to a live application.
    """
    contacts = store.load_contacts()
    contacted = {c["company"].lower() for c in contacts if c.get("status") not in ("", "to_find")}

    suggestions = []
    today = date.today().isoformat()

    for app in store.load_applications():
        if app.get("stage") in ("rejected", "withdrawn", "offer"):
            continue
        company = app.get("company", "")
        if not company or company.lower() in contacted:
            continue
        days = store.days_since(app.get("applied_on")) or 0
        suggestions.append({
            "company": company,
            "track": app.get("track", "swe"),
            "tier": app.get("tier", "other"),
            "reason": f"applied {days}d ago, no one contacted there yet",
            "urgency": 100 - days,
            "job_id": app.get("job_id", ""),
        })

    if len(suggestions) < limit:
        seen = {s["company"].lower() for s in suggestions}
        for job in sorted(store.load_jobs(), key=lambda r: -float(r.get("score") or 0)):
            if job.get("status") in ("dismissed", "expired"):
                continue
            company = job.get("company_canonical") or job.get("company", "")
            key = company.lower()
            if not company or key in seen or key in contacted:
                continue
            if job.get("tier") not in ("tier1", "tier2"):
                continue
            seen.add(key)
            suggestions.append({
                "company": company,
                "track": job.get("track", "swe"),
                "tier": job.get("tier", "other"),
                "reason": f"open role you have not applied to yet: {job.get('title', '')[:60]}",
                "urgency": float(job.get("score") or 0),
                "job_id": job.get("id", ""),
            })
            if len(suggestions) >= limit * 2:
                break

    suggestions.sort(key=lambda s: -s["urgency"])
    return suggestions[:limit]


# ---------------------------------------------------------------------------
# Message drafting
# ---------------------------------------------------------------------------
LINKEDIN_NOTE_LIMIT = 300

TEMPLATES = {
    "alum": (
        "Hi {first}, I'm a {school} student going into {track_label} and I saw you "
        "made the same jump to {company}. I just applied to {role}. Would you be open "
        "to fifteen minutes on what the team actually works on? Happy to work around your schedule."
    ),
    "engineer": (
        "Hi {first}, I applied to {role} at {company} and I'd rather hear about the team "
        "from someone on it than from the job description. I build {pitch_short}. "
        "Any chance you have fifteen minutes in the next couple weeks?"
    ),
    "pm": (
        "Hi {first}, I applied to {role} at {company}. I'm coming at product from the "
        "building side, {pitch_short}. Would you be open to a short call about how your "
        "team scopes work? I'd learn a lot from it."
    ),
    "recruiter": (
        "Hi {first}, I applied to {role_short} at {company} and wanted to put a name to the "
        "application. {pitch_short}. If a different req is a better fit, I'd rather be pointed "
        "there. Thanks for the look."
    ),
    "hiring_manager": (
        "Hi {first}, I applied to {role} at {company}. I've been building {pitch_short}, "
        "which is why your team's work caught my attention specifically. If you're open to it, "
        "I'd value fifteen minutes to hear what the hardest problem on the team is right now."
    ),
}

TRACK_LABELS = {"swe": "software engineering", "pm": "product", "dte": "deployed engineering"}


def draft_message(contact, job=None, use_claude=True):
    """Return {'linkedin': str, 'email_subject': str, 'email_body': str}."""
    profile = settings.PROFILE
    first = (contact.get("name") or "there").split()[0]
    company = contact.get("company", "the team")
    kind = contact.get("kind") or "engineer"
    role = (job or {}).get("title") or contact.get("notes") or "the new grad role"
    track = (job or {}).get("track") or "swe"
    pitch = profile.get("pitch") or "AI tools for real users"
    pitch_short = pitch.split(".")[0].strip()[:110]

    role_short = role if len(role) <= 42 else role[:42].rsplit(" ", 1)[0]
    role_short = role_short.rstrip(" -,:(").strip()
    fields = {
        "first": first,
        "company": company,
        "role": role,
        "role_short": role_short,
        "school": profile.get("school") or "my school",
        "track_label": TRACK_LABELS.get(track, "engineering"),
        "pitch_short": pitch_short,
        "applied_on": contact.get("last_contact") or date.today().isoformat(),
    }
    template = TEMPLATES.get(kind, TEMPLATES["engineer"])
    note = template.format(**{k: v for k, v in fields.items()})

    if use_claude and settings.ANTHROPIC_API_KEY:
        better = _claude_draft(contact, job, profile, note)
        if better:
            note = better

    note = _fit(note, LINKEDIN_NOTE_LIMIT)

    signature = "\n\n".join(filter(None, [
        f"{profile.get('name', '')}",
        " | ".join(filter(None, [profile.get("school"), profile.get("linkedin"), profile.get("github")])),
    ]))
    email_body = f"{note}\n\n{signature}".strip()

    school = profile.get("school") or "Student"
    return {
        "linkedin": note,
        "email_subject": f"{school} student, applied to {role_short} at {company}",
        "email_body": email_body,
    }


def _fit(text, limit):
    """Trim to the limit at a sentence boundary so it never ends mid-thought."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for stop in (". ", "? ", "! "):
        idx = cut.rfind(stop)
        if idx > limit * 0.5:
            return cut[:idx + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;: ") + "."


def _claude_draft(contact, job, profile, fallback):
    try:
        import anthropic
    except ImportError:
        return ""
    prompt = f"""Write a cold outreach message from a student to someone at a company.

WHO YOU ARE:
{profile.get('name')} - {profile.get('school')} - {profile.get('pitch')}

WHO YOU ARE MESSAGING:
{contact.get('name')} - {contact.get('title')} at {contact.get('company')} ({contact.get('kind')})

THE ROLE YOU CARE ABOUT:
{(job or {}).get('title', 'new grad / internship role')}

RULES:
- Under 280 characters. It has to fit in a LinkedIn connection note.
- No em dashes. No "I hope this finds you well". No "passionate". No exclamation marks.
- Lead with the specific reason you are messaging THIS person, not your resume.
- One concrete ask: fifteen minutes, or a pointer to the right req.
- Plain, direct, peer to peer. Do not grovel and do not oversell.
- Output only the message text, nothing else."""
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=400,
            temperature=0.6,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        return text if 40 < len(text) < 600 else fallback
    except Exception:  # noqa: BLE001 - never let drafting break the daily run
        return ""
