#!/usr/bin/env python3
"""
Cold Email Agent v3 - Multi-Vertical Automated Outreach
Healthcare (25+) + Legal (10) + Finance (10) + Other (5)
Features: send, follow-up, bounce tracking, email guessing, auto-backfill

Run: python agent.py [send|followup|status]
"""

import csv, json, logging, os, random, re, smtplib, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import dns.resolver

import anthropic
from config import (
    EMAIL_CONFIG, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, ANTHROPIC_TEMPERATURE,
    SEND_CONFIG, MIN_SENDS, PERSONAL_CONTEXT, FOLLOW_UP_RULES,
    GUARDRAILS, SUBJECT_TEMPLATES, SUBJECT_TEMPLATES_YC, VERTICAL_TO_CATEGORY,
    HUNTER_API_KEY, HUNTER_CONFIG,
    REQUIRE_VERIFIED_EMAIL, VERIFIED_CONTACT_METHODS,
    get_voice_rules,
)

# ============================================================
# LOGGING
# ============================================================
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

SENT_LOG = Path("sent_emails_log.csv")
FOLLOWUP_LOG = Path("followup_log.csv")

CSV_HEADERS = [
    "company", "founders", "email", "contact_method", "what_they_do",
    "hook_notes", "status", "yc_batch", "funding", "location",
    "team_size", "sent_date", "sent_subject", "message_id", "followup_status",
    "vertical", "domain",
]


def init_logs():
    if not SENT_LOG.exists():
        with open(SENT_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "company", "founders", "email_to", "subject",
                "body", "status", "error", "message_id", "vertical",
            ])
    if not FOLLOWUP_LOG.exists():
        with open(FOLLOWUP_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "timestamp", "company", "email_to", "subject", "body",
                "status", "original_date", "vertical",
            ])


def log_sent(company, founders, email_to, subject, body, status, error="", message_id="", vertical=""):
    with open(SENT_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(), company, founders, email_to,
            subject, body, status, error, message_id, vertical,
        ])


def log_followup(company, email_to, subject, body, status, original_date, vertical=""):
    with open(FOLLOWUP_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(), company, email_to, subject,
            body, status, original_date, vertical,
        ])


# ============================================================
# CSV I/O
# ============================================================
def load_companies(filepath="companies.csv"):
    p = Path(filepath)
    if not p.exists():
        return []
    with open(p, "r") as f:
        companies = list(csv.DictReader(f))
    # Ensure all rows have a vertical field
    for co in companies:
        if "vertical" not in co or not co["vertical"].strip():
            co["vertical"] = "healthcare"
    return companies


def save_companies(companies, filepath="companies.csv"):
    if not companies:
        return
    # Ensure all keys are present
    for co in companies:
        for h in CSV_HEADERS:
            if h not in co:
                co[h] = ""
    with open(filepath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        w.writeheader()
        w.writerows(companies)


DEAD_STATUSES = {
    "skipped_too_large", "invalid_company", "skipped_no_email",
    "skipped_duplicate_email", "skipped_no_mx",
}
ARCHIVE_PATH = Path("archive.csv")


def cleanup_csv(companies):
    """Move dead rows to archive.csv and return only live companies."""
    dead = [c for c in companies if c.get("status", "") in DEAD_STATUSES]
    if not dead:
        return companies

    # Append dead rows to archive
    write_header = not ARCHIVE_PATH.exists()
    with open(ARCHIVE_PATH, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerows(dead)

    live = [c for c in companies if c.get("status", "") not in DEAD_STATUSES]
    logger.info(f"Archived {len(dead)} dead rows to {ARCHIVE_PATH}. {len(live)} companies remain.")
    save_companies(live)
    return live


# ============================================================
# EMAIL GUESSING
# ============================================================
def guess_emails(founders_str, company_domain):
    """Generate possible email addresses from founder names and domain.
    Order: firstname@ (most common at startups) > first.last@ > hello@
    Note: founders@ removed — high bounce rate in practice."""
    emails = []
    domain = company_domain.lower().strip()

    # Personal email patterns (most likely to reach a founder)
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
            emails.append(f"{first}{last[0]}@{domain}")

    # No generic fallbacks — only named-founder patterns reduce bounce rate

    return list(dict.fromkeys(emails))  # dedupe preserving order



# ============================================================
# WEB SCRAPING FOR EMAILS
# ============================================================
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


def scrape_emails_from_url(url):
    """Fetch a URL and extract all email addresses found on the page."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        emails = set()
        # Standard email pattern
        pattern = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
        found = re.findall(pattern, html)

        # Also check for mailto: links (sometimes obfuscated)
        mailto_pattern = r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})'
        found.extend(re.findall(mailto_pattern, html))

        # Check for obfuscated emails like "name [at] domain [dot] com"
        obfuscated = re.findall(r'([a-zA-Z0-9._%+\-]+)\s*\[?\s*(?:at|AT)\s*\]?\s*([a-zA-Z0-9.\-]+)\s*\[?\s*(?:dot|DOT)\s*\]?\s*([a-zA-Z]{2,})', html)
        for local, domain_part, tld in obfuscated:
            found.append(f"{local}@{domain_part}.{tld}")

        for e in found:
            e = e.lower().strip().rstrip(".")
            if any(skip in e for skip in JUNK_EMAIL_PATTERNS):
                continue
            domain_part = e.split("@")[1] if "@" in e else ""
            if domain_part and "." in domain_part:
                emails.add(e)
        return list(emails)
    except Exception as e:
        logger.debug(f"  Scrape failed for {url}: {e}")
        return []


def scrape_company_emails(domain):
    """Scrape a company website for email addresses."""
    if not domain:
        return []

    domain = domain.lower().strip().rstrip("/")
    base = f"https://{domain}" if not domain.startswith("http") else domain

    # Extended path list — covers most startup site structures
    paths = [
        "", "/about", "/about-us", "/team", "/our-team",
        "/contact", "/contact-us", "/company", "/people",
        "/leadership", "/founders", "/careers", "/jobs",
        "/privacy", "/legal/privacy", "/imprint",
    ]

    all_emails = set()
    for path in paths:
        url = f"{base}{path}"
        emails = scrape_emails_from_url(url)
        all_emails.update(emails)
        # Stop early if we found good ones (avoid hammering the site)
        if len(all_emails) >= 5:
            break

    core_domain = domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
    on_domain = [e for e in all_emails if core_domain in e.split("@")[1]]

    if on_domain:
        logger.info(f"  Scraped {len(on_domain)} emails from {domain}: {on_domain}")
    else:
        logger.info(f"  No on-domain emails found on {domain}")
    return on_domain


def rank_scraped_emails(emails, founders_str, domain):
    """Rank scraped emails by likelihood of being the right founder contact.
    Returns list of (email, score) tuples sorted by score descending.
    Score thresholds: 100+ = founder match, 80 = team/founders, 30 = outreach-ok, <30 = generic."""
    if not emails:
        return []

    founder_firsts = []
    names = re.split(r'[&,]', founders_str.split('(')[0])
    for name in names:
        parts = name.strip().split()
        if len(parts) >= 2:
            first = parts[0].lower().strip()
            if first not in ['dr', 'dr.', 'md']:
                founder_firsts.append(first)

    # Tiered scoring: higher = better for cold outreach to founders
    # HARD BLOCK: these inboxes never reach founders — skip entirely
    outreach_blocked = {"support", "help", "sales", "admin", "office",
                        "careers", "jobs", "press", "media", "investors",
                        "legal", "privacy", "noreply", "no-reply",
                        "newsletter", "marketing", "info", "hello",
                        "contact", "team", "general", "billing",
                        "feedback", "enquiries", "inquiries"}
    outreach_ok = set()  # No generic addresses are acceptable anymore
    outreach_bad = outreach_blocked  # All generic = blocked

    scored = []
    for email in emails:
        local = email.split("@")[0].lower()
        # Hard-block generic/non-founder addresses — these never reach decision makers
        if local in outreach_blocked:
            logger.info(f"  Blocked non-founder address: {email}")
            continue
        score = 0
        for first in founder_firsts:
            if first in local:
                score += 100
                break
        if score == 0:
            if local in ("founders", "cofounders"):
                score += 80
            elif len(local) < 20 and not any(c.isdigit() for c in local):
                score += 50  # unknown person name - decent bet
        scored.append((email, score))

    scored.sort(key=lambda x: -x[1])
    return scored


# ============================================================
# HUNTER.IO (optional backup for verification)
# ============================================================
HUNTER_USAGE_FILE = Path("hunter_usage.json")

def _load_hunter_usage():
    """Load Hunter.io usage counter for the current month."""
    month_key = datetime.now().strftime("%Y-%m")
    if HUNTER_USAGE_FILE.exists():
        try:
            data = json.loads(HUNTER_USAGE_FILE.read_text())
            if data.get("month") == month_key:
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {"month": month_key, "searches": 0, "verifications": 0}

def _save_hunter_usage(usage):
    HUNTER_USAGE_FILE.write_text(json.dumps(usage))

def _hunter_enabled():
    if not (HUNTER_CONFIG.get("enabled", False) and HUNTER_API_KEY and HUNTER_API_KEY != "YOUR_HUNTER_API_KEY"):
        return False
    # Check rate limits (free tier: 25 searches + 50 verifications/month)
    usage = _load_hunter_usage()
    if usage["searches"] >= 25 or usage["verifications"] >= 50:
        logger.warning(f"Hunter.io monthly limit reached (searches: {usage['searches']}/25, verifications: {usage['verifications']}/50)")
        return False
    return True


def hunter_find_email(domain, first_name, last_name):
    """Use Hunter.io Email Finder. Costs 1 credit. Free tier: 25/month."""
    if not _hunter_enabled():
        return None, 0
    try:
        usage = _load_hunter_usage()
        usage["searches"] += 1
        _save_hunter_usage(usage)

        params = urllib.parse.urlencode({
            "domain": domain, "first_name": first_name,
            "last_name": last_name, "api_key": HUNTER_API_KEY,
        })
        url = f"https://api.hunter.io/v2/email-finder?{params}"
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
            data = json.loads(resp.read().decode())
        email = data.get("data", {}).get("email")
        confidence = data.get("data", {}).get("confidence", 0)
        if email and confidence >= HUNTER_CONFIG.get("min_confidence", 70):
            logger.info(f"  Hunter found: {email} (confidence: {confidence}%)")
            return email, confidence
        return None, 0
    except Exception as e:
        logger.warning(f"  Hunter error: {e}")
        return None, 0


def hunter_verify_email(email):
    """Verify email deliverability via Hunter. Costs 0.5 credits."""
    if not _hunter_enabled() or not HUNTER_CONFIG.get("verify_guesses", False):
        return True, "unverified"
    try:
        usage = _load_hunter_usage()
        usage["verifications"] += 1
        _save_hunter_usage(usage)

        params = urllib.parse.urlencode({"email": email, "api_key": HUNTER_API_KEY})
        url = f"https://api.hunter.io/v2/email-verifier?{params}"
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("data", {}).get("result", "unknown")
        if result == "undeliverable":
            logger.info(f"  Hunter: {email} -> undeliverable. Skipping.")
            return False, result
        logger.info(f"  Hunter: {email} -> {result}")
        return True, result
    except Exception as e:
        logger.warning(f"  Hunter verify error: {e}. Assuming valid.")
        return True, "unverified"


# ============================================================
# MX RECORD VERIFICATION
# ============================================================
# Use public DNS to avoid ISP NXDOMAIN hijacking
_public_resolver = dns.resolver.Resolver()
_public_resolver.nameservers = ['8.8.8.8', '1.1.1.1']


def verify_mx(domain):
    """Check if a domain has real MX records (can actually receive email).
    Uses public DNS (Google/Cloudflare) to avoid ISP hijacking.
    Rejects null MX records (just '.') from parked/fake domains.
    Retries with a fresh resolver if the first attempt fails."""
    if not domain:
        return False
    domain = domain.lower().strip().rstrip("/")
    domain = re.sub(r'^https?://', '', domain)
    domain = domain.split("/")[0]  # strip any path

    # Try up to 2 times — first with shared resolver, then with a fresh one
    for attempt in range(2):
        try:
            if attempt == 0:
                resolver = _public_resolver
            else:
                resolver = dns.resolver.Resolver()
                resolver.nameservers = ['8.8.8.8', '1.1.1.1']
                resolver.lifetime = 10
            answers = resolver.resolve(domain, 'MX', lifetime=10)
            real_mx = [r for r in answers if str(r.exchange).strip('.') != '']
            if not real_mx:
                logger.info(f"  MX check: {domain} has only null MX records (parked domain)")
                return False
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return False
        except Exception as e:
            if attempt == 0:
                logger.debug(f"  MX check retry for {domain}: {e}")
                continue
            # Final attempt failed — assume MX exists to avoid false skips
            return True
    return True


# ============================================================
# SMTP RCPT TO VERIFICATION
# ============================================================
def smtp_verify_email(email_addr):
    """Verify an email address exists by connecting to the MX server and issuing RCPT TO.
    Returns: 'valid', 'invalid', 'catch_all', or 'unknown' (on error/timeout)."""
    if not email_addr or '@' not in email_addr:
        return 'invalid'

    domain = email_addr.split('@')[1].lower()

    # Get MX records using public DNS
    try:
        answers = _public_resolver.resolve(domain, 'MX')
        mx_hosts = sorted(answers, key=lambda r: r.preference)
        mx_host = str(mx_hosts[0].exchange).rstrip('.')
        if not mx_host:
            return 'invalid'
    except Exception:
        return 'unknown'

    # Connect to MX server and test RCPT TO
    try:
        smtp = smtplib.SMTP(timeout=10)
        smtp.connect(mx_host, 25)
        smtp.ehlo('gmail.com')
        # MAIL FROM with a real-looking sender
        smtp.mail('verify@gmail.com')
        code, _ = smtp.rcpt(email_addr)
        smtp.quit()

        if code == 250:
            # Check for catch-all: test a random fake address
            try:
                smtp2 = smtplib.SMTP(timeout=10)
                smtp2.connect(mx_host, 25)
                smtp2.ehlo('gmail.com')
                smtp2.mail('verify@gmail.com')
                fake = f"zzzfakeverify9999@{domain}"
                code2, _ = smtp2.rcpt(fake)
                smtp2.quit()
                if code2 == 250:
                    logger.info(f"  SMTP verify: {domain} is catch-all (accepts everything)")
                    return 'catch_all'
            except Exception:
                pass
            return 'valid'
        elif code >= 500:
            return 'invalid'
        else:
            return 'unknown'
    except smtplib.SMTPServerDisconnected:
        return 'unknown'
    except smtplib.SMTPConnectError:
        return 'unknown'
    except Exception as e:
        logger.debug(f"  SMTP verify error for {email_addr}: {e}")
        return 'unknown'


# ============================================================
# EMAIL RESOLUTION PIPELINE
# ============================================================
def resolve_email(company):
    """
    Resolve the best email for a company. Priority:
    1. Confirmed email in CSV (contact_method == "email")
    2. Web scrape the company website for real emails
    3. Hunter.io Email Finder (if enabled)
    4. Pattern guessing fallback (optionally verified by Hunter)
    """
    domain = company.get("domain", "").strip()
    founders_str = company.get("founders", "")

    # 1. Already have a confirmed email?
    existing = company.get("email", "").strip()
    method = company.get("contact_method", "").strip()
    if existing and method == "email":
        logger.info(f"  Using confirmed email: {existing}")
        return existing, "confirmed"

    # 1.5. Check MX records — skip if domain can't receive email
    if domain and not verify_mx(domain):
        logger.warning(f"  No MX records for {domain}. Domain can't receive email.")
        return None, "no_mx"

    # 2. Scrape the company website
    best_scraped = None
    best_scraped_score = 0
    if domain:
        logger.info(f"  Scraping {domain} for emails...")
        scraped = scrape_company_emails(domain)
        if scraped:
            ranked = rank_scraped_emails(scraped, founders_str, domain)
            if ranked:
                best_scraped, best_scraped_score = ranked[0]
                # Only use scraped email immediately if it's a strong match
                # (founder name or team/founders address, score >= 50)
                if best_scraped_score >= 50:
                    if _hunter_enabled() and HUNTER_CONFIG.get("verify_guesses", False):
                        is_valid, result = hunter_verify_email(best_scraped)
                        if is_valid:
                            return best_scraped, f"scraped_verified_{result}"
                        for alt_email, alt_score in ranked[1:3]:
                            if alt_score >= 50:
                                is_valid, result = hunter_verify_email(alt_email)
                                if is_valid:
                                    return alt_email, f"scraped_verified_{result}"
                    else:
                        logger.info(f"  Using strong scraped match: {best_scraped} (score: {best_scraped_score})")
                        return best_scraped, "scraped"
                else:
                    logger.info(f"  Scraped only generic emails (best: {best_scraped}, score: {best_scraped_score}). Trying better options first.")

    # 3. Try Hunter Email Finder
    if _hunter_enabled() and domain:
        names = re.split(r'[&,]', founders_str.split('(')[0])
        for name in names:
            parts = name.strip().split()
            if len(parts) >= 2:
                first, last = parts[0].strip(), parts[-1].strip()
                if first.lower() in ['dr', 'dr.', 'md']:
                    continue
                email, confidence = hunter_find_email(domain, first, last)
                if email:
                    return email, "hunter_finder"

    # 4. Verify existing guessed email
    if existing and _hunter_enabled() and HUNTER_CONFIG.get("verify_guesses", False):
        is_valid, result = hunter_verify_email(existing)
        if is_valid:
            return existing, f"existing_verified_{result}"

    # 5. Pattern guessing with SMTP verification
    if domain:
        guesses = guess_emails(founders_str, domain)
        if guesses:
            # Try Hunter first if available
            if _hunter_enabled() and HUNTER_CONFIG.get("verify_guesses", False):
                for guess in guesses[:3]:
                    is_valid, result = hunter_verify_email(guess)
                    if is_valid and result == "deliverable":
                        return guess, f"guess_verified_{result}"

            # SMTP RCPT TO verification (free, no API needed)
            logger.info(f"  SMTP-verifying guessed emails...")
            for guess in guesses[:4]:
                result = smtp_verify_email(guess)
                logger.info(f"    {guess} -> {result}")
                if result == 'valid':
                    return guess, "guess_smtp_verified"
                elif result == 'catch_all':
                    # Catch-all domain: can't verify, but firstname@ is reasonable
                    return guess, "guess_catch_all"
                elif result == 'invalid':
                    continue  # skip, try next pattern
                # 'unknown' = server didn't cooperate, try next

            # All guesses either invalid or unknown — don't send blind
            logger.warning(f"  No guessed emails could be verified for {domain}")

    # 6. Fall back to generic scraped email ONLY if it's a named person (not hello@, contact@, etc.)
    generic_blocked = {"support", "help", "sales", "admin", "office", "careers", "jobs",
                       "press", "media", "investors", "legal", "privacy", "noreply",
                       "no-reply", "newsletter", "marketing", "info", "hello", "contact",
                       "team", "general", "billing", "feedback", "enquiries", "inquiries"}
    if best_scraped:
        local = best_scraped.split("@")[0].lower()
        if local not in generic_blocked:
            result = smtp_verify_email(best_scraped)
            if result != 'invalid':
                logger.info(f"  Falling back to scraped email: {best_scraped} (smtp: {result})")
                return best_scraped, f"scraped_generic_{result}"
            else:
                logger.warning(f"  Scraped email {best_scraped} failed SMTP verification")
        else:
            logger.info(f"  Skipping generic scraped email: {best_scraped}")

    if existing:
        local = existing.split("@")[0].lower()
        if local not in generic_blocked:
            result = smtp_verify_email(existing)
            if result != 'invalid':
                return existing, f"existing_{result}"
            else:
                logger.warning(f"  Existing email {existing} failed SMTP verification")
        else:
            logger.info(f"  Skipping generic existing email: {existing}")

    return None, None


# ============================================================
# EMAIL GENERATION (vertical-aware)
# ============================================================
def _is_yc_company(company):
    """Check if a company is YC-backed based on yc_batch or funding fields."""
    batch = (company.get("yc_batch", "") or "").strip().lower()
    funding = (company.get("funding", "") or "").strip().lower()
    if batch and batch not in ("unknown", "non-yc", "n/a", ""):
        return True
    if "yc" in funding:
        return True
    return False


def generate_email(company, client, temperature=None):
    if temperature is None:
        temperature = ANTHROPIC_TEMPERATURE
    vertical = company.get("vertical", "healthcare")
    category = VERTICAL_TO_CATEGORY.get(vertical, "other")
    is_yc = _is_yc_company(company)
    voice_rules = get_voice_rules(vertical, is_yc=is_yc)

    # Pick subject templates — YC-specific if applicable
    if is_yc and category in SUBJECT_TEMPLATES_YC:
        templates = [t.format(company=company["company"]) for t in SUBJECT_TEMPLATES_YC[category]]
    else:
        templates = SUBJECT_TEMPLATES.get(category, SUBJECT_TEMPLATES["other"])

    system = f"""You are a cold email ghostwriter for Shrivi. Write ONE cold email. Return ONLY valid JSON: {{"subject":"...","body":"..."}}

BACKGROUND:
{PERSONAL_CONTEXT}

RULES:
{voice_rules}

ABSOLUTE FORMATTING BAN - EM DASHES:
You MUST NOT use the em dash character (\u2014) anywhere in the subject or body. Not even once.
Do NOT just swap the em dash for a period, which creates awkward sentence fragments.
Instead, REWRITE the sentence so it flows naturally without needing one.

WRONG: "I build AI tools \u2014 specifically for clinical workflows"
ALSO WRONG: "I build AI tools. Specifically for clinical workflows." (broken fragment)
RIGHT: "I build AI tools, specifically for clinical workflows."
RIGHT: "I build AI tools for clinical workflows and I ship fast."

WRONG: "healthcare documentation \u2014 something I know well"
ALSO WRONG: "healthcare documentation. Something I know well." (broken fragment)
RIGHT: "healthcare documentation, which is something I know well."
RIGHT: "healthcare documentation, and it's a space I know well."

Use commas, conjunctions (and, which, because, so), or restructure the sentence.
This is a hard constraint. Any em dash will cause the email to be rejected.

SUBJECT TEMPLATES (pick/adapt one):
{json.dumps(templates)}"""

    # Extract first names for greeting
    founders_raw = company['founders'].split('(')[0].strip()
    names = [n.strip().split()[0] for n in re.split(r'[&,]', founders_raw) if n.strip()]
    greeting_names = " and ".join(names[:2])

    vertical_note = ""
    if vertical != "healthcare":
        vertical_note = f"""
IMPORTANT: This is a {vertical.upper().replace('_', ' ')} company, NOT healthcare.
Do NOT lead with healthcare jargon. Lead with your transferable builder skills
and genuine curiosity about their industry. Be honest about coming from healthcare
but show why your skills transfer."""

    yc_note = ""
    if is_yc:
        batch = company.get("yc_batch", "unknown")
        yc_note = f"""
YC CONTEXT: This is a YC {batch} company. You found them through the YC directory.
Mention this naturally (e.g., "came across {company['company']} on YC" or
"found {company['company']} through YC"). Don't fanboy. Don't say "prestigious."
These are builders. Talk like a builder."""

    user = f"""Write a cold email to the founders of {company['company']}.

Company: {company['company']}
Industry/Vertical: {vertical}
Founders: {company['founders']}
What they do: {company['what_they_do']}
YC Batch: {company.get('yc_batch', 'unknown')}
Funding: {company.get('funding', 'unknown')}
Location: {company.get('location', 'unknown')}
Team size: {company.get('team_size', 'unknown')}

PERSONALIZATION NOTES:
{company.get('hook_notes', '')}
{vertical_note}
{yc_note}

Address to: {greeting_names}
Make the hook SPECIFIC and HONEST.
CRITICAL: You MUST use the exact company name "{company['company']}" at least once in the email body. Do NOT say "your team" or "what you're building" without also naming the company.
Return ONLY JSON."""

    try:
        r = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1000,
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
            system=system,
        )
        raw = r.content[0].text.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        result = json.loads(raw)
        if "subject" not in result or "body" not in result:
            raise ValueError("Missing subject or body")
        return result
    except Exception as e:
        logger.error(f"Generation error for {company['company']}: {e}")
        return None


def generate_followup(company, original_subject, client):
    system = f"""You write short follow-up emails. Return ONLY JSON: {{"subject":"...","body":"..."}}

RULES:
{FOLLOW_UP_RULES}"""

    founders_raw = company['founders'].split('(')[0].strip()
    names = [n.strip().split()[0] for n in re.split(r'[&,]', founders_raw) if n.strip()]
    name = names[0] if names else "there"

    user = f"""Write a follow-up for {company['company']} (founder: {name}).
Original subject was: {original_subject}
The subject should be "Re: {original_subject}" to stay in the same thread.
Keep under 75 words. Return ONLY JSON.

REMINDER: You are Shrivi emailing a founder about working for THEM this summer.
Do NOT flip the framing. Do NOT say "we'd love to have you" or "finalizing our team."
Add ONE new thing (something you shipped, an observation about their product, or a specific meeting time)."""

    try:
        r = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=300,
            temperature=ANTHROPIC_TEMPERATURE,
            messages=[{"role": "user", "content": user}],
            system=system,
        )
        raw = r.content[0].text.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Follow-up generation error for {company['company']}: {e}")
        return None


# ============================================================
# GUARDRAILS (vertical-aware)
# ============================================================
def validate_email(email_data, company):
    issues = []
    body = email_data["body"]
    full = email_data["subject"] + " " + body
    vertical = company.get("vertical", "healthcare")

    # Banned phrases
    for phrase in GUARDRAILS["banned_phrases"]:
        if phrase.lower() in full.lower():
            issues.append(f"BANNED: '{phrase}'")

    # Required phrases (vertical-specific)
    if vertical == "healthcare":
        required = GUARDRAILS["required_phrases_healthcare"]
    else:
        required = GUARDRAILS["required_phrases_other"]

    for phrase in required:
        if phrase.lower() not in full.lower():
            issues.append(f"MISSING: '{phrase}'")

    # Recommended (warn but don't block)
    warnings = []
    if vertical != "healthcare":
        for phrase in GUARDRAILS.get("recommended_phrases_other", []):
            if phrase.lower() not in full.lower():
                warnings.append(f"RECOMMENDED MISSING (non-blocking): '{phrase}'")

    # Word count
    wc = len(body.split())
    if wc > GUARDRAILS["max_word_count"]:
        issues.append(f"TOO LONG: {wc}w")
    if wc < GUARDRAILS["min_word_count"]:
        issues.append(f"TOO SHORT: {wc}w")

    # Paragraph count
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    if len(paragraphs) > GUARDRAILS["max_paragraphs"]:
        issues.append(f"TOO MANY PARAGRAPHS: {len(paragraphs)}")

    # Em dash check
    if "\u2014" in full:
        issues.append("EM DASH FOUND")

    # Company name check
    if company["company"].lower() not in body.lower():
        issues.append("COMPANY NAME MISSING")

    # Dear check
    if body.strip().startswith("Dear"):
        issues.append("STARTS WITH DEAR")

    if warnings:
        for w in warnings:
            logger.info(f"  {w}")

    return len(issues) == 0, issues


# ============================================================
# SENDING
# ============================================================
def send_email(to_addr, subject, body, in_reply_to=None):
    try:
        msg = MIMEMultipart()
        msg["From"] = f"{EMAIL_CONFIG['display_name']} <{EMAIL_CONFIG['email_address']}>"
        msg["To"] = to_addr
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        # Convert plain text body to clean HTML email
        lines = body.split("\n")
        html_parts = []
        html_parts.append("""<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; color: #1a1a1a;">""")
        current_paragraph = []
        for line in lines:
            if line.strip() == "":
                if current_paragraph:
                    html_parts.append(f"<p style='margin: 0 0 12px 0;'>{'<br>'.join(current_paragraph)}</p>")
                    current_paragraph = []
            else:
                current_paragraph.append(line)
        if current_paragraph:
            html_parts.append(f"<p style='margin: 0 0 12px 0;'>{'<br>'.join(current_paragraph)}</p>")
        html_parts.append("</div>")
        html = "\n".join(html_parts)
        msg.attach(MIMEText(html, "html"))

        if SEND_CONFIG["attach_resume"]:
            rpath = Path(SEND_CONFIG["resume_path"])
            if rpath.exists():
                with open(rpath, "rb") as f:
                    att = MIMEApplication(f.read(), _subtype="pdf")
                    att.add_header(
                        "Content-Disposition", "attachment",
                        filename="Shrivi_Sakthisundaram_Resume.pdf",
                    )
                    msg.attach(att)

        with smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(EMAIL_CONFIG["email_address"], EMAIL_CONFIG["password"])
            s.sendmail(EMAIL_CONFIG["email_address"], to_addr, msg.as_string())

        message_id = msg["Message-ID"] or ""
        return True, "", message_id

    except smtplib.SMTPAuthenticationError as e:
        return False, f"Auth failed. Create an app password at myaccount.google.com/apppasswords. Error: {e}", ""
    except smtplib.SMTPRecipientsRefused as e:
        return False, f"BOUNCED - bad email: {e}", ""
    except Exception as e:
        return False, f"Send failed: {e}", ""


# ============================================================
# BACKFILL CHECK
# ============================================================
def check_and_backfill(companies, auto_allowed=False):
    """
    Check if we have enough pending companies to hit MIN_SENDS.
    When auto_allowed=False (default), logs the gap but does NOT trigger
    AI discovery — this prevents the doom loop where bounces trigger more
    hallucinated companies which bounce again.
    """
    # Count sent + pending per category
    cat_sent = {"healthcare": 0, "legal": 0, "finance": 0, "other": 0}
    cat_pending = {"healthcare": 0, "legal": 0, "finance": 0, "other": 0}

    for co in companies:
        v = co.get("vertical", "healthcare")
        cat = VERTICAL_TO_CATEGORY.get(v, "other")
        status = co.get("status", "pending")
        if status in ("sent", "dry_run"):
            cat_sent[cat] += 1
        elif status == "pending":
            cat_pending[cat] += 1

    needs_backfill = False
    for cat, target in MIN_SENDS.items():
        if cat == "total":
            continue
        have = cat_sent[cat] + cat_pending[cat]
        if have < target:
            needs_backfill = True
            logger.info(f"  {cat}: have {have} (sent:{cat_sent[cat]} pending:{cat_pending[cat]}), need {target}")

    if not needs_backfill:
        logger.info("All vertical targets covered. No backfill needed.")
        return companies

    if not auto_allowed:
        logger.info("Pipeline gap detected but auto-backfill is disabled.")
        logger.info("Run 'python discover.py --from-yc' or 'python discover.py --from-file leads.csv' to add real companies.")
        return companies

    logger.info("Running auto-backfill discovery...")
    try:
        from discover import backfill
        backfill()
        # Reload companies after backfill added new rows
        companies = load_companies()
        logger.info(f"After backfill: {len(companies)} total companies")
    except Exception as e:
        logger.error(f"Backfill failed: {e}")

    return companies


# ============================================================
# MAIN: SEND NEW EMAILS
# ============================================================
def age_pending_delivery(companies):
    """
    Move pending_delivery companies to 'sent' if they've been stuck for 3+ days.
    Gmail either delivered them or gave up by then.
    """
    aged = 0
    for co in companies:
        if co.get("status") != "pending_delivery":
            continue
        sent_date_str = co.get("sent_date", "")
        if not sent_date_str:
            # No sent date — assume they were sent a while ago, promote them
            co["status"] = "sent"
            aged += 1
            continue
        try:
            sent_date = datetime.fromisoformat(sent_date_str)
            if datetime.now() - sent_date > timedelta(days=3):
                co["status"] = "sent"
                aged += 1
        except (ValueError, TypeError):
            co["status"] = "sent"
            aged += 1
    if aged > 0:
        logger.info(f"Aged {aged} pending_delivery companies to 'sent'")
    return companies


def run_send():
    init_logs()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    companies = load_companies()

    # Archive dead companies before processing
    companies = cleanup_csv(companies)

    # Age stuck pending_delivery companies
    companies = age_pending_delivery(companies)
    save_companies(companies)

    # Check if we need to discover more companies first
    logger.info(f"{'='*60}")
    logger.info(f"COLD EMAIL AGENT v3 - SEND MODE")
    logger.info(f"Checking pipeline vs targets...")
    logger.info(f"{'='*60}")

    companies = check_and_backfill(companies, auto_allowed=False)

    pending = [c for c in companies if c["status"] == "pending"]

    # Show breakdown by vertical
    by_vert = {}
    for c in pending:
        v = c.get("vertical", "healthcare")
        by_vert[v] = by_vert.get(v, 0) + 1

    logger.info(f"\nPending breakdown:")
    for v, n in sorted(by_vert.items()):
        logger.info(f"  {v}: {n}")
    logger.info(f"  TOTAL: {len(pending)}")
    logger.info(f"Dry run: {SEND_CONFIG['dry_run']} | Max per run: {SEND_CONFIG['max_emails_per_run']}")
    logger.info(f"{'='*60}")

    # Round-robin: interleave verticals so all get coverage
    if len(by_vert) > 1:
        from itertools import zip_longest
        vert_buckets = {}
        for c in pending:
            v = c.get("vertical", "healthcare")
            vert_buckets.setdefault(v, []).append(c)
        interleaved = []
        for group in zip_longest(*vert_buckets.values()):
            for c in group:
                if c is not None:
                    interleaved.append(c)
        pending = interleaved
        logger.info(f"Round-robin order: {[c.get('vertical','?') for c in pending[:12]]}...")

    if not pending:
        logger.info("No pending companies. Run: python discover.py --auto")
        return

    sent = 0
    errors_this_run = 0

    # Track emails already sent or bounced to prevent duplicates and re-bounces
    emails_used = set()
    for co in companies:
        if co.get("status") in ("sent", "dry_run", "bounced") and co.get("email", "").strip():
            emails_used.add(co["email"].strip().lower())

    for co in pending:
        if sent >= SEND_CONFIG["max_emails_per_run"]:
            break

        logger.info(f"\n--- [{co.get('vertical','healthcare').upper()}] {co['company']} ({co['founders']}) ---")

        # Resolve email via scraping, Hunter, then pattern guessing
        email_to, email_method = resolve_email(co)
        if not email_to:
            if email_method == "no_mx":
                logger.warning(f"No MX records for {co['company']} - skipping")
                co["status"] = "skipped_no_mx"
            else:
                logger.warning(f"No email for {co['company']} - skipping")
                co["status"] = "skipped_no_email"
            save_companies(companies)
            continue

        # Dedup: skip if we already sent to this email address
        if email_to.lower() in emails_used:
            logger.warning(f"Duplicate email {email_to} (already sent to) - skipping {co['company']}")
            co["status"] = "skipped_duplicate_email"
            save_companies(companies)
            continue

        # Skip emails not on the verified allowlist — too high bounce risk
        # guess_catch_all is blocked: catch-all domains accept any RCPT TO,
        # so SMTP verification gives zero signal on deliverability.
        if REQUIRE_VERIFIED_EMAIL and email_method not in VERIFIED_CONTACT_METHODS:
            logger.warning(f"Skipping {co['company']}: email {email_to} is unverified (method: {email_method})")
            co["status"] = "needs_review"
            co["email"] = email_to
            co["contact_method"] = email_method
            save_companies(companies)
            continue

        logger.info(f"Email: {email_to} (method: {email_method})")

        # Generate
        logger.info("Generating email...")
        email_data = generate_email(co, client)
        if not email_data:
            co["status"] = "generation_failed"
            errors_this_run += 1
            log_sent(co["company"], co["founders"], email_to, "", "",
                     "generation_failed", "API error", "", co.get("vertical", ""))
            save_companies(companies)
            continue

        # Validate
        passed, issues = validate_email(email_data, co)
        if not passed:
            logger.warning(f"Guardrail issues: {issues}")
            logger.info(f"Retrying with lower temperature (0.3)...")
            email_data = generate_email(co, client, temperature=0.3)
            if email_data:
                passed, issues = validate_email(email_data, co)
            if not passed:
                logger.error(f"Still failing: {issues}. Skipping.")
                co["status"] = "guardrail_failed"
                errors_this_run += 1
                log_sent(co["company"], co["founders"], email_to,
                         email_data.get("subject", ""), email_data.get("body", ""),
                         "guardrail_failed", "; ".join(issues), "", co.get("vertical", ""))
                save_companies(companies)
                continue

        logger.info(f"PASSED | Subject: {email_data['subject']}")

        if SEND_CONFIG["dry_run"]:
            logger.info(f"[DRY RUN] To: {email_to}")
            logger.info(f"[DRY RUN] Vertical: {co.get('vertical', 'healthcare')}")
            logger.info(f"[DRY RUN] Body:\n{email_data['body'][:200]}...")
            co["status"] = "dry_run"
            co["sent_date"] = datetime.now().isoformat()
            co["sent_subject"] = email_data["subject"]
            log_sent(co["company"], co["founders"], email_to,
                     email_data["subject"], email_data["body"], "dry_run",
                     "", "", co.get("vertical", ""))
        else:
            ok, err, mid = send_email(email_to, email_data["subject"], email_data["body"])
            if ok:
                logger.info(f"SENT to {email_to}")
                co["status"] = "sent"
                co["sent_date"] = datetime.now().isoformat()
                co["sent_subject"] = email_data["subject"]
                co["message_id"] = mid
                log_sent(co["company"], co["founders"], email_to,
                         email_data["subject"], email_data["body"], "sent",
                         "", mid, co.get("vertical", ""))
            else:
                if "BOUNCED" in err:
                    co["status"] = "bounced"
                    logger.error(f"BOUNCED: {err}")
                else:
                    co["status"] = "send_failed"
                    logger.error(f"FAILED: {err}")
                errors_this_run += 1
                log_sent(co["company"], co["founders"], email_to,
                         email_data["subject"], email_data["body"],
                         co["status"], err, "", co.get("vertical", ""))
                save_companies(companies)
                continue

        sent += 1
        emails_used.add(email_to.lower())
        # Save after EACH successful send (bug fix from v1)
        save_companies(companies)

        if sent < SEND_CONFIG["max_emails_per_run"] and not SEND_CONFIG["dry_run"]:
            delay = random.randint(SEND_CONFIG["min_delay_seconds"], SEND_CONFIG["max_delay_seconds"])
            logger.info(f"Waiting {delay}s...")
            time.sleep(delay)

    save_companies(companies)

    # Summary
    _print_summary(companies)


def _print_summary(companies):
    """Print a summary of the campaign state."""
    statuses = {}
    vert_statuses = {}
    for c in companies:
        s = c.get("status", "unknown")
        v = c.get("vertical", "healthcare")
        cat = VERTICAL_TO_CATEGORY.get(v, "other")
        statuses[s] = statuses.get(s, 0) + 1
        vert_statuses.setdefault(cat, {})
        vert_statuses[cat][s] = vert_statuses[cat].get(s, 0) + 1

    logger.info(f"\n{'='*60}")
    logger.info(f"RUN COMPLETE | Total companies: {len(companies)}")
    logger.info(f"{'='*60}")
    for s, count in sorted(statuses.items()):
        logger.info(f"  {s}: {count}")

    logger.info(f"\nBy vertical category:")
    for cat in ["healthcare", "legal", "finance", "other"]:
        target = MIN_SENDS.get(cat, 0)
        cat_data = vert_statuses.get(cat, {})
        sent = cat_data.get("sent", 0) + cat_data.get("dry_run", 0)
        pending = cat_data.get("pending", 0)
        status_str = "OK" if (sent + pending) >= target else "NEEDS MORE"
        logger.info(f"  {cat}: sent={sent} pending={pending} target={target} [{status_str}]")

    logger.info(f"Log: {log_file}")
    logger.info(f"{'='*60}")


# ============================================================
# MAIN: SEND FOLLOW-UPS
# ============================================================
def run_followups():
    init_logs()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    companies = load_companies()

    cutoff = datetime.now() - timedelta(days=SEND_CONFIG["follow_up_days"])
    max_followups = SEND_CONFIG.get("max_follow_ups", 1)
    needs_followup = []
    for co in companies:
        if co.get("status") != "sent":
            continue
        # Check follow-up count against max
        followup_count = int(co.get("followup_count", 0) or 0)
        if followup_count >= max_followups:
            continue
        # Check if enough time has passed since last contact
        sent_date_str = co.get("sent_date", "")
        if sent_date_str:
            try:
                sent_date = datetime.fromisoformat(sent_date_str)
                if sent_date < cutoff:
                    needs_followup.append(co)
            except (ValueError, TypeError):
                pass

    logger.info(f"{'='*60}")
    logger.info(f"FOLLOW-UP MODE | {len(needs_followup)} companies need follow-up")
    logger.info(f"{'='*60}")

    sent = 0
    for co in needs_followup:
        if sent >= 17:
            break

        logger.info(f"\n--- Follow-up: [{co.get('vertical', 'healthcare').upper()}] {co['company']} ---")
        # Use resolve_email for consistency, but prefer the email we originally sent to
        email_to = co.get("email", "").strip()
        if not email_to:
            email_to, _ = resolve_email(co)
        if not email_to:
            logger.warning(f"No email for {co['company']} follow-up - skipping")
            co["followup_status"] = "skipped_no_email"
            save_companies(companies)
            continue
        orig_subject = co.get("sent_subject", "Duke freshman building AI clinical tools - summer help?")

        fu = generate_followup(co, orig_subject, client)
        if not fu:
            co["followup_status"] = "generation_failed"
            continue

        # Guardrail: detect inverted framing (sounds like WE are hiring THEM)
        fu_body_lower = fu["body"].lower()
        inversion_phrases = [
            "we'd love to have you", "we're finalizing", "our summer team",
            "love to have you involved", "have you on board", "join our team",
            "we're building our team", "our growing team",
        ]
        if any(phrase in fu_body_lower for phrase in inversion_phrases):
            logger.warning(f"Follow-up for {co['company']} has INVERTED FRAMING. Regenerating...")
            fu = generate_followup(co, orig_subject, client)
            if not fu:
                co["followup_status"] = "generation_failed"
                continue
            # Check again — if still inverted, skip
            fu_body_lower = fu["body"].lower()
            if any(phrase in fu_body_lower for phrase in inversion_phrases):
                logger.error(f"Follow-up for {co['company']} still inverted after retry. Skipping.")
                co["followup_status"] = "guardrail_failed"
                continue

        followup_count = int(co.get("followup_count", 0) or 0)

        if SEND_CONFIG["dry_run"]:
            logger.info(f"[DRY RUN] Follow-up to: {email_to}")
            logger.info(f"[DRY RUN] Body: {fu['body'][:150]}...")
            co["followup_status"] = "dry_run"
            co["followup_count"] = followup_count + 1
            log_followup(co["company"], email_to, fu["subject"], fu["body"],
                         "dry_run", co.get("sent_date", ""), co.get("vertical", ""))
        else:
            ok, err, mid = send_email(email_to, fu["subject"], fu["body"],
                                       in_reply_to=co.get("message_id", ""))
            if ok:
                logger.info(f"Follow-up SENT to {email_to}")
                co["followup_status"] = "sent"
                co["followup_count"] = followup_count + 1
                log_followup(co["company"], email_to, fu["subject"], fu["body"],
                             "sent", co.get("sent_date", ""), co.get("vertical", ""))
            else:
                logger.error(f"Follow-up FAILED: {err}")
                co["followup_status"] = "failed"
                log_followup(co["company"], email_to, fu["subject"], fu["body"],
                             "failed", co.get("sent_date", ""), co.get("vertical", ""))

        sent += 1
        save_companies(companies)

        if sent < len(needs_followup):
            delay = random.randint(60, 180)
            time.sleep(delay)

    save_companies(companies)
    logger.info(f"\nFollow-ups processed: {sent}")


# ============================================================
# STATUS REPORT
# ============================================================
def run_status():
    companies = load_companies()

    # Overall
    statuses = {}
    for c in companies:
        s = c.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1

    print(f"\n{'='*60}")
    print(f"CAMPAIGN STATUS - {len(companies)} companies")
    print(f"{'='*60}")
    for s, count in sorted(statuses.items()):
        print(f"  {s}: {count}")

    # Per vertical category
    print(f"\n--- BY VERTICAL ---")
    cat_data = {}
    for c in companies:
        v = c.get("vertical", "healthcare")
        cat = VERTICAL_TO_CATEGORY.get(v, "other")
        cat_data.setdefault(cat, {"total": 0, "sent": 0, "pending": 0, "failed": 0, "bounced": 0})
        cat_data[cat]["total"] += 1
        st = c.get("status", "pending")
        if st in ("sent", "dry_run"):
            cat_data[cat]["sent"] += 1
        elif st == "pending":
            cat_data[cat]["pending"] += 1
        elif st in ("bounced", "send_failed", "guardrail_failed", "generation_failed"):
            cat_data[cat]["failed"] += 1

    for cat in ["healthcare", "legal", "finance", "other"]:
        target = MIN_SENDS.get(cat, 0)
        d = cat_data.get(cat, {"total": 0, "sent": 0, "pending": 0, "failed": 0})
        have = d["sent"] + d["pending"]
        status = "OK" if have >= target else f"NEED {target - have} MORE"
        print(f"  {cat.upper()}: {d['total']} total | {d['sent']} sent | {d['pending']} pending | target: {target} [{status}]")

    # Per sub-vertical detail
    print(f"\n--- DETAILED VERTICALS ---")
    sub_data = {}
    for c in companies:
        v = c.get("vertical", "healthcare")
        sub_data.setdefault(v, {"total": 0, "sent": 0, "pending": 0})
        sub_data[v]["total"] += 1
        st = c.get("status", "pending")
        if st in ("sent", "dry_run"):
            sub_data[v]["sent"] += 1
        elif st == "pending":
            sub_data[v]["pending"] += 1

    for v in sorted(sub_data.keys()):
        d = sub_data[v]
        print(f"  {v}: {d['total']} total ({d['sent']} sent, {d['pending']} pending)")

    # Needs review (unverified emails — won't send until manually verified)
    needs_review = [c for c in companies if c.get("status") == "needs_review"]
    if needs_review:
        print(f"\nNEEDS REVIEW ({len(needs_review)}) — unverified emails, won't auto-send:")
        for c in needs_review:
            print(f"  {c['company']} [{c.get('vertical', '?')}] - {c.get('email', '')} ({c.get('contact_method', '?')})")
        print(f"  To approve: change contact_method to 'email' and status to 'pending' in companies.csv")

    # Bounced
    bounced = [c for c in companies if c.get("status") == "bounced"]
    if bounced:
        print(f"\nBOUNCED ({len(bounced)}):")
        for c in bounced:
            print(f"  {c['company']} [{c.get('vertical', '?')}] - {c.get('email', '')}")

    # Responded
    responded = [c for c in companies if c.get("status") == "responded"]
    if responded:
        print(f"\nRESPONDED ({len(responded)}):")
        for c in responded:
            print(f"  {c['company']} [{c.get('vertical', '?')}]")

    # Needs follow-up
    cutoff = datetime.now() - timedelta(days=SEND_CONFIG["follow_up_days"])
    needs_fu = [c for c in companies
                if c.get("status") == "sent"
                and c.get("followup_status", "") == ""
                and c.get("sent_date", "")]
    ready = []
    for c in needs_fu:
        try:
            if datetime.fromisoformat(c["sent_date"]) < cutoff:
                ready.append(c)
        except:
            pass
    if ready:
        print(f"\nREADY FOR FOLLOW-UP ({len(ready)}):")
        for c in ready:
            print(f"  {c['company']} [{c.get('vertical', '?')}] - sent {c.get('sent_date', '')[:10]}")

    # Formal applications
    formal = [c for c in companies
              if "formal" in c.get("hook_notes", "").lower()
              or "posting" in c.get("hook_notes", "").lower()]
    if formal:
        print(f"\nAPPLY FORMALLY TOO ({len(formal)}):")
        for c in formal:
            print(f"  {c['company']} [{c.get('vertical', '?')}]")

    print(f"{'='*60}\n")


# ============================================================
# ENTRY
# ============================================================
if __name__ == "__main__":
    if EMAIL_CONFIG["password"] == "YOUR_GMAIL_APP_PASSWORD":
        print("\n!! Fill in config.py first. See README for setup steps.\n")
        sys.exit(1)
    if ANTHROPIC_API_KEY == "YOUR_ANTHROPIC_API_KEY":
        print("\n!! Set your Anthropic API key in config.py\n")
        sys.exit(1)

    # CLI flag overrides for dry_run
    if "--live" in sys.argv:
        SEND_CONFIG["dry_run"] = False
        sys.argv.remove("--live")
    elif "--dry-run" in sys.argv:
        SEND_CONFIG["dry_run"] = True
        sys.argv.remove("--dry-run")

    # CLI flag for max emails per run
    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        if idx + 1 < len(sys.argv):
            SEND_CONFIG["max_emails_per_run"] = int(sys.argv[idx + 1])
            sys.argv.pop(idx + 1)
            sys.argv.pop(idx)

    mode = sys.argv[1] if len(sys.argv) > 1 else "send"

    if mode == "send":
        run_send()
    elif mode == "followup":
        run_followups()
    elif mode == "status":
        run_status()
    else:
        print("Usage: python agent.py [send|followup|status] [--live|--dry-run] [--max N]")
