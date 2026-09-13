"""
The daily digest: one email that tells you exactly what to do today.

Structure is deliberate. Apply-today comes first because it is time-sensitive
and everything else can slip a day. The pipeline section is second because
following up on a live application beats starting a new one. LeetCode and
outreach come last because they are the parts you do when the urgent stuff is
already handled.
"""

import html
from datetime import date, datetime, timedelta

from . import leetcode, outreach, settings, store

STAGE_ORDER = ["applied", "oa", "phone", "onsite", "offer", "rejected", "ghosted", "withdrawn"]
LIVE_STAGES = {"applied", "oa", "phone", "onsite"}
TRACK_NAMES = {"swe": "SWE", "pm": "PM", "dte": "Deployed/Solutions"}
TIER_NAMES = {"tier1": "Big Tech", "tier2": "Strong tech", "quant": "Quant", "other": ""}


# ---------------------------------------------------------------------------
# Digest assembly
# ---------------------------------------------------------------------------
def build(today=None):
    today = today or date.today()
    limits = settings.REPORT_LIMITS
    jobs = store.load_jobs()
    apps = store.load_applications()
    applied_ids = {a["job_id"] for a in apps}

    live = [
        j for j in jobs
        if j.get("status") in ("new", "shortlisted")
        and j["id"] not in applied_ids
        and j.get("track")
    ]
    for j in live:
        j["_score"] = float(j.get("score") or 0)
    live.sort(key=lambda j: -j["_score"])

    new_today = [j for j in live if j.get("first_seen") == today.isoformat()]

    # Cap how many roles one company can take. Five Lyft postings at the top
    # is a worse morning than five different companies.
    apply_now, spillover, per_company = [], [], {}
    for job in live:
        key = (job.get("company_canonical") or job.get("company", "")).lower()
        if per_company.get(key, 0) >= 2 or len(apply_now) >= limits.get("apply_today", 8):
            spillover.append(job)
            continue
        per_company[key] = per_company.get(key, 0) + 1
        apply_now.append(job)
    also = []
    for job in spillover:
        key = (job.get("company_canonical") or job.get("company", "")).lower()
        if per_company.get(key, 0) >= 3:
            continue
        per_company[key] = per_company.get(key, 0) + 1
        also.append(job)
        if len(also) >= limits.get("also_worth_it", 6):
            break

    return {
        "date": today,
        "apply_now": apply_now,
        "also": also,
        "new_today_count": len(new_today),
        "live_count": len(live),
        "nudges": _pipeline_nudges(apps, today),
        "pipeline": _pipeline_summary(apps),
        "leetcode": leetcode.plan_today(),
        "leetcode_stats": leetcode.stats(),
        "outreach": outreach.suggest_targets(limits.get("outreach_suggestions", 3)),
        "contacts_due": _contacts_due(today),
        "pace": _pace(apps, today),
        "dte_watchlist": outreach.DTE_WATCHLIST if today.weekday() == 0 else [],
    }


def _pipeline_nudges(apps, today):
    """Applications that need you to do something, most urgent first."""
    out = []
    for app in apps:
        stage = app.get("stage", "")
        if stage not in LIVE_STAGES:
            continue

        deadline = app.get("oa_deadline")
        if deadline:
            try:
                left = (datetime.fromisoformat(deadline).date() - today).days
                if left <= 7:
                    out.append({
                        "urgency": 0 if left <= 2 else 1,
                        "company": app.get("company", ""),
                        "title": app.get("title", ""),
                        "job_id": app.get("job_id", ""),
                        "what": f"OA due in {left}d ({deadline})" if left >= 0 else f"OA deadline passed ({deadline})",
                    })
                    continue
            except ValueError:
                pass

        if app.get("next_action_on"):
            try:
                if datetime.fromisoformat(app["next_action_on"]).date() <= today:
                    out.append({
                        "urgency": 1,
                        "company": app.get("company", ""),
                        "title": app.get("title", ""),
                        "job_id": app.get("job_id", ""),
                        "what": app.get("next_action") or "follow up",
                    })
                    continue
            except ValueError:
                pass

        quiet = store.days_since(app.get("last_touch") or app.get("applied_on"))
        if quiet is not None and quiet >= settings.FOLLOWUP_AFTER_DAYS:
            out.append({
                "urgency": 2,
                "company": app.get("company", ""),
                "title": app.get("title", ""),
                "job_id": app.get("job_id", ""),
                "what": f"silent {quiet}d since {stage}. Follow up or mark it ghosted so it stops taking up space.",
            })

    out.sort(key=lambda x: x["urgency"])
    return out[:8]


def _contacts_due(today):
    out = []
    for c in store.load_contacts():
        if c.get("status") != "reached_out" or c.get("replied") == "yes":
            continue
        quiet = store.days_since(c.get("last_contact"))
        if quiet is not None and quiet >= 7 and int(c.get("followups") or 0) < 1:
            out.append({
                "contact_id": c.get("contact_id", ""),
                "name": c.get("name", ""),
                "company": c.get("company", ""),
                "days": quiet,
            })
    return out[:5]


def _pipeline_summary(apps):
    counts = {stage: 0 for stage in STAGE_ORDER}
    for app in apps:
        stage = app.get("stage", "applied")
        counts[stage] = counts.get(stage, 0) + 1
    counts["total"] = len(apps)
    counts["live"] = sum(counts.get(s, 0) for s in LIVE_STAGES)
    return counts


def _pace(apps, today):
    week_ago = (today - timedelta(days=7)).isoformat()
    this_week = [a for a in apps if (a.get("applied_on") or "") >= week_ago]
    contacts = store.load_contacts()
    reached = [c for c in contacts
               if (c.get("first_contact") or "") >= week_ago and c.get("status") not in ("to_find", "found")]
    target_apps = settings.TARGETS.get("applications_per_day", 5) * 7
    target_out = settings.TARGETS.get("outreach_per_week", 10)
    return {
        "applications_7d": len(this_week),
        "applications_target_7d": target_apps,
        "outreach_7d": len(reached),
        "outreach_target_7d": target_out,
        "on_pace": len(this_week) >= target_apps * 0.7,
    }


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------
def render_text(d):
    L = []
    add = L.append
    add(f"RECRUITING BRIEF - {d['date'].strftime('%a %b %d, %Y')}")
    add("=" * 64)
    pace = d["pace"]
    add(f"Applications last 7d: {pace['applications_7d']}/{pace['applications_target_7d']}"
        f"   Outreach last 7d: {pace['outreach_7d']}/{pace['outreach_target_7d']}")
    p = d["pipeline"]
    add(f"Pipeline: {p['live']} live of {p['total']} total  "
        f"(OA {p.get('oa', 0)}, phone {p.get('phone', 0)}, onsite {p.get('onsite', 0)}, offer {p.get('offer', 0)})")
    add(f"Board: {d['live_count']} open roles match you, {d['new_today_count']} posted today")
    add("")

    if d["nudges"]:
        add("NEEDS YOU FIRST")
        add("-" * 64)
        for n in d["nudges"]:
            add(f"  [{n['job_id'][:8]}] {n['company']} - {n['title'][:44]}")
            add(f"      {n['what']}")
        add("")

    add(f"APPLY TODAY ({len(d['apply_now'])})")
    add("-" * 64)
    if not d["apply_now"]:
        add("  Nothing new above the bar. Use the time for outreach or LeetCode.")
    for j in d["apply_now"]:
        tier = TIER_NAMES.get(j.get("tier"), "")
        add(f"  {j['_score']:>5.0f}  {j.get('company_canonical') or j['company']}"
            f"  [{TRACK_NAMES.get(j.get('track'), j.get('track', ''))}{', ' + tier if tier else ''}]")
        add(f"         {j['title'][:70]}")
        add(f"         {j.get('locations', '')[:66]}")
        add(f"         {j.get('reasons', '')}")
        add(f"         {j.get('url', '')}")
        add(f"         mark done:  python3 -m recruit applied {j['id']}")
        add("")

    if d["also"]:
        add("ALSO WORTH A LOOK")
        add("-" * 64)
        for j in d["also"]:
            add(f"  {j['_score']:>5.0f}  {j.get('company_canonical') or j['company']} - {j['title'][:52]}")
            add(f"         {j.get('url', '')}")
        add("")

    lc = d["leetcode"]
    stats = d["leetcode_stats"]
    add("LEETCODE TODAY" + ("  [INTERVIEW MODE: volume increased]" if lc["interview_mode"] else ""))
    add("-" * 64)
    add(f"  Working through: {lc['pattern']}   "
        f"({stats['attempted']}/{stats['total']} seen, Blind 75: {stats['blind75_done']}/75, streak {stats['streak']}d)")
    for p_ in lc["reviews"]:
        add(f"  REVIEW  [{p_['difficulty']:<6}] {p_['title']}  (due {p_['due_on']}, last: {p_['last_rating']})")
        add(f"          {p_['url']}")
    for p_ in lc["new"]:
        tag = "Blind75" if p_["blind75"] else p_["pattern"]
        add(f"  NEW     [{p_['difficulty']:<6}] {p_['title']}  ({tag})")
        add(f"          {p_['url']}")
    if lc["reviews"] or lc["new"]:
        add("  log it: python3 -m recruit lc log <slug> solved|hint|struggled|failed --minutes 25")
    add("")

    if d["outreach"]:
        add("OUTREACH THIS WEEK")
        add("-" * 64)
        for s in d["outreach"]:
            add(f"  {s['company']}  ({s['reason']})")
            add(f"      python3 -m recruit people \"{s['company']}\" --track {s['track']}")
        add("")

    if d["contacts_due"]:
        add("FOLLOW UP WITH")
        add("-" * 64)
        for c in d["contacts_due"]:
            add(f"  {c['name']} at {c['company']} - no reply in {c['days']}d  [{c['contact_id']}]")
        add("")

    if d["dte_watchlist"]:
        add("MONDAY: CHECK DEPLOYED / FORWARD-DEPLOYED ROLES BY HAND")
        add("-" * 64)
        add("  These rarely hit the job-board repos. Check the career pages directly:")
        for name, url in d["dte_watchlist"]:
            add(f"  {name:<20} {url}")
        add("")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _e(text):
    return html.escape(str(text or ""))


def _chip(text, bg, fg="#fff"):
    return (f'<span style="display:inline-block;background:{bg};color:{fg};font-size:11px;'
            f'font-weight:600;padding:2px 7px;border-radius:10px;margin-right:5px;">{_e(text)}</span>')


TIER_COLORS = {"tier1": "#1a7f37", "tier2": "#0969da", "quant": "#8250df", "other": "#6e7781"}
TRACK_COLORS = {"swe": "#24292f", "pm": "#bc4c00", "dte": "#0550ae"}


def render_html(d):
    parts = []
    add = parts.append
    pace = d["pace"]
    p = d["pipeline"]

    add(f'''<body style="margin:0;padding:0;background:#f6f8fa;">
<div style="max-width:680px;margin:0 auto;padding:20px 16px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2328;">
<h1 style="margin:0 0 4px;font-size:20px;">Recruiting brief</h1>
<div style="color:#656d76;font-size:13px;margin-bottom:16px;">{_e(d['date'].strftime('%A, %B %d, %Y'))}</div>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #d0d7de;border-radius:8px;margin-bottom:16px;">
<tr>
  <td style="padding:12px 14px;font-size:13px;">
    <b>{pace['applications_7d']}</b>/{pace['applications_target_7d']} applications this week
    &nbsp;&middot;&nbsp; <b>{pace['outreach_7d']}</b>/{pace['outreach_target_7d']} people contacted
    &nbsp;&middot;&nbsp; <b>{p['live']}</b> live applications
    &nbsp;&middot;&nbsp; <b>{d['new_today_count']}</b> new roles today
  </td>
</tr>
</table>''')

    if d["nudges"]:
        add('<h2 style="font-size:15px;margin:20px 0 8px;">Needs you first</h2>')
        for n in d["nudges"]:
            color = "#cf222e" if n["urgency"] == 0 else "#9a6700"
            add(f'''<div style="background:#fff;border:1px solid #d0d7de;border-left:3px solid {color};border-radius:6px;padding:10px 12px;margin-bottom:8px;font-size:13px;">
<b>{_e(n['company'])}</b> &middot; {_e(n['title'][:60])}<br>
<span style="color:{color};">{_e(n['what'])}</span>
</div>''')

    add(f'<h2 style="font-size:15px;margin:22px 0 8px;">Apply today &nbsp;<span style="color:#656d76;font-weight:400;font-size:13px;">{len(d["apply_now"])} picked from {d["live_count"]} matching</span></h2>')
    if not d["apply_now"]:
        add('<div style="background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:14px;font-size:13px;color:#656d76;">Nothing new above the bar today. Spend the time on outreach or LeetCode instead.</div>')
    for j in d["apply_now"]:
        tier = j.get("tier", "other")
        chips = _chip(TRACK_NAMES.get(j.get("track"), "?"), TRACK_COLORS.get(j.get("track"), "#57606a"))
        if TIER_NAMES.get(tier):
            chips += _chip(TIER_NAMES[tier], TIER_COLORS.get(tier, "#6e7781"))
        if j.get("salary"):
            chips += _chip(j["salary"], "#eaeef2", "#24292f")
        add(f'''<table width="100%" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #d0d7de;border-radius:6px;margin-bottom:10px;">
<tr><td style="padding:12px 14px;">
  <div style="font-size:11px;color:#656d76;float:right;">score {j['_score']:.0f}</div>
  <div style="font-size:15px;font-weight:600;margin-bottom:2px;">{_e(j.get('company_canonical') or j['company'])}</div>
  <div style="font-size:13px;margin-bottom:6px;">{_e(j['title'])}</div>
  <div style="margin-bottom:8px;">{chips}</div>
  <div style="font-size:12px;color:#656d76;margin-bottom:4px;">{_e(j.get('locations', ''))}</div>
  <div style="font-size:12px;color:#656d76;margin-bottom:10px;">{_e(j.get('reasons', ''))}</div>
  <a href="{_e(j.get('url', ''))}" style="display:inline-block;background:#1f883d;color:#fff;text-decoration:none;font-size:13px;font-weight:600;padding:6px 14px;border-radius:6px;">Apply</a>
  <code style="font-size:11px;color:#656d76;margin-left:10px;">recruit applied {_e(j['id'])}</code>
</td></tr></table>''')

    if d["also"]:
        add('<h2 style="font-size:15px;margin:22px 0 8px;">Also worth a look</h2><div style="background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:6px 14px;font-size:13px;">')
        for j in d["also"]:
            add(f'<div style="padding:6px 0;border-bottom:1px solid #eaeef2;"><a href="{_e(j.get("url", ""))}" style="color:#0969da;text-decoration:none;font-weight:600;">{_e(j.get("company_canonical") or j["company"])}</a> &middot; {_e(j["title"][:64])} <span style="color:#8c959f;font-size:11px;">({j["_score"]:.0f})</span></div>')
        add("</div>")

    lc, stats = d["leetcode"], d["leetcode_stats"]
    banner = ' <span style="color:#cf222e;font-size:12px;">interview mode</span>' if lc["interview_mode"] else ""
    add(f'''<h2 style="font-size:15px;margin:22px 0 8px;">LeetCode today{banner}</h2>
<div style="background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:12px 14px;font-size:13px;">
<div style="color:#656d76;font-size:12px;margin-bottom:10px;">
Pattern: <b style="color:#1f2328;">{_e(lc['pattern'])}</b> &middot; {stats['attempted']}/{stats['total']} seen &middot; Blind 75: {stats['blind75_done']}/75 &middot; {stats['streak']} day streak
</div>''')
    for p_ in lc["reviews"]:
        add(f'<div style="padding:5px 0;">{_chip("review", "#9a6700")}<a href="{_e(p_["url"])}" style="color:#0969da;text-decoration:none;">{_e(p_["title"])}</a> <span style="color:#8c959f;font-size:11px;">{_e(p_["difficulty"])} &middot; due {_e(p_["due_on"])}</span></div>')
    for p_ in lc["new"]:
        add(f'<div style="padding:5px 0;">{_chip("new", "#0969da")}<a href="{_e(p_["url"])}" style="color:#0969da;text-decoration:none;">{_e(p_["title"])}</a> <span style="color:#8c959f;font-size:11px;">{_e(p_["difficulty"])} &middot; {_e(p_["pattern"])}{" &middot; Blind 75" if p_["blind75"] else ""}</span></div>')
    add('<div style="margin-top:10px;"><code style="font-size:11px;color:#656d76;">recruit lc log &lt;slug&gt; solved|hint|struggled|failed --minutes 25</code></div></div>')

    if d["outreach"]:
        add('<h2 style="font-size:15px;margin:22px 0 8px;">Outreach this week</h2><div style="background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:10px 14px;font-size:13px;">')
        for s in d["outreach"]:
            add(f'<div style="padding:6px 0;border-bottom:1px solid #eaeef2;"><b>{_e(s["company"])}</b> <span style="color:#656d76;font-size:12px;">{_e(s["reason"])}</span><br><code style="font-size:11px;color:#656d76;">recruit people "{_e(s["company"])}" --track {_e(s["track"])}</code></div>')
        add("</div>")

    if d["contacts_due"]:
        add('<h2 style="font-size:15px;margin:22px 0 8px;">Follow up with</h2><div style="background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:10px 14px;font-size:13px;">')
        for c in d["contacts_due"]:
            add(f'<div style="padding:4px 0;">{_e(c["name"])} at {_e(c["company"])} <span style="color:#656d76;font-size:12px;">no reply in {c["days"]}d</span></div>')
        add("</div>")

    if d["dte_watchlist"]:
        add('<h2 style="font-size:15px;margin:22px 0 8px;">Monday: check deployed / forward-deployed roles by hand</h2><div style="background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:10px 14px;font-size:13px;"><div style="color:#656d76;font-size:12px;margin-bottom:8px;">These roles almost never appear in the job-board repos, so the feed cannot find them for you.</div>')
        for name, url in d["dte_watchlist"]:
            add(f'<div style="padding:3px 0;"><a href="{_e(url)}" style="color:#0969da;text-decoration:none;">{_e(name)}</a></div>')
        add("</div>")

    add('<div style="color:#8c959f;font-size:11px;margin-top:24px;padding-top:12px;border-top:1px solid #d0d7de;">Generated by your recruiting command center. Sources: SimplifyJobs, vanshb03, speedyapply, jobright-ai.</div>')
    add("</div></body>")
    return "\n".join(parts)


def subject(d):
    n = len(d["apply_now"])
    urgent = len([x for x in d["nudges"] if x["urgency"] == 0])
    bits = [f"{n} to apply to"]
    if urgent:
        bits.insert(0, f"{urgent} URGENT")
    if d["leetcode"]["new"]:
        bits.append(d["leetcode"]["new"][0]["title"])
    return f"Recruiting brief {d['date'].strftime('%b %d')}: " + ", ".join(bits)
