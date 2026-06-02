# Claude Code Instructions: Fix Cold Email Agent

## Location: ~/Desktop/cold-email-agent/

## Problem 1: discover.py hallucinates fake companies

The discovery script asks Claude Haiku to find startups, but Haiku invents companies with fake domains (healthspark.co, schedulingwizard.com, vitalsignai.com, therapybotai.com, hummingly.io, pinnaclehealth.ai — none of these exist). It also returns companies that are way too large to respond to a cold intern email (LawGeex has 200+ employees, Abridge raised $150M+).

### Fix: Add domain verification to discover.py

After Claude returns a list of companies, BEFORE appending to companies.csv, verify each domain actually resolves:

```python
import urllib.request, urllib.error

def verify_domain(domain):
    """Returns True if domain has a real website."""
    if not domain:
        return False
    domain = domain.lower().strip()
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
```

Call `verify_domain(company["domain"])` for every company returned by Claude. Remove any that fail. Print which ones were removed so we can see hallucination rate.

### Fix: Improve the discovery prompt

Add these rules to the prompt sent to Haiku:

1. "ONLY return companies you are CERTAIN exist. Every company must have a REAL, working website. DO NOT invent companies or guess at domains."
2. "DO NOT return companies with more than ~75 employees. Sweet spot is 5-30 employees."
3. "If you are not confident a company exists, skip it. Quality over quantity. Returning 5 real companies is better than 15 where half are fake."
4. "Prefer YC-backed companies since their info is verifiable on ycombinator.com/companies."
5. "For larger companies (50+), only include if they're a genuinely strong fit and the founder is still accessible."
6. Add a line: "If you can only find [count//2] real companies, return that. DO NOT pad the list with invented companies."

### Fix: Add size hints for real companies per vertical

In the prompt, give Haiku examples of REAL companies in each vertical so it anchors on real entities:
- Legal: "Real examples in this space: Draftwise (YC), EvenUp, Harvey AI, Casetext, Ironclad, Rally (YC)"
- Finance: "Real examples: Greenboard (YC), Socratix (YC), Kobalt (YC), Unit21, Sardine"
- Healthcare: already has good coverage from the original 14

## Problem 2: Agent needs to scrape websites for emails instead of guessing

Currently agent.py guesses emails like firstname@domain.com. This causes bounces. The agent should scrape the company's website first.

### Fix: Add web scraping to agent.py email resolution

Before guessing, scrape these pages for email addresses:
- https://{domain}
- https://{domain}/about
- https://{domain}/team
- https://{domain}/contact
- https://{domain}/about-us
- https://{domain}/our-team
- https://{domain}/contact-us

Use regex `r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'` to extract emails from the HTML.

Filter results:
- Keep only emails whose domain matches the company domain
- Skip junk (example.com, sentry.io, schema.org, googleapis, .png, .css etc)
- Rank: founder name match > founders@ > personal-looking > generic (info@, hello@, support@)

Email resolution priority should be:
1. Confirmed email already in CSV (contact_method == "email")
2. Scrape company website for real emails
3. Hunter.io finder (optional, disabled by default)
4. Pattern guessing (last resort)

## Problem 3: companies.csv needs cleanup

Update these rows in companies.csv based on bounce/response data:

### Mark as responded (DO NOT resend or follow up):
- Cadence RPM (eric@cadencerpm.com responded — internship full)
- Avelis Health (angel@avelishealth.com responded — pointed to apply)

### Mark as invalid_company (hallucinated, domain doesn't exist):
- HealthSpark (healthspark.co)
- SchedulingWizard (schedulingwizard.com)
- VitalSignAI (vitalsignai.com)
- TherapyBotAI (therapybotai.com)
- Hummingly (hummingly.io)
- PinnacleHealth (pinnaclehealth.ai)

### Mark as bounced (real company, wrong/bad email):
- Abridge (shivam@abridge.com) — too large anyway, skip
- LawGeex (noam@lawgeex.com) — too large, skip
- NurseAI (catherine@nurseai.health) — server misconfigured, likely dead
- Mend Health (anurag@mend.health) — wrong email
- OverdriveHealth (not@overdrivehealth.com) — "not" was a parsing error

### Mark as pending_delivery (Gmail still retrying):
- Turbine Health (harrison@turbinehealth.com)
- Claim Health (founders@claimhealth.com)
- PatientDesk (founders@patientdesk.com)
- Fluvio AI (joe@fluvio.ai)
- Amby Health (founders@ambyhealth.com)

### Already resent successfully (no action needed):
- Camber — delivered via christophe@camber.health and hello@camber.health
- Prosper — delivered via xavier.gracia@getprosper.ai and info@getprosper.ai
- Clinicos — delivered via kav@clinicos.ai (pradeep@ bounced but kav@ worked)

## Problem 4: Multi-vertical expansion

The agent currently only targets healthcare. Expand to:
- 25+ Healthcare AI
- 10 Legal AI  
- 10 Finance/Compliance AI
- 5 Other (supply chain, cyber, defense combined)

Each vertical needs its own voice rules in the email generation prompt:
- Healthcare: lead with AphasiaGPT, clinical workflow experience
- Non-healthcare: lead with transferable skills (building AI tools for professionals in regulated, documentation-heavy environments) + genuine curiosity about their industry. Don't pretend to have direct experience. Be honest.

Add a "vertical" column to companies.csv. All existing rows are "healthcare".

## Problem 5: 25 minimum enforcement

Before each send run, count sent + pending per vertical category. If any category is short of its minimum target, auto-run discovery to backfill before sending.

After a send run with bounces/errors, check again and backfill if needed.

## Problem 6: Temperature

Set temperature to 0.6 for all Claude API calls (email generation and discovery). Currently not set, which defaults to 1.0 and causes more randomness than we want.

## Config additions needed

```python
# In config.py, add:
ANTHROPIC_TEMPERATURE = 0.6

MIN_SENDS = {
    "healthcare": 25,
    "legal": 10,
    "finance": 10,
    "other": 5,
    "total": 50,
}

# Hunter.io is optional, disabled by default
HUNTER_API_KEY = "YOUR_HUNTER_API_KEY"
HUNTER_CONFIG = {
    "enabled": False,
    "verify_guesses": True,
    "min_confidence": 70,
}
```

## Priority order

1. Fix discover.py (add domain verification + better prompt) — this is the root cause
2. Clean up companies.csv with the status updates above
3. Add web scraping for email resolution to agent.py
4. Add vertical column + multi-vertical voice rules
5. Add minimum enforcement + backfill logic
6. Set temperature to 0.6
