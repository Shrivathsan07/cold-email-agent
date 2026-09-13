# Recruiting Command Center

A system for running your own recruiting season instead of reacting to it.

It pulls open roles from nine public GitHub job boards every morning, ranks them
against what you are actually going after (SWE, PM, deployed/solutions, big tech),
emails you a short list you can finish before class, tracks every application and
every person you reach out to, and runs a LeetCode plan that does not need an
interview on the calendar to be worth doing.

```
python3 -m recruit setup     # one time
python3 -m recruit sync      # pull the boards
python3 -m recruit report    # today's brief
```

---

## Why it is built this way

The problem you described is not "I cannot find jobs." It is that you have been
applying to whatever you see. Three things follow from that, and they are the
three design decisions in this system.

**A short list beats a complete one.** The boards have ~7,000 live listings. About
2,300 match your tracks. If the daily email handed you 2,300 you would skim it and
apply to nothing. It hands you eight, capped at two per company, and tells you why
each one is on the list. Finishing the list is the point.

**Speed matters more than polish for these roles.** Big-company new grad and
internship reqs get thousands of applicants in the first week and many are
effectively closed long before they come down. So freshness is weighted almost as
heavily as company tier in the ranking, and anything older than 21 days drops off
entirely. A perfect application in week three loses to a good one on day one.

**The pipeline is the actual product.** Applying is the easy part to track and the
least predictive. Response rate, referral rate, and how many live conversations you
have are what tell you whether the season is working. `recruit stats` shows those.

---

## The daily loop

Ten minutes in the morning, twenty if you are doing outreach.

1. Open the brief in your inbox (or `python3 -m recruit report`).
2. Work the **Needs you first** block. OA deadlines and silent applications
   outrank anything new.
3. Work **Apply today**. Eight roles, ranked. For each one you do:
   `python3 -m recruit applied <id>`
4. Do the **LeetCode** set. Two new problems plus whatever review is due:
   `python3 -m recruit lc log <slug> solved --minutes 25`
5. Once or twice a week, work one **Outreach** suggestion.

Marking things done is what makes the next day's brief good. An unmarked
application means the system keeps showing you that role and never nudges you to
follow up on it.

---

## Where the roles come from

| Source | What it covers |
|---|---|
| SimplifyJobs/New-Grad-Positions | new grad SWE, AI/ML, product, quant |
| SimplifyJobs/Summer-Internships | internships, all the above |
| vanshb03/New-Grad + Summer-Internships | independent listing set, catches things Simplify misses |
| speedyapply/SWE-College-Jobs | SWE intern + new grad, with salary and a FAANG+ section |
| speedyapply/AI-College-Jobs | AI/ML roles |
| jobright-ai/Product-Management-Internship | the best PM internship coverage of the lot |
| jobright-ai/Product-Management-New-Grad | PM new grad |

These repos get renamed every cycle (`Summer2026-Internships` becomes
`Summer2027-Internships`). Each source is configured with a list of candidate URLs
and the fetcher walks them until one works, so the system survives the rollover
without a code change. If a source does go dark permanently, `sync` prints
`UNAVAILABLE` for it and keeps going with the rest.

Listings are deduplicated across sources on company plus title, and locations are
merged, so one req posted to four boards is one line in your brief.

### Deployed and forward-deployed roles are the exception

There are only about 18 of these live across all nine boards right now, and almost
none at the big companies, because the boards are built around SWE and PM. The
system tells you the truth about that rather than padding the list: every Monday
the brief includes a hand-check list of the companies where deployed/solutions
engineering is a real career track with real headcount, with direct links to their
career pages. Palantir, Anthropic, OpenAI, Scale, Databricks, Snowflake, Samsara,
Applied Intuition and a few more. Five minutes of clicking, once a week.

---

## How the ranking works

Score out of 100, roughly:

- **Company tier, up to 46.** Big Tech 46, strong tech 33, quant 20, everything
  else 12. Edit `recruit/data/companies.json` to move a company.
- **Freshness, up to 26.** Full marks the day it is posted, zero by day 15.
- **Location, 10.** One of your `PREFERRED_LOCATIONS`.
- **Small signals.** Published salary, FAANG+ section, explicit sponsorship offer,
  a term in the title that says it is a real seasonal req.

Filtered out before scoring: wrong track, too senior (anything past "Engineer I"),
PhD-only, clearance or citizenship required if you flagged that, excluded
locations, older than 21 days, and anything you already applied to or dismissed.

Track classification runs deployed/solutions patterns first, then PM, then SWE,
because "Solutions Engineer" contains the word "Engineer" and would otherwise be
filed as SWE. Hardware, mechanical, clinical, sales and analyst titles are dropped
outright.

If you are seeing roles you do not want, `python3 -m recruit dismiss <id>` and they
stay gone. If a whole category is wrong, edit `NEGATIVE_PATTERNS` in
`recruit/score.py`.

---

## The LeetCode system

Bank is the NeetCode 150, which contains all of Blind 75, vendored locally so this
works with no account and no network.

Each day you get two things:

**New problems**, in NeetCode roadmap order. You finish a pattern before starting
the next one, because pattern recognition is the thing that transfers and doing a
random problem a day does not build it. Blind 75 problems come first inside each
pattern.

**Reviews**, on a spaced schedule. When you log a problem, the next review is set
by how it went: clean solve pushes it out 3, 7, 16, 35, 90 days; needing a hint is
tighter; a failure resets to tomorrow. This is the part that matters before you
have interviews. Without it you will have "done" Arrays and Hashing in September
and be unable to solve any of it in January.

```bash
python3 -m recruit lc plan                              # today's set
python3 -m recruit lc log two-sum solved --minutes 14   # slug or part of the title
python3 -m recruit lc log "Valid Anagram" hint
python3 -m recruit lc stats                             # coverage per pattern
```

Ratings are `solved` (clean, no help), `hint` (looked something up), `struggled`
(got there, slowly, ugly), `failed` (did not get there). Be honest with these. The
schedule is only as good as the ratings.

**Interview mode** turns on automatically when any application is at `oa`, `phone`
or `onsite`, or has an OA deadline within 14 days. Volume goes up and the queue
reorders toward the patterns that actually show up in phone screens.

---

## Finding people

Read this part before you use it, because it is the part where you can do damage.

This does **not** scrape LinkedIn. LinkedIn's terms forbid it, scraped-data tools
get accounts restricted, and losing your LinkedIn in October would cost you more
than every referral it could ever find. What it does instead is generate the exact
searches that surface the right people in about fifteen seconds each, ranked by who
is actually likely to help you.

```bash
python3 -m recruit people "Anthropic" --track dte --team "solutions"
```

You get four target types, in yield order:

1. **Alumni from your school.** Highest reply rate by a wide margin. Shared school
   is the single strongest predictor of a stranger answering you.
2. **Recent grads and current interns.** One to two years in. They remember being
   you, they are not busy enough to ignore you, and they usually have unused
   referral links.
3. **University / campus recruiter.** The one person whose literal job is moving
   your resume. Keep it to three sentences.
4. **Hiring manager.** Lowest reply rate, highest payoff. Only worth it if you have
   something specific to say about their team's work.

Then track it:

```bash
python3 -m recruit contact add --company "Anthropic" --name "Jane Doe" \
    --title "University Recruiter" --kind recruiter --linkedin <url>
python3 -m recruit draft c0001        # LinkedIn note + email version
python3 -m recruit contact sent c0001
python3 -m recruit contact replied c0001
```

`draft` writes a LinkedIn connection note that fits in the 300 character limit, and
an email version. If you set `ANTHROPIC_API_KEY` it uses Claude to sharpen it;
without a key you get a solid template. Either way, read it before you send it and
change one thing so it sounds like you.

On email addresses: for a handful of big companies the system knows the published
address convention and will show you a guess. Treat it as a guess. For first
contact at a big company, LinkedIn beats cold email anyway. A cold email to a
recruiter is worth sending; a cold email to a hiring manager you have no connection
to mostly is not.

---

## Commands

```bash
python3 -m recruit sync                       # pull every board, rank, diff against last run
python3 -m recruit report                     # today's brief
python3 -m recruit report --email             # mail it to yourself
python3 -m recruit report --html brief.html   # save the HTML version

python3 -m recruit list --track pm --tier tier1 --limit 20
python3 -m recruit list --track dte
python3 -m recruit show <job_id>

python3 -m recruit applied <job_id> [--referral "Jane Doe"]
python3 -m recruit shortlist <job_id>
python3 -m recruit dismiss <job_id> --reason "wrong team"
python3 -m recruit stage <job_id> oa --deadline 2026-09-28
python3 -m recruit stage <job_id> phone --next "send thank you" --on 2026-09-29
python3 -m recruit pipeline

python3 -m recruit people "Stripe" --track swe --team "payments infra"
python3 -m recruit contact add|list|sent|replied
python3 -m recruit draft <contact_id>

python3 -m recruit lc plan|log|stats
python3 -m recruit stats
```

Stages are `applied`, `oa`, `phone`, `onsite`, `offer`, `rejected`, `ghosted`,
`withdrawn`. Mark rejections. A funnel with no rejections in it cannot tell you
anything.

---

## Automating it

**GitHub Actions** (`.github/workflows/recruiting-brief.yml`) runs weekday mornings
at 11:00 UTC and Sunday evening, syncs, emails you the brief, and commits the state
files so the next run remembers this one.

Add these repository secrets under Settings → Secrets and variables → Actions:

| Secret | What |
|---|---|
| `RECRUIT_EMAIL_ADDRESS` | the Gmail you send from |
| `RECRUIT_EMAIL_PASSWORD` | a Gmail **app password**, not your login ([myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)) |
| `RECRUIT_EMAIL_TO` | where the brief goes, if different |
| `RECRUIT_PROFILE_JSON` | optional, e.g. `{"school":"Duke","needs_sponsorship":false}` |
| `ANTHROPIC_API_KEY` | optional, sharpens outreach drafts |

**Locally** instead, `./run_recruiting_brief.sh` does the same thing. Cron:

```
0 7 * * 1-5 /path/to/cold-email-agent/run_recruiting_brief.sh
```

On a Mac, cron does not fire while the machine is asleep. Use launchd with
`RunAtLoad` set so it catches up on wake, the same way this repo's existing
`run_morning.sh` handles it.

**Keep this repository private.** `data/` holds your application pipeline, who you
contacted, and where you got rejected.

---

## Files

```
recruit/
  sources.py    the nine job boards, their parsers, dedupe
  score.py      track classification, company tiers, eligibility, ranking
  store.py      CSV state
  leetcode.py   curriculum + spaced repetition
  outreach.py   people research, templates, drafting
  report.py     the daily brief, text and HTML
  mailer.py     SMTP
  cli.py        commands
  data/
    companies.json      company tiers, edit this to re-rank a company
    leetcode_bank.json  NeetCode 150, vendored

data/
  jobs.csv          full listing cache, gitignored, rebuilt every sync
  job_state.csv     first_seen and your verdict per listing, committed
  applications.csv  the pipeline
  contacts.csv      people
  leetcode_log.csv  every attempt
  state.json        last sync

recruit_config.py   your settings and secrets, gitignored
```

Everything is plain CSV. Open it in Excel, fix it by hand, the system will pick up
your edits.

No dependencies outside the standard library. `anthropic` is optional and only
used for outreach drafts.

---

## Things that will help more than this system will

Said plainly, because you asked for tips and the honest ones are not features.

**Referrals are the whole game at big tech.** A referred application at a large
company gets looked at by a human; an unreferred one competes with ten thousand
others in an ATS. One referral is worth more than fifty cold applications. This is
why outreach is in the daily loop and not a side feature, and why the system nudges
you toward a person at every company you apply to. If you do one thing differently
this season, make it this.

**Apply in the first week or do not bother.** For the companies you want, reqs fill
from the early pile. This is baked into the ranking, and it is also why the brief
runs at 7am. A role you see on day one and apply to on day ten is a role you did
not apply to.

**Your application volume target is a floor, not a ceiling, and it is not the
metric.** Five a day is enough if they are targeted and fast. Fifty a day of
whatever you see is what you were already doing.

**Keep two resumes, not one.** A SWE version and a PM version. The deployed/
solutions roles take the SWE one with the customer-facing work pulled to the top.
Three versions is too many to maintain in season.

**The thing that gets you the deployed/forward-deployed roles is different.** Those
teams hire for "can talk to a customer and then go fix it," and they weight
demonstrated shipping and communication far above LeetCode. Your cold email agent
and AphasiaGPT are better evidence for that track than another medium problem is.
Lead with them.

**Track rejections and read them as a batch.** Twelve rejections at the resume
screen means the resume. Twelve after the phone screen means the prep. You cannot
tell which without the data, which is why `stage` takes `rejected`.

**Do not let the LeetCode streak become the work.** It is the thing you do when the
applications and outreach are already done. The daily brief puts it third on
purpose.
