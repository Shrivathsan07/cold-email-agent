"""
Cold Email Agent Configuration v3
Multi-vertical: Healthcare AI + Legal AI + Finance AI + Supply Chain/Cyber/Defense

SETUP: Copy this file to config.py and fill in your credentials.
  cp config.example.py config.py
"""

# ============================================================
# EMAIL CREDENTIALS (Gmail)
# ============================================================
# Get a Gmail App Password: myaccount.google.com/apppasswords > Mail > Mac
EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "email_address": "your.email@gmail.com",
    "password": "xxxx xxxx xxxx xxxx",  # Gmail App Password (16 chars)
    "display_name": "Your Name",
}

# ============================================================
# ANTHROPIC API KEY
# ============================================================
# Get your key: console.anthropic.com > API Keys > Create
ANTHROPIC_API_KEY = "sk-ant-your-key-here"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DISCOVERY_MODEL = "claude-sonnet-4-5-20250929"
ANTHROPIC_TEMPERATURE = 0.6
DISCOVERY_TEMPERATURE = 0.0  # For hook_notes generation only — Claude never generates company data

# ============================================================
# EMAIL VERIFICATION POLICY
# ============================================================
# Only send to emails verified through these contact methods.
# guess_catch_all is excluded: catch-all domains accept any RCPT TO,
# so SMTP verification gives zero signal on deliverability.
REQUIRE_VERIFIED_EMAIL = True
VERIFIED_CONTACT_METHODS = {
    "email",              # Confirmed real email (from CSV or manual entry)
    "scraped",            # Found on company website
    "scraped_verified",   # Found on website + SMTP verified
    "scraped_verified_deliverable",
    "scraped_verified_risky",
    "scraped_verified_unknown",
    "scraped_generic_valid",
    "scraped_generic_catch_all",
    "scraped_generic_unknown",
    "hunter_finder",      # Hunter.io Email Finder
    "guess_smtp_verified", # Pattern guess confirmed via SMTP RCPT TO
    "guess_verified_deliverable",  # Pattern guess verified by Hunter
    "existing_verified_deliverable",
    "existing_verified_risky",
    "existing_valid",
    "existing_unknown",   # Named-founder email, SMTP inconclusive (Google Workspace blocks RCPT TO)
    "existing_catch_all", # Named-founder email on catch-all domain
    "confirmed",          # Manually confirmed
}

# ============================================================
# HUNTER.IO API (optional - email verification backup)
# ============================================================
# The agent already scrapes company websites for real emails (free, no API needed).
# Hunter is an OPTIONAL backup that can verify emails before sending.
# SETUP: hunter.io > Sign up (free) > API Keys > Copy
# Free tier: 25 searches + 50 verifications per month
# Set enabled: False if you don't want to use Hunter at all.
HUNTER_API_KEY = "your-hunter-api-key-here"
HUNTER_CONFIG = {
    "enabled": False,          # Set to True after adding your Hunter API key
    "verify_guesses": True,    # Verify scraped/guessed emails before sending
    "min_confidence": 70,      # Only use Hunter Finder results above this score
}

# ============================================================
# SENDING SETTINGS
# ============================================================
SEND_CONFIG = {
    "min_delay_seconds": 30,
    "max_delay_seconds": 55,
    "max_emails_per_run": 50,
    "dry_run": True,             # SET TO False WHEN READY TO SEND
    "attach_resume": True,
    "resume_path": "/path/to/your/resume.pdf",
    "follow_up_days": 5,
    "max_follow_ups": 1,
}

# ============================================================
# MINIMUM SEND TARGETS
# ============================================================
MIN_SENDS = {
    "healthcare": 25,
    "legal": 10,
    "finance": 10,
    "other": 5,        # supply chain, cyber, defense combined
    "total": 50,       # overall minimum across all verticals
}

# ============================================================
# TARGETING (per vertical)
# ============================================================
VERTICALS = {
    "healthcare": {
        "industries": [
            "healthcare AI", "clinical AI", "digital health", "health tech",
            "medical AI", "patient communication", "clinical documentation",
            "remote patient monitoring", "EHR", "telehealth",
        ],
        "skip_types": ["pure biotech", "pharma", "wet lab", "drug discovery", "Series C+"],
    },
    "legal": {
        "industries": [
            "legal AI", "legal tech", "contract review AI", "litigation AI",
            "compliance AI", "law firm automation", "legal document AI",
            "regulatory tech", "e-discovery AI", "legal research AI",
        ],
        "skip_types": ["Series C+", "100+ employees", "pure consulting"],
    },
    "finance": {
        "industries": [
            "fintech AI", "financial compliance AI", "fraud detection AI",
            "risk management AI", "regtech", "banking AI", "insurance AI",
            "AML AI", "KYC automation", "financial operations AI",
        ],
        "skip_types": ["crypto only", "Series C+", "100+ employees", "consumer trading app"],
    },
    "supply_chain": {
        "industries": [
            "supply chain AI", "logistics AI", "procurement AI",
            "manufacturing AI", "inventory AI", "operations AI",
        ],
        "skip_types": ["Series C+", "100+ employees"],
    },
    "cybersecurity": {
        "industries": [
            "cybersecurity AI", "security AI", "threat detection AI",
            "security operations AI", "vulnerability AI",
        ],
        "skip_types": ["Series C+", "100+ employees"],
    },
    "defense": {
        "industries": [
            "defense tech AI", "govtech AI", "military AI", "defense automation",
            "national security AI",
        ],
        "skip_types": ["weapons manufacturer", "100+ employees"],
    },
}

# Map sub-verticals to the "other" category for min send counting
VERTICAL_TO_CATEGORY = {
    "healthcare": "healthcare",
    "legal": "legal",
    "finance": "finance",
    "supply_chain": "other",
    "cybersecurity": "other",
    "defense": "other",
}

PREFERRED_LOCATIONS = ["NYC", "New York", "NJ", "New Jersey", "Remote", "SF", "San Francisco", "Durham"]
MAX_EMPLOYEES = 40  # YC startups are small — 40 is generous

# ============================================================
# YC-SPECIFIC CONFIGURATION
# ============================================================
# Recent batches to prioritize (most recent first)
# YC Algolia uses both short codes AND long names — match both formats
YC_RECENT_BATCHES = [
    "W26", "Winter 2026", "IK12", "Spring 2026",
    "F25", "Fall 2025", "S25", "Summer 2025",
    "W25", "Winter 2025", "F24", "Fall 2024",
    "S24", "Summer 2024",
]
YC_FOCUS_MODE = True  # When True, heavily favor YC companies in discovery

# ============================================================
# YOUR BACKGROUND
# ============================================================
PERSONAL_CONTEXT = """
Name: Your Name
School: Your University
GPA: X.X/4.0
Phone: (xxx) xxx-xxxx
Email: your@email.com
LinkedIn: linkedin.com/in/your-profile/
Location: Your Location

CURRENT ROLES:
- Your current role and description

PAST WORK:
- Your past work and description

SKILLS: Your skills here

LOOKING FOR: What you're looking for (e.g., Summer 2026 internship)
"""

# ============================================================
# VOICE RULES (base rules shared across all verticals)
# ============================================================
VOICE_RULES_BASE = """
CRITICAL RULES:

FORMATTING:
- NO em dashes (\u2014) anywhere. Do NOT just replace them with periods.
  Instead, REWRITE the sentence to flow naturally without needing an em dash.
  BAD: "I build AI tools \u2014 specifically for clinical workflows"
  ALSO BAD: "I build AI tools. Specifically for clinical workflows." (awkward fragment)
  GOOD: "I build AI tools, specifically for clinical workflows."
  GOOD: "I build AI tools for clinical workflows."
  GOOD: "I focus on AI tools for clinical workflows, and I ship fast."
  Use commas, conjunctions, or restructure the sentence entirely.
- NO bullet points in email body.
- Spell out abbreviations.

TONE:
- Conversational and direct. Like a peer messaging a founder.
- Lead with your own work before connecting to their company.
- Show specific understanding of what the company does.
- No filler: "passionate", "thrilled", "incredibly excited" are banned.
- "I like building things that matter and I move fast." - include this or similar.

STRUCTURE:
1. "Hi [FirstName]," then LEAD WITH THE COMPANY — why you're emailing THEM specifically.
   Open with what caught your attention about their company or product.
   Do NOT open with "I'm [Name], a student at [School]..." — that reads as cold spam.
2. THEN who you are + what you build — tied to why it's relevant to them
3. Background paragraph with relevant experience (keep it brief)
4. Ask (adjust by company size):
   - Tiny (1-5): "whatever capacity is most helpful. Product, engineering, growth, you name it."
   - Mid (5-20): "most interested in [engineering/product] but I'm flexible."
   - Larger (20+): "looking for a summer [SWE/product] internship"
5. "I'd love to hop on a quick call if you're open to it. Resume attached if helpful."
6. Signature with your contact info

NEVER:
- Use em dashes
- Sound like a cover letter
- Make up facts about the company
- Claim deep overlap if there isn't one
- More than one exclamation mark total
- Start with "I hope this email finds you well"
- Mention any formal job posting or application page
- Say "Dear"
- Include bullet points
"""

# ============================================================
# VERTICAL-SPECIFIC VOICE ADDITIONS
# ============================================================
VOICE_RULES_HEALTHCARE = """
HEALTHCARE-SPECIFIC:
- Lead with relevant healthcare experience
- Show you live in this space
"""

VOICE_RULES_NON_HEALTHCARE = """
NON-HEALTHCARE VERTICAL:
This company is NOT in healthcare. You MUST tailor the pitch to THEIR specific industry.

CRITICAL: Do NOT lead with healthcare jargon or make healthcare the centerpiece.
The email should read like you actually researched what THEY do.

Your hook should combine BOTH:
1. TRANSFERABLE SKILLS from your startup experience
2. GENUINE CURIOSITY about THEIR specific problem
"""

VOICE_RULES_LEGAL = """
LEGAL AI SPECIFIC:
- Connect your documentation tool experience to legal document workflows
- Common thread: professionals buried in low-value admin work
"""

VOICE_RULES_FINANCE = """
FINANCE AI SPECIFIC:
- Connect consulting/strategy background to financial operations
- If compliance/regtech: connect to experience in regulated environments
"""

VOICE_RULES_OTHER = """
SUPPLY CHAIN / CYBER / DEFENSE SPECIFIC:
- Your hook: you build AI tools that make complex professional workflows more efficient
"""

# ============================================================
# YC-SPECIFIC VOICE OVERLAY
# ============================================================
VOICE_RULES_YC = """
YC COMPANY — SPECIAL RULES:
This is a YC startup. Adjust your tone accordingly:

1. MENTION finding them on the YC directory or YC startup page.
2. YC LANGUAGE: These founders value speed, shipping, and resourcefulness.
3. BATCH AWARENESS: Recent batches are early-stage. Older batches are more established.
4. SIZE AWARENESS: Most YC companies are tiny (2-10 people). Adjust your ask.
5. DO NOT fanboy over YC.
"""


def get_voice_rules(vertical, is_yc=False):
    """Return the combined voice rules for a given vertical.
    If is_yc=True, appends YC-specific voice overlay."""
    rules = VOICE_RULES_BASE
    if vertical == "healthcare":
        rules += VOICE_RULES_HEALTHCARE
    else:
        rules += VOICE_RULES_NON_HEALTHCARE
        if vertical == "legal":
            rules += VOICE_RULES_LEGAL
        elif vertical == "finance":
            rules += VOICE_RULES_FINANCE
        else:
            rules += VOICE_RULES_OTHER
    if is_yc:
        rules += VOICE_RULES_YC
    return rules

# ============================================================
# FOLLOW-UP RULES
# ============================================================
FOLLOW_UP_RULES = """
Short follow-up. REPLY to original email (same thread). Under 75 words. One paragraph.
Don't repeat your background. Don't sound desperate. Casual and direct.
NEVER use em dashes. NEVER re-explain who you are in full.

CRITICAL - EVERY FOLLOW-UP MUST ADD SOMETHING NEW:
Pick ONE of these approaches:
1. Share something you shipped or built since the last email
2. Reference something specific about their product you noticed
3. Make a concrete ask with a specific day/time

TONE: Confident but not pushy. Brief. One new thing + one clear ask.
"""

# ============================================================
# GUARDRAILS
# ============================================================
GUARDRAILS = {
    "banned_phrases": [
        "I hope this email finds you", "I am writing to", "I would be honored",
        "I am passionate about", "I am thrilled", "incredibly excited",
        "Dear Sir", "Dear Madam", "To Whom It May Concern",
        "proven track record", "fast-paced environment", "team player",
        "\u2014",  # em dash
        "I noticed your job posting", "I saw your job listing",
        "I applied through", "formal application", "job posting",
        "caught my eye", "no pressure", "just checking in", "just bumping",
        "circling back", "totally understand if",
    ],
    "required_phrases_healthcare": [],  # Add required phrases for healthcare emails
    "required_phrases_other": [],       # Add required phrases for other emails
    "recommended_phrases_other": [],    # Warn but don't block if missing
    "max_word_count": 350,
    "min_word_count": 150,
    "max_paragraphs": 7,
}

# ============================================================
# SUBJECT TEMPLATES (per vertical category)
# ============================================================
SUBJECT_TEMPLATES = {
    "healthcare": [
        "Your subject line template here - summer help?",
    ],
    "legal": [
        "Your subject line template here - summer help?",
    ],
    "finance": [
        "Your subject line template here - summer help?",
    ],
    "other": [
        "Your subject line template here - summer help?",
    ],
}

# YC-specific subject templates — used when company is YC-backed
SUBJECT_TEMPLATES_YC = {
    "healthcare": [
        "Saw {company} on YC. Your template here - summer help?",
    ],
    "legal": [
        "Saw {company} on YC. Your template here - summer help?",
    ],
    "finance": [
        "Saw {company} on YC. Your template here - summer help?",
    ],
    "other": [
        "Saw {company} on YC. Your template here - summer help?",
    ],
}
