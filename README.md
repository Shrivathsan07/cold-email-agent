# Cold Email Agent v3 - Multi-Vertical

Sends personalized cold emails + auto follow-ups to startup founders across multiple industries.

> **Also in this repo: the [Recruiting Command Center](RECRUITING.md).** Pulls open
> SWE, PM and deployed-engineering roles from nine GitHub job boards every morning,
> ranks them for big tech, emails you a short list, tracks your pipeline and
> outreach, and runs a LeetCode plan. `python3 -m recruit setup` to start.

**Targets:** 25+ Healthcare AI | 10 Legal AI | 10 Finance AI | 5 Supply Chain/Cyber/Defense

## Quick Start (if upgrading from v2)

1. Replace `agent.py`, `discover.py`, and `config.py` with the new versions
2. Fill in your credentials in `config.py` (same as before)
3. Your existing `companies.csv` will be auto-upgraded (adds `vertical` column)
4. Run discovery to populate new verticals:
```bash
python3 discover.py --auto
```
5. Dry run to test:
```bash
python3 agent.py send
```
6. When ready, set `dry_run: False` in config.py and send for real.

## Setup (fresh install, ~10 minutes)

### Step 1: Install Python + dependency
```bash
cd ~/Desktop/cold-email-agent
pip3 install anthropic
```

### Step 2: Get credentials
- **Anthropic API key:** console.anthropic.com > API Keys > Create
- **Gmail App Password:** myaccount.google.com/apppasswords > Mail > Mac
- **Hunter.io API key (optional, not required):** hunter.io > Sign up free > Dashboard > API Keys
  - Free tier: 25 email searches + 50 verifications per month
  - The agent already scrapes websites for real emails. Hunter is a bonus verification layer.

### Step 3: Fill in config.py
```python
"password": "your 16 char app password here",
ANTHROPIC_API_KEY = "sk-ant-your-key-here"
# Hunter is OPTIONAL. The agent scrapes websites for emails by default.
# HUNTER_API_KEY = "your-hunter-key-here"   # uncomment + set enabled: True to use
```

### Step 4: Discover companies across all verticals
```bash
python3 discover.py --auto
```

### Step 5: Test (dry run)
```bash
python3 agent.py send
```

### Step 6: Send for real
Set `"dry_run": False` in config.py, then:
```bash
python3 agent.py send
```

## Commands

```bash
# ---- DISCOVERY ----
python3 discover.py --auto                    # Discover across ALL verticals
python3 discover.py --auto --vertical legal   # Discover only legal AI startups
python3 discover.py --auto --vertical finance # Discover only finance AI startups
python3 discover.py --backfill                # Auto-fill gaps vs minimum targets

# ---- SENDING ----
python3 agent.py send                         # Send to all pending (auto-backfills if short)
python3 agent.py followup                     # Send follow-ups (5+ days, no reply)
python3 agent.py status                       # Full campaign status by vertical

# ---- FULL WORKFLOW ----
python3 discover.py --auto && python3 agent.py send
```

## How It Works

### Multi-Vertical Pipeline
The agent maintains separate pipelines for each vertical:
- **Healthcare (25+ min):** Clinical AI, digital health, patient communication
- **Legal (10 min):** Contract review, litigation, compliance, regulatory
- **Finance (10 min):** Fraud detection, risk management, regtech, AML/KYC
- **Other (5 min):** Supply chain, cybersecurity, defense (combined)

### Auto-Backfill
Before each send run, the agent checks if it has enough pending + sent companies to hit the minimums. If any vertical is short, it automatically runs discovery to fill the gap (with buffer for bounces/errors).

After a send run with errors, it checks again and backfills if needed.

### Vertical-Aware Emails
Each vertical gets different voice rules:
- **Healthcare:** Leads with AphasiaGPT, clinical workflow experience
- **Legal:** Leads with transferable skills (regulated AI tools) + curiosity about legal problems
- **Finance:** Leads with transferable skills + consulting/strategy background
- **Other:** Leads with builder identity + honest curiosity

### Email Generation
1. **Load** pending companies from companies.csv
2. **Generate** personalized email via Claude Haiku with temperature 0.6 (~$0.01 each)
3. **Validate** against vertical-specific guardrails
4. **Retry** up to 2x if guardrails fail, skip if still failing
5. **Send** via Gmail SMTP with 2-6 min random delays
6. **Save** CSV after EACH send (prevents data loss)

### Email Resolution (how it finds real emails)
For each company, the agent tries to find the real founder email in this order:
1. **Confirmed email in CSV** — If you already have a verified email, it uses it.
2. **Web scrape the company website** — Hits the homepage, /about, /team, /contact pages and extracts every email address. Then ranks them: founder name matches score highest, then founders@, then personal-looking emails, then generic ones. No API key needed, completely free.
3. **Hunter.io Email Finder** (optional) — If web scraping finds nothing, tries Hunter's API to look up the founder by name + domain.
4. **Hunter.io Verifier** (optional) — Can verify any scraped or guessed email is deliverable before sending.
5. **Pattern guessing fallback** — Only as a last resort: tries founders@domain, firstname@domain, firstname.lastname@domain.

Most of the time, the web scraper finds real emails directly from the company's website, which is exactly what you'd do if you looked it up yourself. Hunter is there as an optional backup.

### Follow-ups
- Auto-sent 5 days after initial email (same thread)
- Short (<75 words), casual, one paragraph
- Max 1 follow-up per company

### Guardrails
Every email is checked for:
- Banned phrases (cover letter cliches, em dashes)
- Required phrases (Duke always; AphasiaGPT for healthcare)
- Word count (150-350)
- Company name mentioned
- No mention of formal job postings
- Proper signature

## Files
- `config.py` — credentials, verticals, voice rules, guardrails
- `agent.py` — main agent (send/followup/status + auto-backfill)
- `discover.py` — multi-vertical company discovery
- `companies.csv` — target list with vertical column
- `resume.pdf` — attached to every email
- `sent_emails_log.csv` — full send history
- `followup_log.csv` — follow-up history
- `logs/` — detailed run logs

## Verticals Available
| Vertical | Config Key | Category | Min Target |
|---|---|---|---|
| Healthcare AI | healthcare | healthcare | 25 |
| Legal AI | legal | legal | 10 |
| Finance AI | finance | finance | 10 |
| Supply Chain AI | supply_chain | other | 5 (shared) |
| Cybersecurity AI | cybersecurity | other | 5 (shared) |
| Defense/GovTech AI | defense | other | 5 (shared) |

## Launchd Schedule (Mac)

Update your existing plist files to use the new workflow:
```bash
# Morning discover + send (weekdays 7am)
python3 discover.py --backfill && python3 agent.py send

# Follow-ups (weekdays 8am)
python3 agent.py followup
```

## Safety
- **Dry run by default** — nothing sends until you flip the switch
- Gmail daily limit: ~500/day. We send 40 max per run. You're fine.
- 2-6 min random delays between emails
- Bounced emails logged and skipped
- CSV saved after every single send
- Password in plaintext in config.py — don't push to GitHub
